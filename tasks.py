
from celery.task import task
from django.conf import settings
from os import path
import logging
import json

from tardis.tardis_portal.models import Experiment, ExperimentParameter, \
    DatafileParameter, DatasetParameter, ExperimentACL, Dataset_File, \
    DatafileParameterSet, ParameterName, GroupAdmin, Schema, \
    Dataset, ExperimentParameterSet, DatasetParameterSet, \
    License, UserProfile, UserAuthentication, Token

from urllib2 import Request, urlopen, URLError, HTTPError

from django.http import HttpResponse
from django.template import Context, loader

from tardis.tardis_portal.shortcuts import render_response_index, \
    return_response_error, return_response_not_found, \
    render_response_search, get_experiment_referer

from django.contrib.auth.models import User, Group, AnonymousUser
from tardis.tardis_portal.metsparser import parseMets


from django.db import transaction
from tardis.tardis_portal.ProcessExperiment import ProcessExperiment
from django.conf import settings
from tardis.tardis_portal.auth import auth_service
from tardis.tardis_portal.auth.localdb_auth import django_user, django_group


logger = logging.getLogger(__name__)


def _get_or_create_user(source, user_id):
    """
    Retrieves information about the user_id at the source
    and creates equivalent record here
    """
    # get the founduser
    try:
        request = Request("%s/apps/reposproducer/user/%s/"
            % (source, user_id), {}, {})
        response = urlopen(request)
        xmldata = response.read()
    except HTTPError as e:
        logger.error(e.read())
        raise e
    # FIXME: check for fail
    user_profile = json.loads(xmldata)
    # FIXME: check for fail
    # assume that usernames are unique
    found_user = User.objects.get(username=user_profile['username'])
    if not found_user:
        # FIXME: should new user have same id as original?
        user1 = User(username=user_profile['username'],
            first_name=user_profile['first_name'],
            last_name=user_profile['last_name'],
            email=user_profile['email'])
        user1.save()
        UserProfile(user=user1).save()
        found_user = user1
    return found_user


@task(name="reposconsumer.transfer_experiments", ignore_result=True)
def transfer_experiment(source=settings.SOURCEPROVIDER):
    """
    Pull public experiments from source into current repos
    """
    import pdb
    pdb.set_trace()
    #import nose.tools
    #nose.tools.set_trace()

    # Check identity of the feed
    from oaipmh.client import Client
    from oaipmh.metadata import MetadataRegistry, oai_dc_reader
    registry = MetadataRegistry()
    registry.registerReader('oai_dc', oai_dc_reader)
    source_url = "%s/apps/oaipmh/?verb=Identify" % source
    client = Client(source_url, registry)
    try:
        identify = client.identify()
    except AttributeError:
        logger.exception("error reading repos identity")
        return
    repos = identify.baseURL()
    import urlparse
    repos_url = urlparse.urlparse(repos)
    if "%s://%s" % (repos_url.scheme, repos_url.netloc) != source:
        # In deployment, this should throw exception
        logger.warn("Source directory reports incorrect name")

    # Get list of public experiments at source
    registry = MetadataRegistry()
    registry.registerReader('oai_dc', oai_dc_reader)
    client = Client(source
        + "/apps/oaipmh/?verb=ListRecords&metadataPrefix=oai_dc", registry)
    try:
        exps_metadata = [meta
            for (header, meta, extra)
            in client.listRecords(metadataPrefix='oai_dc')]
    except AttributeError:
        logger.exception("error reading experiment")
        return

    for exp_metadata in exps_metadata:
        exp_id = exp_metadata.getField('identifier')[0]
        user = exp_metadata.getField('creator')[0]

        found_user = _get_or_create_user(source, user)

        #make sure experiment is publicish
        try:
            request = Request("%s/apps/reposproducer/expstate/%s/"
                % (source, exp_id), {}, {})
            response = urlopen(request)
            xmldata = response.read()
        except HTTPError as e:
            logger.error(e.read())
            raise e
        try:
            exp_state = json.loads(xmldata)
        except ValueError as e:
            logger.error(e.read())
            raise e
        if not exp_state in [Experiment.PUBLIC_ACCESS_FULL,
                              Experiment.PUBLIC_ACCESS_METADATA]:
            logger.error('=== processing experiment %s: FAILED!' % exp_id)
            raise e

        # Get the usernames of isOwner django_user ACLs for the experiment
        try:
            request = Request("%s/apps/reposproducer/acls/%s/"
                % (source, exp_id), {}, {})
            response = urlopen(request)
            xmldata = response.read()
        except HTTPError as e:
            logger.error(e.read())
            raise e
        try:
            acls = json.loads(xmldata)
        except ValueError as e:
            logger.error(e.read())
            raise e
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
            request = Request("%s/experiment/metsexport/%s/"
                % (source, exp_id), {}, {})
            response = urlopen(request)
            metsxml = response.read()
        except HTTPError as e:
            logger.error(e.read())
            raise e

        # Make placeholder experiment and ready metadata
        e = Experiment(
            title='Placeholder Title',
            approved=True,
            created_by=found_user,
            public_access=exp_state
            )
        e.save()
        local_id = e.id
        filename = path.join(e.get_or_create_directory(),
                             'mets_upload.xml')
        f = open(filename, 'wb+')
        f.write(metsxml)
        f.close()

        # Ingest this experiment META data and isOwner ACLS
        try:
            _, sync_path = _registerExperimentDocument(filename=filename,
                                               created_by=found_user,
                                               expid=local_id,
                                               owners=owners)
            logger.info('=== processing experiment %s: DONE' % local_id)
        except:
            logger.exception('=== processing experiment %s: FAILED!'
                % local_id)
            return


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
        #logger.debug('processing simple xml')
        processExperiment = ProcessExperiment()
        eid, sync_root = processExperiment.process_simple(filename,
                                                          created_by,
                                                          expid)
    else:
        #logger.debug('processing METS')
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
