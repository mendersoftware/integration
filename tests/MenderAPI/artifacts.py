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

class Artifacts():
    artifacts_tool_path = "mender-artifact"
    
    def make_artifact_with_scripts(self, image, device_type, artifact_name, scripts, artifact_file_created):
        if artifact_name.startswith("artifact_name="):
            artifact_name = artifact_name.split('=')[1]
     
        for scr in scripts:
            f = open(scr, 'w+')
            f.write("#!/bin/bash\necho `basename \"$0\"` >> \"/data/mender/scripts_exec\"\n")
            f.close()

        scr_cmd = '-s ' + ' -s '.join(scripts)

        cmd = "%s write rootfs-image -u %s -t %s -n %s -o %s %s" % (self.artifacts_tool_path,
                                                                 image,
                                                                 device_type,
                                                                 artifact_name,
                                                                 artifact_file_created.name,
                                                                 scr_cmd)
        logger.info("Running: " + cmd)
        subprocess.check_call(cmd, shell=True)

        return artifact_file_created.name


    def make_artifact(self, image, device_type, artifact_name, artifact_file_created):

        if artifact_name.startswith("artifact_name="):
            artifact_name = artifact_name.split('=')[1]

        cmd = "%s write rootfs-image -u %s -t %s -n %s -o %s" % (self.artifacts_tool_path,
                                                                 image,
                                                                 device_type,
                                                                 artifact_name,
                                                                 artifact_file_created.name)
        logger.info("Running: " + cmd)
        subprocess.check_call(cmd, shell=True)

        return artifact_file_created.name
