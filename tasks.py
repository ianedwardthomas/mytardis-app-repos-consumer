# -*- coding: utf-8 -*-
#
# Copyright (c) 2012, RMIT eResearch Office
#   (RMIT University, Australia)
# Copyright (c) 2010-2012, Monash e-Research Centre
#   (Monash University, Australia)
# Copyright (c) 2010-2011, VeRSI Consortium
#   (Victorian eResearch Strategic Initiative, Australia)
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#    *  Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#    *  Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#    *  Neither the name of the VeRSI, the VeRSI Consortium members, nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE REGENTS AND CONTRIBUTORS BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
"""

.. moduleauthor::  Ian Thomas <ianedwardthomas@gmail.com>

"""

from celery.task import task
from django.conf import settings
from os import path
import logging
import json

from tardis.tardis_portal.models import Experiment, ExperimentACL, \
     UserProfile, Schema, ParameterName, ExperimentParameter, \
     ExperimentParameterSet

from urllib2 import Request, urlopen, URLError, HTTPError

from django.contrib.auth.models import User
from tardis.tardis_portal.metsparser import parseMets


from django.db import transaction
from tardis.tardis_portal.ProcessExperiment import ProcessExperiment
from tardis.tardis_portal.auth import auth_service
from tardis.tardis_portal.auth.localdb_auth import django_user

from django.core.urlresolvers import reverse

logger = logging.getLogger(__name__)


def getURL(source):
    request = Request(source, {}, {})
    response = urlopen(request)
    xmldata = response.read()
    return xmldata


def _get_or_create_user(source, user_id):
    """
    Retrieves information about the user_id at the source
    and creates equivalent record here
    """
    # get the founduser
    try:
        xmldata = getURL("%s/apps/reposproducer/user/%s/"
            % (source, user_id))
    except HTTPError as e:
        logger.exception("error getting user information")
        logger.error(e.read())
        return None
    try:
        user_profile = json.loads(xmldata)
    except ValueError as e:
        logger.error(e.read())
        logger.exception("cannot parse user information.")
        return None
    # NOTE: we assume that a person username is same across all nodes in BDP
    # FIXME: should new user have same id as original?

    found_user = None
    try:
        found_user = User.objects.get(username=user_profile['username'])
    except User.DoesNotExist as e:
        pass
    if not found_user:
        #FIXME: If there is a exception with readingfeeds, oaipmh from source,
        # then may end up with redundant users here.  Solution is to check for existing users,
        # and then create later once all source data has been fetched.
        user1 = User(username=user_profile['username'],
            first_name=user_profile['first_name'],
            last_name=user_profile['last_name'],
            email=user_profile['email'])
        user1.save()
        UserProfile(user=user1).save()
        found_user = user1

    return found_user


