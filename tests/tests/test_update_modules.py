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

import os
import subprocess
import tempfile
import shutil

from .. import conftest
from ..common_setup import (
    standard_setup_one_docker_client_bootstrapped,
    standard_setup_one_client_bootstrapped,
    enterprise_one_docker_client_bootstrapped,
    enterprise_one_client_bootstrapped,
)
from .common_update import common_update_procedure, update_image
from ..MenderAPI import DeviceAuthV2, Deployments, logger
from .mendertesting import MenderTesting


class BaseTestUpdateModules(MenderTesting):
    def do_test_rootfs_image_rejected(self, env):
        """Test that a rootfs-image update is rejected when such a setup isn't
        present."""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        file_tree = tempfile.mkdtemp()
        try:
            file1 = os.path.join(file_tree, "file1")
            with open(file1, "w") as fd:
                fd.write("dummy")

            def make_artifact(artifact_file, artifact_id):
                cmd = (
                    "mender-artifact write rootfs-image -o %s -n %s -t docker-client -f %s"
                    % (artifact_file, artifact_id, file1)
                )
                logger.info("Executing: " + cmd)
                subprocess.check_call(cmd, shell=True)
                return artifact_file

            deployment_id, _ = common_update_procedure(
                make_artifact=make_artifact, devauth=devauth, deploy=deploy
            )
            deploy.check_expected_status("finished", deployment_id)
            deploy.check_expected_statistics(deployment_id, "failure", 1)

            output = mender_device.run("mender --no-syslog show-artifact").strip()
            # The update failed but the database got initialized with artifact-name "unknown"
            assert output == "unknown"

            output = env.get_logs_of_service("mender-client")
            assert (
                "Artifact Payload type 'rootfs-image' is not supported by this Mender Client"
                in output
            )

        finally:
            shutil.rmtree(file_tree)

    def do_test_rootfs_update_module_success(self, env, valid_image_with_mender_conf):
        """Test the rootfs-image-v2 update module, which does the same as the
        built-in rootfs-image type."""

        mender_conf = env.device.run("cat /etc/mender/mender.conf")
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        def make_artifact(artifact_file, artifact_id):
            cmd = (
                "mender-artifact write module-image "
                + "-o %s -n %s -t %s -T rootfs-image-v2 -f %s"
                % (
                    artifact_file,
                    artifact_id,
                    conftest.machine_name,
                    valid_image_with_mender_conf(mender_conf),
                )
            )
            logger.info("Executing: " + cmd)
            subprocess.check_call(cmd, shell=True)
            return artifact_file

        update_image(
            env.device,
            env.get_virtual_network_host_ip(),
            make_artifact=make_artifact,
            devauth=devauth,
            deploy=deploy,
        )


class TestUpdateModulesOpenSource(BaseTestUpdateModules):
    @MenderTesting.fast
    def test_rootfs_image_rejected(self, standard_setup_one_docker_client_bootstrapped):
        self.do_test_rootfs_image_rejected(
            standard_setup_one_docker_client_bootstrapped
        )

    @MenderTesting.fast
    def test_rootfs_update_module_success(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_rootfs_update_module_success(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
        )


class TestUpdateModulesEnterprise(BaseTestUpdateModules):
    @MenderTesting.fast
    def test_rootfs_image_rejected(self, enterprise_one_docker_client_bootstrapped):
        self.do_test_rootfs_image_rejected(enterprise_one_docker_client_bootstrapped)

    @MenderTesting.fast
    def test_rootfs_update_module_success(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_rootfs_update_module_success(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )
