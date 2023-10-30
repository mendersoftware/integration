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

import logging
import json
import time

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
            # Strip the array from the reported identity
            dev["identity_data"]["mac"] = dev["identity_data"]["mac"][0]
            identity_to_id[
                json.dumps(dev["identity_data"], separators=(",", ":"))
            ] = dev["id"]
        ip_to_device_id = {}
        for identity, ip in identity_to_ip.items():
            ip_to_device_id[ip] = identity_to_id[identity]

        return ip_to_device_id

    @staticmethod
    def _check_log_for_message(device, message, since=None):
        if since:
            cmd = f"journalctl -u mender-authd -l -S '{since}'"
        else:
            # Use systemctl instead of journalctl in order to get only
            # entries since the last service restart.
            cmd = f"systemctl status --no-pager -l -n 100000 mender-authd"

        sleepsec = 0
        timeout = 600
        while sleepsec < timeout:
            out = device.run(cmd + "| grep '" + message + "'", warn=True,)
            if out != "":
                return

            time.sleep(10)
            sleepsec += 10
            logger.info(
                f"waiting for message '{message}' in mender-authd log, waited for: {sleepsec}"
            )

        assert (
            sleepsec <= timeout
        ), f"timeout for waiting for message '{message}' in mender-authd log"

    @staticmethod
    def check_log_is_authenticated(device, since=None):
        Helpers._check_log_for_message(
            device, "Successfully received new authorization data", since
        )

    @staticmethod
    def check_log_is_unauthenticated(device, since=None):
        Helpers._check_log_for_message(
            device, "Failed to authorize with the server", since
        )
