#!/usr/bin/python
# Copyright 2019 Northern.tech AS
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
from helpers import Helpers
from common_update import common_update_procedure, update_image_successful
from MenderAPI import deploy, image
from mendertesting import MenderTesting
from common_setup import *
import shutil
from common import *

class TestUpdateModules(MenderTesting):
    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_one_docker_client_bootstrapped")
    def test_file_update_module(self):
        """Test the file based update module, first with a failed update, then
        a successful one."""

        if not env.host_string:
            execute(self.test_file_update_module,
                    hosts=get_mender_clients())
            return

        file_tree = tempfile.mkdtemp()
        try:
            files_and_content = ["file1", "file2"]

            for file_and_content in files_and_content:
                with open(os.path.join(file_tree, file_and_content), "w") as fd:
                    fd.write(file_and_content)

            # Use list as a trick to assign to this variable from inside the sub
            # function (lists are references).
            artifact_name = [None]
            def make_artifact(artifact_file, artifact_id):
                cmd = ("file-install-artifact-gen -o %s -n %s -t docker-client -d /tmp/test_file_update_module %s"
                       % (artifact_file, artifact_id, file_tree))
                logger.info("Executing: " + cmd)
                subprocess.check_call(cmd, shell=True)
                artifact_name[0] = artifact_id
                return artifact_file

            # Block the path with a file first
            run("touch /tmp/test_file_update_module")

            deployment_id, expected_image_id = common_update_procedure(make_artifact=make_artifact)
            deploy.check_expected_status("finished", deployment_id)
            deploy.check_expected_statistics(deployment_id, "failure", 1)

            output = run("mender -show-artifact").strip()
            assert output == "original"

            # Remove path block.
            run("rm -f /tmp/test_file_update_module")

            deployment_id, expected_image_id = common_update_procedure(make_artifact=make_artifact)
            deploy.check_expected_status("finished", deployment_id)
            deploy.check_expected_statistics(deployment_id, "success", 1)

            for file_and_content in files_and_content:
                output = run("cat /tmp/test_file_update_module/%s" % file_and_content).strip()
                assert output == file_and_content

            output = run("mender -show-artifact").strip()
            assert output == artifact_name[0]

        finally:
            shutil.rmtree(file_tree)

    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
    def test_rootfs_update_module_success(self):
        """Test the rootfs-image-v2 update module, which does the same as the
        built-in rootfs-image type."""

        if not env.host_string:
            execute(self.test_rootfs_update_module_success,
                    hosts=get_mender_clients())
            return

        def make_artifact(artifact_file, artifact_id):
            cmd = ("mender-artifact write module-image "
                   + "-o %s -n %s -t %s -T rootfs-image-v2 -f %s"
                   % (artifact_file, artifact_id, conftest.machine_name, conftest.get_valid_image()))
            logger.info("Executing: " + cmd)
            subprocess.check_call(cmd, shell=True)
            return artifact_file

        update_image_successful(make_artifact=make_artifact)
