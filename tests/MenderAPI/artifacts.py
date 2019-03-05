#!/usr/bin/python
# Copyright 2017 Northern.tech AS
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

from MenderAPI import *
import os
import shutil


class Artifacts():
    artifacts_tool_path = "mender-artifact"

    def reset(self):
        # Reset all temporary values.
        pass

    def make_artifact(self, image, device_type, artifact_name, artifact_file_created, signed=False, scripts=[], global_flags="", version=None):
        signed_arg = ""

        if artifact_name.startswith("artifact_name="):
            artifact_name = artifact_name.split('=')[1]

        if signed:
            private_key = "../extra/signed-artifact-client-testing/private.key"
            assert os.path.exists(private_key), "private key for testing doesn't exist"
            signed_arg = "-k %s" % (private_key)

        cmd = ("%s %s  write rootfs-image -f %s -t %s -n %s -o %s %s %s"
               % (self.artifacts_tool_path,
                  global_flags,
                  image,
                  device_type,
                  artifact_name,
                  artifact_file_created.name,
                  signed_arg,
                  ("-v %d" % version) if version else ""
               )
        )
        for script in scripts:
            cmd += " -s %s" % script

        logger.info("Running: " + cmd)
        subprocess.check_call(cmd, shell=True)

        return artifact_file_created.name

    def get_mender_conf(self, image):
        """
        Get the /etc/mender/mender.conf from the artifact rootfs as a
        python dictionary.
        """
        conf = {}
        cmd = "debugfs -R 'cat /etc/mender/mender.conf' %s" % image

        output = subprocess.check_output("debugfs -R 'cat /etc/mender/mender.conf' " + \
                                             "core-image-full-cmdline-%s.ext4" % \
                                             conftest.machine_name, shell=True)
        import json
        conf = json.loads(output)

        return conf

    def replace_mender_conf(self, image, conf):
        """
        Get the /etc/mender/mender.conf from the artifact rootfs as a
        python dictionary.
        """
        tmp_conf_dir = os.path.join(os.path.curdir, "tmp_conf")
        try:
            os.mkdir(tmp_conf_dir)
            tmp_conf_path = os.path.join(tmp_conf_dir, "mender.conf")
            import json
            with open(tmp_conf_path, "w") as f:
                json.dump(conf, f, indent=2, sort_keys=True)
            debugfs_cmd = "cd /etc/mender/\n" + \
                          "rm mender.conf\n" + \
                          "write %s mender.conf\n" % tmp_conf_path + \
                          "close\n"

            cmd = "cat << EOF | debugfs -w %s\n%sEOF\n" % \
                  (image, debugfs_cmd)
            retcode = subprocess.call(cmd, shell=True)
            if retcode != 0:
                logger.fatal("debugfs returned status code: %s." % retcode)
        finally:
            shutil.rmtree(tmp_conf_dir)
        return conf

