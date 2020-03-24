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

import os
import subprocess
import tempfile
import shutil

from .. import conftest
from ..common_setup import (
    standard_setup_one_docker_client_bootstrapped,
    standard_setup_one_client_bootstrapped,
)
from .common_update import common_update_procedure, update_image
from ..MenderAPI import deploy, logger
from .mendertesting import MenderTesting


class TestUpdateModules(MenderTesting):
    @MenderTesting.fast
    def test_file_update_module(self, standard_setup_one_docker_client_bootstrapped):
        """Test the file based update module, first with a failed update, then
        a successful one."""

        mender_device = standard_setup_one_docker_client_bootstrapped.device

        file_tree = tempfile.mkdtemp()
        try:
            files_and_content = ["file1", "file2"]

            for file_and_content in files_and_content:
                with open(os.path.join(file_tree, file_and_content), "w") as fd:
                    fd.write(file_and_content)

            def make_artifact(artifact_file, artifact_id):
                cmd = (
                    "directory-artifact-gen -o %s -n %s -t docker-client -d /tmp/test_file_update_module %s"
                    % (artifact_file, artifact_id, file_tree)
                )
                logger.info("Executing: " + cmd)
                subprocess.check_call(cmd, shell=True)
                return artifact_file

            # Block the path with a file first
            mender_device.run("touch /tmp/test_file_update_module")

            # We use verify_status=False, because update module updates are so
            # quick that it sometimes races past the 'inprogress' status without
            # the test framework having time to register it. That's not really
            # the part we're interested in though, so just skip it.
            deployment_id, expected_image_id = common_update_procedure(
                make_artifact=make_artifact, verify_status=False
            )
            deploy.check_expected_statistics(deployment_id, "failure", 1)
            deploy.check_expected_status("finished", deployment_id)

            output = mender_device.run("mender -show-artifact").strip()
            assert output == "original"

            # Remove path block.
            mender_device.run("rm -f /tmp/test_file_update_module")

            deployment_id, expected_image_id = common_update_procedure(
                make_artifact=make_artifact, verify_status=False
            )
            deploy.check_expected_statistics(deployment_id, "success", 1)
            deploy.check_expected_status("finished", deployment_id)

            for file_and_content in files_and_content:
                output = mender_device.run(
                    "cat /tmp/test_file_update_module/%s" % file_and_content
                ).strip()
                assert output == file_and_content

            output = mender_device.run("mender -show-artifact").strip()
            assert output == expected_image_id

        finally:
            shutil.rmtree(file_tree)

    @MenderTesting.fast
    def test_rootfs_image_rejected(self, standard_setup_one_docker_client_bootstrapped):
        """Test that a rootfs-image update is rejected when such a setup isn't
        present."""

        mender_device = standard_setup_one_docker_client_bootstrapped.device

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

            deployment_id, _ = common_update_procedure(make_artifact=make_artifact)
            deploy.check_expected_status("finished", deployment_id)
            deploy.check_expected_statistics(deployment_id, "failure", 1)

            output = mender_device.run("mender -show-artifact").strip()
            assert output == "original"

            output = standard_setup_one_docker_client_bootstrapped.get_logs_of_service(
                "mender-client"
            )
            assert (
                "Artifact Payload type 'rootfs-image' is not supported by this Mender Client"
                in output
            )

        finally:
            shutil.rmtree(file_tree)

    @MenderTesting.fast
    def test_rootfs_update_module_success(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        """Test the rootfs-image-v2 update module, which does the same as the
        built-in rootfs-image type."""

        def make_artifact(artifact_file, artifact_id):
            cmd = (
                "mender-artifact write module-image "
                + "-o %s -n %s -t %s -T rootfs-image-v2 -f %s"
                % (artifact_file, artifact_id, conftest.machine_name, valid_image,)
            )
            logger.info("Executing: " + cmd)
            subprocess.check_call(cmd, shell=True)
            return artifact_file

        update_image(
            standard_setup_one_client_bootstrapped.device,
            standard_setup_one_client_bootstrapped.get_virtual_network_host_ip(),
            make_artifact=make_artifact,
        )
