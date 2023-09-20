# Copyright 2023 Northern.tech AS
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
    @staticmethod
    def identity_script_to_identity_string(output):
        data_dict = {}
        for line in output.rstrip().split("\n"):
            split = line.split("=", 2)
            assert len(split) == 2
            data_dict[split[0]] = split[1]

        return json.dumps(data_dict, separators=(",", ":"))

    @staticmethod
    def ip_to_device_id_map(device_group, devauth=devauth):
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
        identity_to_id = {}
        for dev in devauth_devices:
            identity_to_id[
                json.dumps(dev["identity_data"], separators=(",", ":"))
            ] = dev["id"]
        ip_to_device_id = {}
        for identity, ip in identity_to_ip.items():
            ip_to_device_id[ip] = identity_to_id[identity]

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
                "systemctl status --no-pager -l -n 100000 mender-updated"
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