@task(name="reposconsumer.consume_experiments", ignore_result=True)
def transfer_experiment(source):
    """
    Pull public experiments from source into current mytardis.
    """

    #TODO: Cleanup error messages
    #NOTE: As this is a pull we trust the data from the other tardis
    # Check identity of the feed
    from oaipmh.client import Client
    from oaipmh import error
    from oaipmh.metadata import MetadataRegistry, oai_dc_reader

    from django.core.cache import cache
    from django.utils.hashcompat import md5_constructor as md5

    # The cache key consists of the task name and the MD5 digest
    # of the feed URL.
    cache_key  = md5("token").hexdigest()
    lock_id = "%s-lock-%s" % ("consume_experiment", cache_key)
    LOCK_EXPIRE = 60*5
    # cache.add fails if if the key already exists
    acquire_lock = lambda: cache.add(lock_id, "true", LOCK_EXPIRE)
    # memcache delete is very slow, but we have to use it to take
    # advantage of using add() for atomic locking
    release_lock = lambda: cache.delete(lock_id)

    registry = MetadataRegistry()
    registry.registerReader('oai_dc', oai_dc_reader)
    source_url = "%s/apps/oaipmh/?verb=Identify" % source

    client = Client(source_url, registry)
    try:
        identify = client.identify()
    except AttributeError as e:
        logger.exception("error reading repos identity")
        return
    except error.ErrorBase as e:
        logger.exception("OAIPMH.error")
        return
    except URLError as e:
        logger.exception("url access error for %s" % source_url)
        return

    repos = identify.baseURL()
    import urlparse
    repos_url = urlparse.urlparse(repos)
    if "%s://%s" % (repos_url.scheme, repos_url.netloc) != source:
        # In deployment, this should throw exception
        logger.exception("Source directory reports incorrect name")
        return
    # Get list of public experiments at sources
    registry = MetadataRegistry()
    registry.registerReader('oai_dc', oai_dc_reader)
    client = Client(source
        + "/apps/oaipmh/?verb=ListRecords&metadataPrefix=oai_dc", registry)
    try:
        exps_metadata = [meta
            for (header, meta, extra)
            in client.listRecords(metadataPrefix='oai_dc')]
    except AttributeError as e:
        logger.exception("error reading experiment %s" % e)
        return
    except error.NoRecordsMatchError as e:
        logger.warn("no public records found %s" % e)
        return

    local_ids = []
    for exp_metadata in exps_metadata:
        exp_id = exp_metadata.getField('identifier')[0]
        user = exp_metadata.getField('creator')[0]

        found_user = _get_or_create_user(source, user)

        #make sure experiment is publicish
        try:
            xmldata = getURL("%s/apps/reposproducer/expstate/%s/"
            % (source, exp_id))
        except HTTPError as e:
            logger.error(e.read())
            logger.exception("cannot get public state of experiment %s" % exp_id)
            return
        try:
            exp_state = json.loads(xmldata)
        except ValueError as e:
            logger.error(e.read())
            logger.exception("cannot parse public state of experiment %s" % exp_id)
            return
        if not exp_state in [Experiment.PUBLIC_ACCESS_FULL,
                              Experiment.PUBLIC_ACCESS_METADATA]:
            logger.error('=== processing experiment %s: FAILED!' % exp_id)
            return

        # Get the usernames of isOwner django_user ACLs for the experiment
        try:
            xmldata = getURL("%s/apps/reposproducer/acls/%s/"
            % (source, exp_id))

        except HTTPError as e:
            logger.error(e.read())
            logger.exception("cannot get acl list of experiment %s" % exp_id)
            return
        try:
            acls = json.loads(xmldata)
        except ValueError as e:
            logger.error(e.read())
            logger.exception("cannot parse acl list of experiment %s" % exp_id)
            return
        owners = []
        for acl in acls:
            if acl['pluginId'] == 'django_user' and acl['isOwner']:
                user = _get_or_create_user(source, acl['entityId'])
                owners.append(user.username)
            else:
                # FIXME: skips all other types of acl for now
                pass

        # Get the METS for the experiment
        metsxml = ""
        try:
            metsxml = getURL("%s/experiment/metsexport/%s/?force_http_urls"
            % (source, exp_id))
            #metsxml = getURL("%s/experiment/metsexport/%s/"
            #% (source, exp_id))

        except HTTPError as e:
            logger.error(e.read())
            logger.exception("cannot get METS for experiment %s" % exp_id)
            return

        # load schema and parametername for experiment keys
        try:
            key_schema = Schema.objects.get(namespace=settings.KEY_NAMESPACE)
        except Schema.DoesNotExist as e:
            logger.exception("No ExperimentKeyService Schema found")
            return

        try:
            key_name = ParameterName.objects.get(name=settings.KEY_NAME)
        except ParameterName.DoesNotExist as e:
            logger.exception("No ExperimentKeyService ParameterName found")
            return

        try:
            xmldata = getURL("%s/apps/reposproducer/key/%s/"
            % (source, exp_id))
        except HTTPError as e:
            logger.error(e.read())
            logger.exception("cannot get key of experiment %s" % exp_id)
            return
        if not xmldata:
            logger.warn("Unable to retrieve experiment %s key.  Will try again later" % exp_id)
            return

        try:
            key_value = json.loads(xmldata)
        except ValueError as e:
            logger.error(e.read())
            logger.exception("cannot parse key list of experiment %s" % exp_id)
            return
        if not key_value:
            logger.warn("Unable to retrieve experiment %s key value.  Will try again later" % exp_id)
            return


        logger.warn("retrieved key %s from experiment %s" % (key_value, exp_id))
        exps = Experiment.objects.all()

        got_lock = True
        if not acquire_lock():
            logger.warning("another work has access to consume experiment")
            return

        duplicate_exp = 0
        for exp in exps:
            #logger.warn("exp = %s" % exp.id)
            params = ExperimentParameter.objects.filter(name=key_name,
                                    parameterset__schema=key_schema,
                                    parameterset__experiment=exp)
            #logger.warn("params.count() = %s" % params.count())
            if params.count() >= 1:
                key = params[0].string_value
                if key == key_value:
                    duplicate_exp = exp.id
                    #logger.warn("found duplicate for %s" % duplicate_exp)
                    break

        if duplicate_exp:
            logger.warn("Found duplicate experiment form %s exp %s to  exp %s"
                % (source, exp_id, duplicate_exp))
            if got_lock:
                release_lock()
            return

        # TODO: Need someway of updating and existing experiment.  Problem is
        # that copy will have different id from original, so need unique identifier
        # to allow matching

        # We have not pulled everything we need from producer and are ready to create
        # experiment.

        # Make placeholder experiment and ready metadata
        e = Experiment(
            title='Placeholder Title',
            approved=True,
            created_by=found_user,
            public_access=exp_state,
            locked=False  # so experiment can then be altered.
            )
        e.save()

        # store the key
        #eps, was_created = ExperimentParameterSet.objects.\
        #    get_or_create(experiment=e, schema=key_schema)
        #if was_created:
        #    logger.warn("was created")
        #ep, was_created = ExperimentParameter.objects.get_or_create(parameterset=eps,
        #    name=key_name,
        #    string_value=key_value)
        #if was_created:
        #    logger.warn("was created again")
        #ep.save()

        if got_lock:
            release_lock()

        local_id = e.id
        filename = path.join(e.get_or_create_directory(),
                             'mets_upload.xml')
        f = open(filename, 'wb+')
        f.write(metsxml)
        f.close()

        # Ingest this experiment META data and isOwner ACLS
        eid = None
        try:
            eid, sync_path = _registerExperimentDocument(filename=filename,
                                               created_by=found_user,
                                               expid=local_id,
                                               owners=owners)
            logger.info('=== processing experiment %s: DONE' % local_id)
        except:
            logger.exception('=== processing experiment %s: FAILED!'
                % local_id)
            return

        # FIXME: if METS parse fails then we should go back and delete the placeholder experiment

        exp = Experiment.objects.get(id=eid)

        # so that tardis does not copy the data
        for datafile in exp.get_datafiles():
            datafile.stay_remote = True
            datafile.save()

        #import nose.tools
        #nose.tools.set_trace()
        # FIXME: reverse lookup of URLs seem quite slow.
        # TODO: put this information into specific metadata schema attached to experiment
        exp.description += get_audit_message(source, exp_id)
        exp.save()

        local_ids.append(local_id)
    return local_ids


