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
import pytest
from MenderAPI import logger

class Artifacts():
    artifacts_tool_path = "./mender-artifact"

    def make_artifact(self, image, device_type, artifact_name, artifact_file_created):

        if artifact_name.startswith("artifact_name="):
            artifact_name = artifact_name.split('=')[1]

        cmd = "%s write rootfs-image -u %s -t %s -n %s -o %s" % (self.artifacts_tool_path,
                                                                 image,
                                                                 device_type,
                                                                 artifact_name,
                                                                 artifact_file_created)
        logger.info("Running: " + cmd)

        try:
            subprocess.check_output(cmd, shell=True).strip()

        except subprocess.CalledProcessError:
            pytest.fail("Trying to create artifact failed.")
            return False

        except Exception, e:
            pytest.fail("Unexpted error trying to create artifact: %s, error: %s" % (artifact_name, str(e)))
            return False

        return True
