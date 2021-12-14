# Copyright 2021 Northern.tech AS
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
import tempfile
import uuid

from testutils.common import User, new_tenant_client
from testutils.infra.cli import CliTenantadm

from .. import conftest
from ..common_setup import enterprise_no_client
from ..MenderAPI import Authentication, Deployments, DeviceAuthV2, image


class TestUpdateControlEnterprise:
    def test_update_control(
        self, enterprise_no_client, valid_image_with_mender_conf,
    ):
        """
        Schedule an update with a pause in ArtifactInstall_Enter,
        ArtifactReboot_Enter, and ArtifactCommit_Enter, then continue, after the
        client has reported the paused substate back to the server, all the way
        until the deployment is successfully finished.
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

        device = new_tenant_client(
            enterprise_no_client, "control-map-test-container", ttoken
        )
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

        new_tenant_client(enterprise_no_client, "control-map-test-container", ttoken)
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
