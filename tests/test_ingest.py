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

from os import path
from flexmock import flexmock
from urllib2 import URLError, HTTPError
from django.test import TestCase
from django.test.client import Client
from django.conf import settings
from django.contrib.auth.models import User
from oaipmh.client import Client as oaipmhclient
from tardis.tardis_portal.models import UserProfile, ExperimentACL, Experiment, Author_Experiment
from tardis.tardis_portal.models import License, Schema, ParameterName
from tardis.apps.reposconsumer.tasks import OAIPMHError, ReposReadError, BadAccessError
from tardis.apps.reposconsumer.tasks import MetsParseError
from tardis.apps.reposconsumer import tasks
from tardis.tardis_portal.auth.localdb_auth import django_user, django_group



def _create_test_data():
    """
    Create Single experiment with two owners
    """
    user1 = User(username='tom',
                first_name='Thomas',
                last_name='Atkins',
                email='tommy@atkins.net')
    user1.save()
    UserProfile(user=user1).save()

    user2 = User(username='joe',
                first_name='Joe',
                last_name='Bloggs',
                email='joe@mail.com')
    user2.save()
    UserProfile(user=user2).save()

    license_ = License(name='Creative Commons Attribution-NoDerivs '
                            + '2.5 Australia',
                       url='http://creativecommons.org/licenses/by-nd/2.5/au/',
                       internal_description='CC BY 2.5 AU',
                       allows_distribution=True)
    license_.save()
    experiment = Experiment(title='Norwegian Blue',
                            description='Parrot + 40kV',
                            created_by=user1)
    experiment.public_access = Experiment.PUBLIC_ACCESS_FULL
    experiment.license = license_
    experiment.save()
    experiment.author_experiment_set.create(order=0,
                                        author="John Cleese",
                                        url="http://nla.gov.au/nla.party-1")
    experiment.author_experiment_set.create(order=1,
                                        author="Michael Palin",
                                        url="http://nla.gov.au/nla.party-2")

    acl1 = ExperimentACL(experiment=experiment,
                    pluginId='django_user',
                    entityId=str(user1.id),
                    isOwner=True,
                    canRead=True,
                    canWrite=True,
                    canDelete=True,
                    aclOwnershipType=ExperimentACL.OWNER_OWNED)
    acl1.save()

    acl2 = ExperimentACL(experiment=experiment,
                    pluginId='django_user',
                    entityId=str(user2.id),
                    isOwner=True,
                    canRead=True,
                    canWrite=True,
                    canDelete=True,
                    aclOwnershipType=ExperimentACL.OWNER_OWNED)
    acl2.save()

    return (user1, user2, experiment)