def get_audit_message(source, exp_id):
    return "\nOriginally from %s/experiment/view/%s/\n" % (source, exp_id)


# TODO removed username from arguments
# FIXME: from tardis_portal_views as private.
@transaction.commit_on_success
def _registerExperimentDocument(filename, created_by, expid=None,
                                owners=[], username=None):
    '''
    Register the experiment document and return the experiment id.

    :param filename: path of the document to parse (METS or notMETS)
    :type filename: string
    :param created_by: a User instance
    :type created_by: :py:class:`django.contrib.auth.models.User`
    :param expid: the experiment ID to use
    :type expid: int
    :param owners: a list of owners
    :type owner: list
    :param username: **UNUSED**
    :rtype: int

    '''

    f = open(filename)
    firstline = f.readline()
    f.close()

    sync_root = ''
    if firstline.startswith('<experiment'):
        logger.debug('processing simple xml')
        processExperiment = ProcessExperiment()
        eid, sync_root = processExperiment.process_simple(filename,
                                                          created_by,
                                                          expid)
    else:
        logger.debug('processing METS')
        eid, sync_root = parseMets(filename, created_by, expid)

    auth_key = ''
    try:
        auth_key = settings.DEFAULT_AUTH
    except AttributeError:
        logger.error('no default authentication for experiment' +
            ' ownership set (settings.DEFAULT_AUTH)')

    force_user_create = False
    try:
        force_user_create = settings.DEFAULT_AUTH_FORCE_USER_CREATE
    except AttributeError:
        pass

    if auth_key:
        for owner in owners:
            # for each PI
            if not owner:
                continue

            owner_username = None
            if '@' in owner:
                owner_username = auth_service.getUsernameByEmail(auth_key,
                                    owner)
            if not owner_username:
                owner_username = owner

            owner_user = auth_service.getUser(auth_key, owner_username,
                      force_user_create=force_user_create)
            # if exist, create ACL
            if owner_user:
                #logger.debug('registering owner: ' + owner)
                e = Experiment.objects.get(pk=eid)

                acl = ExperimentACL(experiment=e,
                                    pluginId=django_user,
                                    entityId=str(owner_user.id),
                                    canRead=True,
                                    canWrite=True,
                                    canDelete=True,
                                    isOwner=True,
                                    aclOwnershipType=ExperimentACL.OWNER_OWNED)
                acl.save()

    return (eid, sync_root)
