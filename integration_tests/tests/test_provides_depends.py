#!/usr/bin/python
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

import subprocess
import time
import uuid

from integration_tests.common_setup import enterprise_no_client
from integration_tests.tests.common_update import update_image, common_update_procedure
from integration_tests.tests.mendertesting import MenderTesting
from integration_tests.MenderAPI import auth, devauth, deploy, logger

from integration_testutils.infra.device import MenderDevice


class TestProvidesDependsEnterprise(MenderTesting):
    def test_update_provides_depends(self, enterprise_no_client):
        """
        Perform two consecutive updates, the first adds virtual provides
        to the artifact and the second artifact depends on these provides.
        """
        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}".format(uuidv4)
        email = "some.user+{}@example.com".format(uuidv4)

        # Create tenant user
        auth.reset_auth_token()
        auth.new_tenant(tname, email, "secret-service", "enterprise")
        token = auth.current_tenant["tenant_token"]

        # Create client setup with tenant token
        enterprise_no_client.new_tenant_docker_client("mender-client", token)
        mender_device = MenderDevice(enterprise_no_client.get_mender_clients()[0])

        # Wait for ssh to be open
        mender_device.ssh_is_opened()
        # Check that the device has authorized with the backend.
        devauth.get_devices(expected_devices=1)
        devauth.accept_devices(1)
        assert len(devauth.get_devices_status("accepted")) == 1

        # Update client with and artifact with custom provides
        def prepare_provides_artifact(artifact_file, artifact_id):
            cmd = (
                # Package tests folder in the artifact, just a random folder.
                "directory-artifact-gen -o %s -n %s -t docker-client -d /tmp/test_file_update_module tests -- --provides rootfs-image.directory.foo:bar"
                % (artifact_file, artifact_id)
            )
            logger.info("Executing: " + cmd)
            subprocess.check_call(cmd, shell=True)
            return artifact_file

        deployment_id, _ = common_update_procedure(
            make_artifact=prepare_provides_artifact,
            # We use verify_status=False, because update module updates are so
            # quick that it sometimes races past the 'inprogress' status without
            # the test framework having time to register it. That's not really
            # the part we're interested in though, so just skip it.
            verify_status=False,
        )
        deploy.check_expected_status("finished", deployment_id)

        # Issue another update which depends on the custom provides
        def prepare_depends_artifact(artifact_file, artifact_id):
            cmd = (
                # Package tests folder in the artifact, just a random folder.
                "directory-artifact-gen -o %s -n %s -t docker-client -d /tmp/test_file_update_module tests -- --depends rootfs-image.directory.foo:bar"
                % (artifact_file, artifact_id)
            )
            logger.info("Executing: " + cmd)
            subprocess.check_call(cmd, shell=True)
            return artifact_file

        deployment_id, _ = common_update_procedure(
            make_artifact=prepare_depends_artifact, verify_status=False,
        )
        deploy.check_expected_status("finished", deployment_id)

        # Issue a third update with the same update as previous, this time
        # with insufficient provides -> no artifact status
        deployment_id, _ = common_update_procedure(
            make_artifact=prepare_depends_artifact, verify_status=False
        )

        # Retry for at most 60 seconds checking for deployment status update
        stat = None
        noartifact = 0
        for i in range(60):
            time.sleep(1)
            stat = deploy.get_statistics(deployment_id)
            if stat.get("noartifact") == 1:
                noartifact = 1
                break

        assert stat is not None
        assert noartifact == 1
