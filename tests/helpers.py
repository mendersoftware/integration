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
import logging
import pytest
import json
import time
from . import conftest

from .MenderAPI import devauth

logger = logging.getLogger()


class Helpers:
    artifact_info_file = "/etc/mender/artifact_info"
    artifact_prefix = "artifact_name"

    @classmethod
    def yocto_id_from_ext4(self, filename):
        try:
            cmd = "debugfs -R 'cat %s' %s| sed -n 's/^%s=//p'" % (
                self.artifact_info_file,
                filename,
                self.artifact_prefix,
            )
            output = subprocess.check_output(cmd, shell=True).decode().strip()
            logger.info("Running: " + cmd + " returned: " + output)
            return output

        except subprocess.CalledProcessError:
            pytest.fail("Unable to read: %s, is it a broken image?" % (filename))

        except Exception as e:
            pytest.fail(
                "Unexpected error trying to read ext4 image: %s, error: %s"
                % (filename, str(e))
            )

    @staticmethod
    def identity_script_to_identity_string(output):
        data_dict = {}
        for line in output.rstrip().split("\n"):
            split = line.split("=", 2)
            assert len(split) == 2
            data_dict[split[0]] = split[1]

        return json.dumps(data_dict, separators=(",", ":"))

    @staticmethod
    def ip_to_device_id_map(device_group):
        # Get deviceauth data, which includes device identity.
        devauth_devices = devauth.get_devices(expected_devices=len(device_group))

        # Collect identity of each client.
        ret = device_group.run("/usr/share/mender/identity/mender-device-identity")

        # Calculate device identities.
        identity_to_ip = {}
        for device in device_group:
            identity_to_ip[
                Helpers.identity_script_to_identity_string(ret[device.host_string])
            ] = device.host_string

        # Match them.
        ip_to_device_id = {}
        for device in devauth_devices:
            ip_to_device_id[
                identity_to_ip[
                    json.dumps(device["identity_data"], separators=(",", ":"))
                ]
            ] = device["id"]

        return ip_to_device_id

    @staticmethod
    def check_log_have_authtoken(device):
        """Verify that the device was authenticated since its last service start."""
        sleepsec = 0
        MENDER_STORE_TIMEOUT = 600
        while sleepsec < MENDER_STORE_TIMEOUT:
            out = device.run(
                # Use systemctl instead of journalctl in order to get only
                # entries since the last service restart.
                "systemctl status --no-pager -l -n 100000 mender-client "
                + "| grep 'successfully received new authorization data'",
                warn=True,
            )
            if out != "":
                return

            time.sleep(10)
            sleepsec += 10
            logger.info(
                "waiting for authorization message in mender client log, sleepsec: {}".format(
                    sleepsec
                )
            )

        assert (
            sleepsec <= MENDER_STORE_TIMEOUT
        ), "timeout for mender-store file exceeded"
