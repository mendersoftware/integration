#!/usr/bin/python
# Copyright 2016 Mender Software AS
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

import subprocess
from MenderAPI import logger
import sys
sys.path.append('..')
import conftest
import os

class Artifacts():
    artifacts_tool_path = "mender-artifact"

    def make_artifact(self, image, device_type, artifact_name, artifact_file_created, signed=False):
        signed_arg = ""

        if artifact_name.startswith("artifact_name="):
            artifact_name = artifact_name.split('=')[1]

        if signed:
            private_key = "../extra/signed-artifact-client-testing/private.key"
            assert os.path.exists(private_key), "private key for testing doesn't exist"
            signed_arg = "-k %s" % (private_key)

        cmd = "%s write rootfs-image -u %s -t %s -n %s -o %s %s" % (self.artifacts_tool_path,
                                                                    image,
                                                                    device_type,
                                                                    artifact_name,
                                                                    artifact_file_created.name,
                                                                    signed_arg)
        logger.info("Running: " + cmd)
        subprocess.check_call(cmd, shell=True)

        return artifact_file_created.name
