#!/usr/bin/python
# Copyright 2017 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from fabric.api import *
import pytest
from common import *
from common_docker import *
from common_setup import *
from helpers import Helpers
from MenderAPI import auth, adm, deploy, image, logger, inv, deviceauth
from common_update import update_image_successful, update_image_failed, \
                          common_update_procedure
from mendertesting import MenderTesting
from tests import artifact_lock

@pytest.mark.skipif(len(conftest.mt_docker_compose_file) == 0,
                    reason="set --mt-docker-compose-file to run test")
class TestMultiTenancy(MenderTesting):
    def mender_log_contains_aborted_string(self, mender_client_container="mender-client"):
        expected_string = "deployment aborted at the backend"

        for _ in range(60*5):
            with settings(hide('everything'), warn_only=True):
                out = run("journalctl -u mender | grep \"%s\"" % expected_string)
                if out.succeeded:
                    return
                else:
                    time.sleep(2)

        pytest.fail("deployment never aborted.")

    def perform_update(self, mender_client_container="mender-client", fail=False):

        if fail:
            execute(update_image_failed,
                    hosts=get_mender_client_by_container_name(mender_client_container))
        else:
            execute(update_image_successful,
                    install_image=conftest.get_valid_image(),
                    skip_reboot_verification=True,
                    hosts=get_mender_client_by_container_name(mender_client_container))

    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_token_validity(self):
        """ verify that only devices with valid tokens can bootstrap
            successfully to a multitenancy setup """

        wrong_token = "wrong-token"

        def wait_until_bootstrap_attempt():
            if not env.host_string:
                return execute(wait_until_bootstrap_attempt,
                               hosts=get_mender_clients())
            ssh_is_opened()

            for i in range(1, 20):
                    with settings(hide('everything'), warn_only=True):
                        out = run('journalctl -u mender | grep "bootstrapped -> authorize-wait"')
                        if out.succeeded:
                            return True
                        time.sleep(20/i)
            return False

        def set_correct_tenant_token(token):
            if not env.host_string:
                return execute(set_correct_tenant_token,
                               token,
                               hosts=get_mender_clients())

            run("sed -i 's/%s/%s/g' /etc/mender/mender.conf" % (wrong_token, token))
            run("systemctl restart mender")

        auth.reset_auth_token()
        auth.new_tenant("admin", "bob@bob.com", "hunter2hunter2")
        token = auth.current_tenant["tenant_token"]

        # create a new client with an incorrect token set
        new_tenant_client("mender-client", wrong_token)

        if wait_until_bootstrap_attempt():
            for _ in range(5):
                time.sleep(5)
                adm.get_devices(expected_devices=0)  # make sure device not seen
        else:
            pytest.fail("failed to bootstrap device")

        # setting the correct token makes the client visible to the backend
        set_correct_tenant_token(token)
        adm.get_devices(expected_devices=1)

    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_artifacts_exclusive_to_user(self):
        users = [
            {"email": "foo1@foo1.com", "password": "hunter2hunter2", "username": "foo1"},
            {"email": "bar2@bar2.com", "password": "hunter2hunter2", "username": "bar2"},
        ]

        for user in users:
            auth.set_tenant(user["username"], user["email"], user["password"])
            with artifact_lock:
                with tempfile.NamedTemporaryFile() as artifact_file:
                    artifact = image.make_artifact(conftest.get_valid_image(),
                                                   conftest.machine_name,
                                                   user["email"],
                                                   artifact_file)

                    deploy.upload_image(artifact)

        for user in users:
            auth.set_tenant(user["username"], user["email"], user["password"])
            artifacts_for_user = deploy.get_artifacts()

            # make sure that one a single artifact exist for a given tenant
            assert len(artifacts_for_user)
            assert artifacts_for_user[0]["name"] == user["email"]

    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_clients_exclusive_to_user(self):
        users = [
            {
              "email": "foo1@foo1.com",
              "password": "hunter2hunter2",
              "username": "foo1",
              "container": "mender-client-exclusive-1",
              "client_id": "",
              "device_id": ""
            },
            {
               "email": "bar1@bar1.com",
               "password": "hunter2hunter2",
               "username": "bar1",
               "container": "mender-client-exclusive-2",
               "client_id": "",
               "device_id": ""
            }
        ]

        for user in users:
            auth.set_tenant(user["username"], user["email"], user["password"])

            t = auth.current_tenant["tenant_token"]
            new_tenant_client(user["container"], t)
            adm.accept_devices(1)

            # get the new devices client_id and setting it to the our test parameter
            assert len(inv.get_devices()) == 1
            user["client_id"] = inv.get_devices()[0]["id"]
            user["device_id"] = adm.get_devices()[0]["device_id"]

        for user in users:
            # make sure that the correct number of clients appear for the given tenant
            auth.set_tenant(user["username"], user["email"], user["password"])
            assert len(inv.get_devices()) == 1
            assert inv.get_devices()[0]["id"] == user["client_id"]

        for user in users:
            # wait until inventory is populated
            auth.set_tenant(user["username"], user["email"], user["password"])
            deviceauth.decommission(user["client_id"])
            timeout = time.time() + (60 * 5)
            device_id = user["device_id"]
            while time.time() < timeout:
                    newAdmissions = adm.get_devices()[0]
                    if device_id != newAdmissions["device_id"] \
                       and user["client_id"] != newAdmissions["id"]:
                        logger.info("device [%s] not found in inventory [%s]" % (device_id, str(newAdmissions)))
                        break
                    else:
                        logger.info("device [%s] found in inventory..." % (device_id))
                    time.sleep(.5)
            else:
                assert False, "decommissioned device still available in admissions"

    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_multi_tenancy_deployment(self):
        """ Simply make sure we are able to run the multi tenancy setup and
           bootstrap 2 different devices to different tenants """

        auth.reset_auth_token()

        users = [
            {
                "email": "foo2@foo2.com",
                "password": "hunter2hunter2",
                "username": "foo2",
                "container": "mender-client-deployment-1",
                "fail": False
            },
            {
                "email": "bar2@bar2.com",
                "password": "hunter2hunter2",
                "username": "bar2",
                "container": "mender-client-deployment-2",
                "fail": True
            }
        ]

        for user in users:
            auth.new_tenant(user["username"], user["email"], user["password"])
            t = auth.current_tenant["tenant_token"]
            new_tenant_client(user["container"], t)
            adm.accept_devices(1)

        for user in users:
            auth.new_tenant(user["username"], user["email"], user["password"])

            assert len(inv.get_devices()) == 1
            self.perform_update(mender_client_container=user["container"],
                                fail=user["fail"])


    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_multi_tenancy_deployment_aborting(self):
        """ Simply make sure we are able to run the multi tenancy setup and
           bootstrap 2 different devices to different tenants """

        auth.reset_auth_token()

        users = [
            {
                "email": "foo1@foo1.com",
                "password": "hunter2hunter2",
                "username": "foo1",
                "container": "mender-client-deployment-aborting-1",
            }
        ]

        for user in users:
            auth.new_tenant(user["username"], user["email"], user["password"])
            t = auth.current_tenant["tenant_token"]
            new_tenant_client(user["container"], t)
            adm.accept_devices(1)

        for user in users:
            deployment_id, _ = common_update_procedure(install_image=conftest.get_valid_image())
            deploy.abort(deployment_id)
            deploy.check_expected_statistics(deployment_id, "aborted", 1)

            execute(self.mender_log_contains_aborted_string,
                    hosts=get_mender_client_by_container_name(user["container"]))

    @MenderTesting.aws_s3
    @pytest.mark.usefixtures("standard_setup_one_client_bootstrapped_with_s3_and_mt")
    def test_multi_tenancy_deployment_s3(self):

        def verify_object_id_and_tagging():
            from boto3 import client

            tenant = auth.get_tenant_id()
            conn = client('s3')

            artifacts = deploy.get_artifacts()
            assert len(artifacts) == 1

            artifact_id = artifacts[0]["id"]

            # verify object ID of proper MT format
            for key in conn.list_objects(Bucket='mender-artifacts-int-testing-us')['Contents']:
                if key['Key'].startswith(tenant):
                    expectedObject = "%s/%s" % (tenant, artifact_id)
                    assert key['Key'] == expectedObject

            # verify tagging is working
            tags = conn.get_object_tagging(Bucket='mender-artifacts-int-testing-us', Key=expectedObject)["TagSet"][0]
            assert tags["Value"] == tenant
            assert tags["Key"] == "tenant_id"

            # Delete artifact and make sure it's really gone
            conn.delete_object(Bucket="mender-artifacts-int-testing-us",
                               Key=expectedObject)

            deploy.delete_artifact(artifact_id)

            conn.list_objects(Bucket='mender-artifacts-int-testing-us')

            for key in conn.list_objects(Bucket='mender-artifacts-int-testing-us').get('Contents', []):
                if key['Key'].startswith(tenant):
                    pytest.fail("failed to delete artifact from s3")

        auth.reset_auth_token()

        users = [
            {
                "email": "foo1@foo1.com",
                "password": "hunter2hunter2",
                "username": "foo1",
                "container": "mender-client-mt-s3",
            }
        ]

        for user in users:
            auth.new_tenant(user["username"], user["email"], user["password"])
            t = auth.current_tenant["tenant_token"]
            new_tenant_client(user["container"], t)
            adm.accept_devices(1)
            self.perform_update(mender_client_container=user["container"])
            verify_object_id_and_tagging()
