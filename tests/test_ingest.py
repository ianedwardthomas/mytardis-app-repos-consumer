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
from django.contrib.auth.models import User
from tardis.tardis_portal.models import UserProfile, ExperimentACL, Experiment

from tardis.tardis_portal.models import License


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

from flexmock import flexmock
from django.test import TestCase
from django.test.client import Client


from oaipmh.client import Client as oaipmhclient
from tardis.apps.reposconsumer import tasks


class TransferExpTest(TestCase):

    def setUp(self):
        self._client = Client()

    # def test_simple(self):
    #     """
    #     This is an initial test of a basic consumption of service
    #     """
    #     from oaipmh.client import Client
    #     from tardis.apps.reposconsumer import tasks

    #     user1, user2, exp = _create_test_data()
    #     # fake the OAIPMH connections
    #     identify_fake = flexmock(identify=lambda: identify_fake1)
    #     identify_fake1 = flexmock(baseURL=lambda:
    #         "http://127.0.0.1:9000/apps/oaimph")
    #     metadata_fake = flexmock()
    #     metadata_fake.should_receive('getField') \
    #         .and_return([str(exp.id)]) \
    #         .and_return([str(user1.id)])
    #     list_records_fake = flexmock(
    #         listRecords=lambda metadataPrefix: [({}, metadata_fake, {})])
    #     flexmock(Client).new_instances(identify_fake, list_records_fake)

    #     # fake the urllib2 based connections and the mets pull
    #     filename = path.join(path.abspath(path.dirname(__file__)), 'mets.xml')
    #     metsdata = open(filename, 'r').read()
    #     flexmock(tasks).should_receive('getURL') \
    #         .and_return('{"username":"%s","first_name":"%s"\
    #                 ,"last_name":"%s","email":"%s"}' %
    #             (user1.username, user1.first_name, user1.last_name,
    #              user1.email)) \
    #         .and_return(str(Experiment. PUBLIC_ACCESS_FULL)) \
    #         .and_return('[{"pluginId":"django_user","isOwner":true,\
    #             "entityId":"1"}]') \
    #         .and_return('{"username":"%s","first_name":"%s"\
    #             ,"last_name":"%s","email":"%s"}' %
    #             (user1.username, user1.first_name, user1.last_name,
    #              user1.email)) \
    #         .and_return(metsdata)

    #     from tardis.apps.reposconsumer.tasks import transfer_experiment
    #     local_ids = transfer_experiment("http://127.0.0.1:9000")
    #     #TODO: pull experiment at local_id and compare to original exp
    #     self.assertTrue(len(local_ids) == 1)
    #     for local_id in local_ids:
    #         self.assertTrue(int(local_id) > 0)


    def _setup_mocks(self,source):



        user1, user2, exp = _create_test_data()
        # fake the OAIPMH connections
        #identify_fake = flexmock(identify=lambda: identify_fake1)
        identify_fake1 = flexmock(baseURL=lambda:
            "http://127.0.0.1:9000/apps/oaimph")
        metadata_fake = flexmock()

        metadata_fake.should_receive('getField') \
            .with_args('identifier') \
            .and_return([str(exp.id)])

        metadata_fake.should_receive('getField') \
            .with_args('creator') \
            .and_return([str(user1.id)])


        fake = flexmock(identify=lambda: identify_fake1,
                        baseURL=lambda: "%s/apps/oaipmh" % source,
                        listRecords=lambda metadataPrefix:
                             [({}, metadata_fake, {})])
        flexmock(oaipmhclient).new_instances(fake)

        # fake the urllib2 based connections and the mets pull
        filename = path.join(path.abspath(path.dirname(__file__)), 'mets.xml')
        metsdata = open(filename, 'r').read()

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/user/%s/" % (source, user1.id)) \
                .and_return('{"username":"%s","first_name":"%s" \
                    ,"last_name":"%s","email":"%s"}' %
                (user1.username, user1.first_name, user1.last_name,
                 user1.email))

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/expstate/%s/"
            % (source, exp.id)) \
            .and_return(str(Experiment. PUBLIC_ACCESS_FULL))

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/acls/%s/" % (source, exp.id)) \
                .and_return('[{"pluginId":"django_user","isOwner":true,\
                "entityId":"1"},{"pluginId":"django_user","isOwner":true,\
                "entityId":"2"}]')

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/apps/reposproducer/user/%s/" % (source, user2.id)) \
           .and_return('{"username":"%s","first_name":"%s"\
                ,"last_name":"%s","email":"%s"}' %
                (user2.username, user2.first_name, user2.last_name,
                 user2.email))

        flexmock(tasks).should_receive('getURL').with_args(
            "%s/experiment/metsexport/%s/?force_http_urls" % (source, exp.id)) \
            .and_return(metsdata)




    def test_correct_run(self):
        """
        This is an initial test of a basic consumption of service
        """
        source = "http://127.0.0.1:9000"
        self._setup_mocks(source)

        from tardis.apps.reposconsumer.tasks import transfer_experiment
        local_ids = transfer_experiment(source)

        #TODO: pull experiment at local_id and compare to original exp
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
        class AttributeErrorFake:
            def __init__(self):
                raise AttributeError

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
        except IdDoesNotExistError:
            pass
        else:
            self.AssertTrue(False,"Expected IdDoesNotExistError")

