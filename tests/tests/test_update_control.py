# Copyright 2022 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


import json
import os
import tempfile
import pytest
import time
import uuid

from testutils.common import User, new_tenant_client, ApiClient
from testutils.infra.cli import CliTenantadm
import testutils.api.tenantadm as tenantadm

from .. import conftest
from ..common_setup import enterprise_no_client
from ..MenderAPI import (
    Authentication,
    Deployments,
    DeviceAuthV2,
    image,
    get_container_manager,
)


class TestUpdateControlEnterprise:
    def bp(self):
        if not self.DEBUG:
            return
        t = "/tmp/bp" + str(self.bpindex)
        while not os.path.exists(t):
            time.sleep(0.1)
        self.bpindex = self.bpindex + 1

    def test_update_control(
        self, enterprise_no_client, valid_image_with_mender_conf,
    ):
        """
        Schedule an update with a pause in ArtifactInstall_Enter,
        ArtifactReboot_Enter, and ArtifactCommit_Enter, then continue, after the
        client has reported the paused substate back to the server, all the way
        until the deployment is successfully finished.
        """
        self.DEBUG = True
        self.bpindex = 0
        self.bp()
        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}".format(uuidv4)
        email = "some.user+{}@example.com".format(uuidv4)
        u = User("", email, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=enterprise_no_client.name)
        tid = cli.create_org(tname, u.name, u.pwd, plan="enterprise")
        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]

        auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth = DeviceAuthV2(auth)

        device = new_tenant_client(enterprise_no_client, "mender-client", ttoken)
        devauth.accept_devices(1)

        deploy = Deployments(auth, devauth)

        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        mender_conf = device.run("cat /etc/mender/mender.conf")

        with tempfile.NamedTemporaryFile() as artifact_file:
            image.make_rootfs_artifact(
                valid_image_with_mender_conf(mender_conf),
                conftest.machine_name,
                "test-update-control",
                artifact_file.name,
            )

            deploy.upload_image(
                artifact_file.name, description="control map update test"
            )

        deployment_id = deploy.trigger_deployment(
            name="New valid update",
            artifact_name="test-update-control",
            devices=devices,
            update_control_map={
                "Priority": 1,
                "States": {"ArtifactInstall_Enter": {"action": "pause"}},
            },
        )

        # Query the deployment, and verify that the map returned contains the
        # deployment ID
        res_json = deploy.get_deployment(deployment_id)
        self.bp()
        assert deployment_id == res_json.get("update_control_map").get("id"), res_json

        # Wait for the device to pause in ArtifactInstall
        deploy.check_expected_statistics(deployment_id, "pause_before_installing", 1)
        deploy.patch_deployment(
            deployment_id,
            update_control_map={
                "Priority": 2,
                "States": {
                    "ArtifactInstall_Enter": {"action": "force_continue"},
                    "ArtifactReboot_Enter": {"action": "pause"},
                },
            },
        )

        # Wait for the device to pause in ArtifactReboot
        deploy.check_expected_statistics(deployment_id, "pause_before_rebooting", 1)
        deploy.patch_deployment(
            deployment_id,
            update_control_map={
                "Priority": 2,
                "States": {
                    "ArtifactReboot_Enter": {"action": "force_continue"},
                    "ArtifactCommit_Enter": {"action": "pause"},
                },
            },
        )

        # Wait for the device to pause in ArtifactCommit
        deploy.check_expected_statistics(deployment_id, "pause_before_committing", 1)
        deploy.patch_deployment(
            deployment_id,
            update_control_map={
                "Priority": 2,
                "States": {"ArtifactCommit_Enter": {"action": "force_continue"}},
            },
        )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)

    @pytest.mark.min_mender_client_version("3.2.1")
    def test_update_control_limit(
        self, enterprise_no_client, valid_image_with_mender_conf,
    ):
        """MEN-5421:

        Test that the client gracefully handles being rate-limited by the
        Mender server.

        Set the rate-limit to 1 request/ 60 seconds for the deployments/next
        endpoint, then schedule an update with a pause in ArtifactReboot_Enter
        only, then continue, after the client has reported the paused substate
        back to the server, all the way until the deployment is successfully
        finished.

        """

        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}".format(uuidv4)
        email = "some.user+{}@example.com".format(uuidv4)
        u = User("", email, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=enterprise_no_client.name)
        tid = cli.create_org(tname, u.name, u.pwd, plan="enterprise")

        # Rate-limit the /deployments/next endpoint
        tc = ApiClient(
            tenantadm.URL_INTERNAL,
            host=get_container_manager().get_ip_of_service("mender-tenantadm")[0]
            + ":8080",
            schema="http://",
        )

        r = tc.call(
            "PUT",
            tenantadm.URL_INTERNAL_TENANTS + "/" + tid,
            body={
                "api_limits": {
                    "devices": {
                        "bursts": [
                            {
                                "action": "POST",
                                "uri": "/api/devices/v2/deployments/device/deployments/next",
                                "min_interval_sec": 60,
                            }
                        ],
                    }
                }
            },
        )

        assert r.ok, "Failed to set the rate-limit on the 'deployements/next' endpoint"

        time.sleep(10)

        r = tc.call("GET", tenantadm.URL_INTERNAL_TENANTS + "/" + tid,)
        resp_json = r.json()
        if (
            resp_json.get("api_limits", {})
            .get("devices", {})
            .get("bursts", [{}])[0]
            .get("min_interval_sec")
            != 60
        ):
            pytest.fail("rate limits not enabled. The test is invalid")

        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]

        auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth = DeviceAuthV2(auth)

        device = new_tenant_client(enterprise_no_client, "mender-client", ttoken)
        devauth.accept_devices(1)

        deploy = Deployments(auth, devauth)

        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        mender_conf = device.run("cat /etc/mender/mender.conf")

        with tempfile.NamedTemporaryFile() as artifact_file:
            image.make_rootfs_artifact(
                valid_image_with_mender_conf(mender_conf),
                conftest.machine_name,
                "test-update-control",
                artifact_file.name,
            )

            deploy.upload_image(
                artifact_file.name, description="control map update test"
            )

        deployment_id = deploy.trigger_deployment(
            name="New valid update",
            artifact_name="test-update-control",
            devices=devices,
            update_control_map={
                "Priority": 1,
                "States": {"ArtifactReboot_Enter": {"action": "pause"}},
            },
        )

        # Query the deployment, and verify that the map returned contains the
        # deployment ID
        res_json = deploy.get_deployment(deployment_id)
        assert deployment_id == res_json.get("update_control_map").get("id"), res_json

        # Wait for the device to pause in ArtifactInstall
        deploy.check_expected_statistics(deployment_id, "pause_before_rebooting", 1)
        deploy.patch_deployment(
            deployment_id,
            update_control_map={
                "Priority": 2,
                "States": {"ArtifactReboot_Enter": {"action": "force_continue"},},
            },
        )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)

    def test_update_control_with_broken_map(
        self, enterprise_no_client, valid_image,
    ):
        """
        Schedule an update with an invalid map, which should fail.
        """

        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}".format(uuidv4)
        email = "some.user+{}@example.com".format(uuidv4)
        u = User("", email, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=enterprise_no_client.name)
        tid = cli.create_org(tname, u.name, u.pwd, plan="enterprise")
        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]

        auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth = DeviceAuthV2(auth)

        new_tenant_client(enterprise_no_client, "mender-client", ttoken)
        devauth.accept_devices(1)

        deploy = Deployments(auth, devauth)

        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        with tempfile.NamedTemporaryFile() as artifact_file:
            image.make_rootfs_artifact(
                valid_image,
                conftest.machine_name,
                "test-update-control",
                artifact_file.name,
            )

            deploy.upload_image(
                artifact_file.name, description="control map update test"
            )

        deployment_id = deploy.trigger_deployment(
            name="New valid update",
            artifact_name="test-update-control",
            devices=devices,
            update_control_map={
                "Priority": 1,
                "States": {"BogusState_Enter": {"action": "pause"}},
            },
        )

        # Query the deployment, and verify that the map returned contains the
        # deployment ID
        res_json = deploy.get_deployment(deployment_id)
        assert deployment_id == res_json.get("update_control_map").get("id"), res_json

        # Wait for the device to reject it and fail.
        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "failure", 1)

    def test_update_control_with_expiring_control_map(
        self, enterprise_no_client, valid_image_with_mender_conf,
    ):
        """Run an update, in which the download stage takes longer than the
        expiry time of the control map.

        In other words, test MEN-5096.

        This is done by having an Artifact script pause in Download for a time
        longer than the UpdateControlMapExpiration time. This will only pass if
        the client renewes the control map.
        """
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        u = User("", user_name, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=enterprise_no_client.name)
        tid = cli.create_org("enterprise-tenant", u.name, u.pwd, "enterprise")
        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]

        auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth = DeviceAuthV2(auth)

        device = new_tenant_client(enterprise_no_client, "mender-client", ttoken)
        devauth.accept_devices(1)

        deploy = Deployments(auth, devauth)

        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        mender_conf = device.run("cat /etc/mender/mender.conf")
        with tempfile.NamedTemporaryFile(
            prefix="Download_Leave_01_", mode="w"
        ) as sleep_script:
            expiration = int(
                json.loads(mender_conf)["UpdateControlMapExpirationTimeSeconds"]
            )
            sleep_script.writelines(
                ["#! /bin/bash\n", "sleep {}".format(expiration + 60)]
            )
            sleep_script.flush()
            os.fchmod(sleep_script.fileno(), 0o0755)
            device.put(
                os.path.basename(sleep_script.name),
                local_path=os.path.dirname(sleep_script.name),
                remote_path="/etc/mender/scripts/",
            )

        with tempfile.NamedTemporaryFile() as artifact_file:
            created_artifact = image.make_rootfs_artifact(
                valid_image_with_mender_conf(mender_conf),
                conftest.machine_name,
                "test-update-control",
                artifact_file.name,
            )

            deploy.upload_image(
                artifact_file.name, description="control map update test"
            )

        deployment_id = deploy.trigger_deployment(
            name="New valid update",
            artifact_name="test-update-control",
            devices=devices,
            update_control_map={
                "Priority": 1,
                "States": {"ArtifactInstall_Enter": {"action": "pause",},},
            },
        )

        # Query the deployment, and verify that the map returned contains the
        # deployment ID
        res_json = deploy.get_deployment(deployment_id)
        assert deployment_id == res_json.get("update_control_map").get("id"), res_json

        deploy.check_expected_statistics(deployment_id, "pause_before_installing", 1)
        deploy.patch_deployment(
            deployment_id,
            update_control_map={
                "Priority": 2,
                "States": {"ArtifactInstall_Enter": {"action": "force_continue",},},
            },
        )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)
