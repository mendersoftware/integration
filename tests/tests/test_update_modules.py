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
    enterprise_one_docker_client_bootstrapped,
)
from .common_update import common_update_procedure
from ..MenderAPI import DeviceAuthV2, Deployments, logger
from .mendertesting import MenderTesting


class BaseTestUpdateModules(MenderTesting):
    def do_test_rootfs_image_rejected(self, env):
        """Test that a update for a non-existing module is rejected when such a setup isn't
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
                    "mender-artifact write module-image "
                    + "-o %s -n %s -t docker-client -T nonexisting-module -f %s"
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

            output = mender_device.run("mender-update show-artifact").strip()
            assert output == "original"

            output = env.get_logs_of_service("mender-client")
            assert "Update Module not found for given artifact type" in output
            assert (
                "Cannot launch /usr/share/mender/modules/v3/nonexisting-module"
                in output
            )

        finally:
            shutil.rmtree(file_tree)


class TestUpdateModulesOpenSource(BaseTestUpdateModules):
    @MenderTesting.fast
    def test_rootfs_image_rejected(self, standard_setup_one_docker_client_bootstrapped):
        self.do_test_rootfs_image_rejected(
            standard_setup_one_docker_client_bootstrapped
        )


class TestUpdateModulesEnterprise(BaseTestUpdateModules):
    @MenderTesting.fast
    def test_rootfs_image_rejected(self, enterprise_one_docker_client_bootstrapped):
        self.do_test_rootfs_image_rejected(enterprise_one_docker_client_bootstrapped)
