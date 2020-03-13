#!/usr/bin/python
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
        mender_device.run(
            'journalctl -u mender-client | grep "authentication request rejected server error message: Unauthorized"',
            wait=70,
        )

        for _ in range(5):
            time.sleep(5)
            auth_v2.get_devices(expected_devices=0)  # make sure device not seen

        # setting the correct token makes the client visible to the backend
        mender_device.run(
            "sed -i 's/%s/%s/g' /etc/mender/mender.conf" % (wrong_token, token)
        )
        mender_device.run("systemctl restart mender-client")

        auth_v2.get_devices(expected_devices=1)

    def test_artifacts_exclusive_to_user(self, enterprise_no_client):
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
                        conftest.get_valid_image(),
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

    def test_multi_tenancy_deployment(self, enterprise_no_client):
        """ Simply make sure we are able to run the multi tenancy setup and
           bootstrap 2 different devices to different tenants """

        auth.reset_auth_token()

        users = [
            {
                "email": "foo2@foo2.com",
                "password": "hunter2hunter2",
                "username": "foo2",
                "container": "mender-client-deployment-1",
                "fail": False,
            },
            {
                "email": "bar2@bar2.com",
                "password": "hunter2hunter2",
                "username": "bar2",
                "container": "mender-client-deployment-2",
                "fail": True,
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
            if user["fail"]:
                update_image_failed(mender_device, host_ip)
            else:
                update_image(
                    mender_device,
                    host_ip,
                    install_image=conftest.get_valid_image(),
                    skip_reboot_verification=True,
                )

    def test_multi_tenancy_deployment_aborting(self, enterprise_no_client):
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
            deployment_id, _ = common_update_procedure(
                install_image=conftest.get_valid_image()
            )
            deploy.abort(deployment_id)
            deploy.check_expected_statistics(deployment_id, "aborted", 1)

            mender_device = MenderDevice(
                enterprise_no_client.get_mender_client_by_container_name(
                    user["container"]
                )
            )
            mender_device.run(
                'journalctl -u mender-client | grep "deployment aborted at the backend"',
                wait=600,
            )

    def test_update_provides_depends(self, enterprise_no_client):
        """
        Perform two consecutive updates, the first adds virtual provides
        to the artifact and the second artifact depends on these provides.
        """

        DEMO_POLL_INTERVAL = 5
        IMAGE_NAME = "core-image-full-cmdline-qemux86-64.ext4"

        # Create tenant user
        auth.reset_auth_token()
        auth.new_tenant("admin", "bob@builder.org", "secret-service")
        token = auth.current_tenant["tenant_token"]

        # Create client setup with tenant token
        enterprise_no_client.new_tenant_client("mender-client", token)
        mender_device = MenderDevice(enterprise_no_client.get_mender_clients()[0])
        mender_device.host_ip = enterprise_no_client.get_virtual_network_host_ip()

        # Wait for ssh to be open
        mender_device.ssh_is_opened()
        # Check that the device has authorized with the backend.
        device = auth_v2.get_devices(expected_devices=1)
        device_ids = [device[0]["id"]]
        auth_v2.accept_devices(1)
        assert len(auth_v2.get_devices_status("accepted")) == 1

        # Update client with and artifact with custom provides
        def prepare_provides_artifact(artifact_filename, artifact_id):
            artifact = None
            try:
                f = open(artifact_filename, "w+b")
                artifact = image.make_rootfs_artifact(
                    IMAGE_NAME,
                    device_type="qemux86-64",
                    artifact_name=artifact_id,
                    artifact_file_created=f,
                    provides={"foo": "bar"},
                )
            finally:
                f.close()
            return artifact

        update_image(
            mender_device,
            mender_device.host_ip,
            make_artifact=prepare_provides_artifact,
        )

        # Issue another update which depends on the custom provides
        def prepare_depends_artifact(artifact_filename, artifact_id):
            artifact = None
            try:
                f = open(artifact_filename, "w+b")
                artifact = image.make_rootfs_artifact(
                    IMAGE_NAME,
                    device_type="qemux86-64",
                    artifact_name=artifact_id,
                    artifact_file_created=f,
                    depends={"foo": "bar"},
                )
            finally:
                f.close()
            return artifact

        update_image(
            mender_device,
            mender_device.host_ip,
            make_artifact=prepare_depends_artifact,
        )

        # Issue a third update with the same update as previous, this time
        # with insufficient provides -> no artifact status
        deployment_id, _ = common_update_procedure(
            make_artifact=prepare_depends_artifact, verify_status=False
        )

        # Retry for at most 60 seconds checking for deployment status update
        stat = None
        for i in range(60):
            time.sleep(1)
            stat = deploy.get_statistics(deployment_id)
            if stat.get("pending") == 0:
                break

        assert stat is not None
        assert stat.get("noartifact") == 1