class TransferExpTest(TestCase):

    def setUp(self):
        self._client = Client()
        self.user1, self.user2, self.exp = _create_test_data()

    def _setup_mocks(self, source):

        # fake the OAIPMH connections
        #identify_fake = flexmock(identify=lambda: identify_fake1)
        identify_fake1 = flexmock(baseURL=lambda:
            "http://127.0.0.1:9000/apps/oaimph")
        metadata_fake = flexmock()

        metadata_fake.should_receive('getField') \
            .with_args('identifier') \
            .and_return([str(self.exp.id)])

        metadata_fake.should_receive('getField') \
            .with_args('creator') \
            .and_return([str(self.user1.id)])

        fake = flexmock(identify=lambda: identify_fake1,
                        baseURL=lambda: "%s/apps/oaipmh" % source,
                        listRecords=lambda metadataPrefix:
                             [({}, metadata_fake, {})])
        flexmock(oaipmhclient).new_instances(fake)

        # fake the urllib2 based connections and the mets pull
        filename = path.join(path.abspath(path.dirname(__file__)), 'mets.xml')
        metsdata = open(filename, 'r').read()

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/user/%s/" % (source, self.user1.id)) \
                .and_return('{"username":"%s","first_name":"%s" \
                    ,"last_name":"%s","email":"%s"}' %
                (self.user1.username, self.user1.first_name, self.user1.last_name,
                 self.user1.email))

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/expstate/%s/"
            % (source, self.exp.id)) \
            .and_return(str(Experiment. PUBLIC_ACCESS_FULL))

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/acls/%s/" % (source, self.exp.id)) \
                .and_return('[{"pluginId":"django_user","isOwner":true,\
                "entityId":"1"},{"pluginId":"django_user","isOwner":true,\
                "entityId":"2"}]')

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/user/%s/" % (source, self.user2.id)) \
           .and_return('{"username":"%s","first_name":"%s"\
                ,"last_name":"%s","email":"%s"}' %
                (self.user2.username, self.user2.first_name, self.user2.last_name,
                 self.user2.email))

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/experiment/metsexport/%s/?force_http_urls" % (source, self.exp.id)) \
            .and_return(metsdata)

        flexmock(tasks).should_receive('get_audit_message') \
            .and_return(" audit message here")

        sch, _ = Schema.objects.\
            get_or_create(namespace=settings.KEY_NAMESPACE,
             name="Experiment Key")
        pn, _ = ParameterName.objects.get_or_create(schema=sch, name=settings.KEY_NAME)
        pn.save()

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/key/%s/" % (source, self.exp.id)) \
           .and_return('"sdgfkhagkuashiuatihaghs7igtyweatihawtuhatjkhzsdg"')

    def test_correct_run(self):
        """
        This is an initial test of a basic consumption of service
        """
        source = "http://127.0.0.1:9000"
        self._setup_mocks(source)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        local_ids = transfer_experiment(source)

        #TODO: pull experiment at local_id and compare to original exp

        user1 = User.objects.get(username="tom")
        user2 = User.objects.get(username="joe")
        print("local_ids=%s" % local_ids)
        exp = Experiment.objects.get(id=local_ids[0])
        self.assertEquals(exp.title, "test1")  # from METS file
        self.assertEquals(exp.description, "this is the description audit message here")
        self.assertEquals(exp.created_by.username, user1.username)
        self.assertEquals(Author_Experiment.objects.filter(experiment=exp).count(), 2)
        from tardis.tardis_portal.models import ExperimentACL
        self.assertEquals(ExperimentACL.objects.filter(pluginId=django_user,
                                   experiment__id=exp.id,
                                   aclOwnershipType=ExperimentACL.OWNER_OWNED).count(), 2)



        self.assertTrue(len(local_ids) == 1)
        for local_id in local_ids:
            self.assertTrue(int(local_id) > 0)

    def test_no_repos(self):
        """Connection to a non-existence repository
        """
        source = "http://127.0.0.1:9000"
        self._setup_mocks(source)

        from oaipmh.error import IdDoesNotExistError

        # Needed as can't throw exceptions in lambdas
        class IdDoesNotExistErrorFake:
            def __init__(self):
                raise IdDoesNotExistError

        fake = flexmock(identify=IdDoesNotExistErrorFake)
        flexmock(oaipmhclient).new_instances(fake)
        #fake = flexmock().should_receive('identify').and_return("99").and_raise(AttributeError)
        #flexmock(Client).new_instances(fake)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        try:
            transfer_experiment(source)
        except OAIPMHError:
            pass
        else:
            self.assertTrue(False, "Expected OAIPMHError")

        self._setup_mocks(source)

        # Needed as can't throw exceptions in lambdas
        class AttributeErrorFake:
            def __init__(self):
                raise AttributeError

        fake = flexmock(identify=AttributeErrorFake)
        flexmock(oaipmhclient).new_instances(fake)
        #fake = flexmock().should_receive('identify').and_return("99").and_raise(AttributeError)
        #flexmock(Client).new_instances(fake)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        try:
            transfer_experiment(source)
        except ReposReadError:
            pass
        else:
            self.assertTrue(False, "Expected AttributeError")

        self._setup_mocks(source)

        # Needed as can't throw exceptions in lambdas
        class URLErrorFake:
            def __init__(self):
                raise URLError("problem connecting to the remote server")

        fake = flexmock(identify=URLErrorFake)
        flexmock(oaipmhclient).new_instances(fake)
        #fake = flexmock().should_receive('identify').and_return("99").and_raise(AttributeError)
        #flexmock(Client).new_instances(fake)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        try:
            transfer_experiment(source)
        except URLError:
            pass
        else:
            self.assertTrue(False, "Expected URLError")

        self._setup_mocks(source)
        identify_fake1 = flexmock(baseURL=lambda:
            "http://127.0.0.1:8032/apps/oaimph")

        fake = flexmock(identify=lambda: identify_fake1)
        flexmock(oaipmhclient).new_instances(fake)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        try:
            transfer_experiment(source)
        except BadAccessError:
            pass
        else:
            self.assertTrue(False, "Expected BadAccessError")

    def test_list_records(self):
        source = "http://127.0.0.1:9000"
        self._setup_mocks(source)

        # Needed as can't throw exceptions in lambdas
        class AttributeErrorFake:
            def __init__(self):
                raise AttributeError("problem with the attribute")

        fake = flexmock(listRecords=AttributeErrorFake)
        flexmock(oaipmhclient).new_instances(fake)

        identify_fake1 = flexmock(baseURL=lambda:
            "http://127.0.0.1:9000/apps/oaimph")

        fake = flexmock(identify=lambda: identify_fake1,
                        baseURL=lambda: "%s/apps/oaipmh" % source)
        #                listRecords=lambda metadataPrefix: AttributeErrorFake)
        fake.should_receive('listRecords').and_raise(AttributeErrorFake)
        flexmock(oaipmhclient).new_instances(fake)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        try:
            transfer_experiment(source)
        except OAIPMHError:
            pass
        else:
            self.assertTrue(False, "Expected OAIPMHError")

    def test_read_public_experiment(self):
        source = "http://127.0.0.1:9000"
        self._setup_mocks(source)

        # Needed as can't throw exceptions in lambdas

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/expstate/%s/" % (source, self.exp.id)).and_raise(HTTPError("", "", "", "", None))

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        try:
            transfer_experiment(source)
        except BadAccessError:
            pass
        else:
            self.assertTrue(False, "Expected BadAccessError")

    def test_mets_fails(self):
        source = "http://127.0.0.1:9000"
        self._setup_mocks(source)
        flexmock(tasks).should_receive("_registerExperimentDocument").and_raise(MetsParseError)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        try:
            transfer_experiment(source)
        except MetsParseError:
            pass
        else:
            self.assertTrue(False, "Expected MetsParseError")
