# Copyright 2020 Northern.tech AS
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

import tempfile
import time

from .. import conftest
from ..common_setup import enterprise_no_client
from .common_update import update_image, common_update_procedure
from ..MenderAPI import auth, auth_v2, deploy, image, logger, inv
from .mendertesting import MenderTesting
from . import artifact_lock

from testutils.infra.device import MenderDevice


class TestMultiTenancyEnterprise(MenderTesting):
    def test_token_validity(self, enterprise_no_client):
        """ verify that only devices with valid tokens can bootstrap
            successfully to a multitenancy setup """

        wrong_token = "wrong-token"

        auth.reset_auth_token()
        auth.new_tenant("admin", "bob@bob.com", "hunter2hunter2")
        token = auth.current_tenant["tenant_token"]

        # create a new client with an incorrect token set
        enterprise_no_client.new_tenant_client("mender-client", wrong_token)

        mender_device = MenderDevice(enterprise_no_client.get_mender_clients()[0])

        mender_device.ssh_is_opened()
        client_service_name = mender_device.get_client_service_name()
        mender_device.run(
            'journalctl -u %s | grep "authentication request rejected server error message: Unauthorized"'
            % client_service_name,
            wait=70,
        )

        for _ in range(5):
            time.sleep(5)
            auth_v2.get_devices(expected_devices=0)  # make sure device not seen

        # setting the correct token makes the client visible to the backend
        mender_device.run(
            "sed -i 's/%s/%s/g' /etc/mender/mender.conf" % (wrong_token, token)
        )
        mender_device.run("systemctl restart %s" % client_service_name)

        auth_v2.get_devices(expected_devices=1)

    def test_artifacts_exclusive_to_user(self, enterprise_no_client, valid_image):
        # extra long sleep to make sure all services ran their migrations
        # maybe conductor fails because some services are still in a migration phase,
        # and not serving the API yet?
        time.sleep(30)

        users = [
            {
                "email": "foo1@foo1.com",
                "password": "hunter2hunter2",
                "username": "foo1",
            },
            {
                "email": "bar2@bar2.com",
                "password": "hunter2hunter2",
                "username": "bar2",
            },
        ]

        for user in users:
            auth.set_tenant(user["username"], user["email"], user["password"])
            with artifact_lock:
                with tempfile.NamedTemporaryFile() as artifact_file:
                    artifact = image.make_rootfs_artifact(
                        valid_image,
                        conftest.machine_name,
                        user["email"],
                        artifact_file,
                    )

                    deploy.upload_image(artifact)

        for user in users:
            auth.set_tenant(user["username"], user["email"], user["password"])
            artifacts_for_user = deploy.get_artifacts()

            # make sure that one a single artifact exist for a given tenant
            assert len(artifacts_for_user)
            assert artifacts_for_user[0]["name"] == user["email"]

    def test_clients_exclusive_to_user(self, enterprise_no_client):
        users = [
            {
                "email": "foo1@foo1.com",
                "password": "hunter2hunter2",
                "username": "foo1",
                "container": "mender-client-exclusive-1",
                "client_id": "",
                "device_id": "",
            },
            {
                "email": "bar1@bar1.com",
                "password": "hunter2hunter2",
                "username": "bar1",
                "container": "mender-client-exclusive-2",
                "client_id": "",
                "device_id": "",
            },
        ]

        for user in users:
            auth.set_tenant(user["username"], user["email"], user["password"])

            t = auth.current_tenant["tenant_token"]
            enterprise_no_client.new_tenant_client(user["container"], t)
            auth_v2.accept_devices(1)

            # get the new devices client_id and setting it to the our test parameter
            assert len(inv.get_devices()) == 1
            user["client_id"] = inv.get_devices()[0]["id"]
            user["device_id"] = auth_v2.get_devices()[0]["id"]

        for user in users:
            # make sure that the correct number of clients appear for the given tenant
            auth.set_tenant(user["username"], user["email"], user["password"])
            assert len(inv.get_devices()) == 1
            assert inv.get_devices()[0]["id"] == user["client_id"]

        for user in users:
            # wait until inventory is populated
            auth.set_tenant(user["username"], user["email"], user["password"])
            auth_v2.decommission(user["client_id"])
            timeout = time.time() + (60 * 5)
            device_id = user["device_id"]
            while time.time() < timeout:
                newAdmissions = auth_v2.get_devices()[0]
                if (
                    device_id != newAdmissions["id"]
                    and user["client_id"] != newAdmissions["id"]
                ):
                    logger.info(
                        "device [%s] not found in inventory [%s]"
                        % (device_id, str(newAdmissions))
                    )
                    break
                else:
                    logger.info("device [%s] found in inventory..." % (device_id))
                time.sleep(0.5)
            else:
                assert False, "decommissioned device still available in inventory"

    def test_multi_tenancy_deployment(self, enterprise_no_client, valid_image):
        """ Simply make sure we are able to run the multi tenancy setup and
           bootstrap 2 different devices to different tenants """

        auth.reset_auth_token()

        users = [
            {
                "email": "foo2@foo2.com",
                "password": "hunter2hunter2",
                "username": "foo2",
                "container": "mender-client-deployment-1",
            },
            {
                "email": "bar2@bar2.com",
                "password": "hunter2hunter2",
                "username": "bar2",
                "container": "mender-client-deployment-2",
            },
        ]

        for user in users:
            auth.new_tenant(user["username"], user["email"], user["password"])
            t = auth.current_tenant["tenant_token"]
            enterprise_no_client.new_tenant_client(user["container"], t)
            auth_v2.accept_devices(1)

        for user in users:
            auth.new_tenant(user["username"], user["email"], user["password"])

            assert len(inv.get_devices()) == 1

            mender_device = MenderDevice(
                enterprise_no_client.get_mender_client_by_container_name(
                    user["container"]
                )
            )
            host_ip = enterprise_no_client.get_virtual_network_host_ip()
            update_image(
                mender_device, host_ip, install_image=valid_image,
            )

    def test_multi_tenancy_deployment_aborting(self, enterprise_no_client, valid_image):
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
            enterprise_no_client.new_tenant_client(user["container"], t)
            auth_v2.accept_devices(1)

        for user in users:
            deployment_id, _ = common_update_procedure(valid_image)
            deploy.abort(deployment_id)
            deploy.check_expected_statistics(deployment_id, "aborted", 1)

            mender_device = MenderDevice(
                enterprise_no_client.get_mender_client_by_container_name(
                    user["container"]
                )
            )
            mender_device.run(
                'journalctl -u %s | grep "deployment aborted at the backend"'
                % mender_device.get_client_service_name(),
                wait=600,
            )
