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
import re
import time

import pytest

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
            identity_to_id[json.dumps(dev["identity_data"], separators=(",", ":"))] = (
                dev["id"]
            )
        ip_to_device_id = {}
        for identity, ip in identity_to_ip.items():
            ip_to_device_id[ip] = identity_to_id[identity]

        return ip_to_device_id

    @staticmethod
    def _check_log_for_message(device, message, since=None):
        # Docker client has no systemd — check auth state via D-Bus instead.
        # Detect the running init system, not just the presence of the
        # systemctl binary (which exists in the Docker client image too).
        has_systemd = (
            device.run(
                "test -d /run/systemd/system && echo yes",
                warn=True,
                hide=True,
            ).strip()
            == "yes"
        )
        if not has_systemd:
            if "Successfully received new authorization data" in message:
                sleepsec = 0
                timeout = 600
                while sleepsec < timeout:
                    out = device.run(
                        "dbus-send --system --print-reply "
                        "--dest=io.mender.AuthenticationManager "
                        "/io/mender/AuthenticationManager "
                        "io.mender.Authentication1.GetJwtToken 2>/dev/null",
                        warn=True,
                        hide=True,
                    )
                    # GetJwtToken replies with the JWT as the first 'string'
                    # value; it is empty until the device has authenticated.
                    token = re.search(r'string "([^"]*)"', out or "")
                    if token and token.group(1):
                        return
                    time.sleep(10)
                    sleepsec += 10
                    logger.info(
                        f"waiting for device to authenticate via D-Bus, waited {sleepsec}s"
                    )
                assert False, "timeout waiting for device to authenticate via D-Bus"
            # Only the "authenticated" check is implemented over D-Bus. Fail
            # loudly rather than silently passing for any other log message.
            raise NotImplementedError(
                "log message check not implemented for docker client: %r" % message
            )

        if since:
            cmd = f"journalctl --unit mender-authd --full --since '{since}'"
        else:
            # Use systemctl instead of journalctl in order to get only
            # entries since the last service restart.
            cmd = f"systemctl status --no-pager --full --lines 100000 mender-authd"

        sleeptime = 2
        max_sleeptime = 10
        timeout = 600
        deadline = time.time() + timeout
        while time.time() < deadline:
            out = device.run(
                cmd + "| grep '" + message + "'",
                warn=True,
            )
            if out != "":
                return

            waited = int(timeout - (deadline - time.time()))
            logger.info(
                f"waiting for message '{message}' in mender-authd log, waited for: {waited}s"
            )
            time.sleep(sleeptime)
            sleeptime = min(sleeptime * 2, max_sleeptime)

        pytest.fail(
            f"timeout ({timeout}s) waiting for message '{message}' in mender-authd log"
        )

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

    @staticmethod
    def install_community_update_module(device, module):
        url = f"https://raw.githubusercontent.com/mendersoftware/mender-update-modules/master/{module}/module/{module}"
        device.run("mkdir -p /usr/share/mender/modules/v3")
        device.run(f"wget -P /usr/share/mender/modules/v3 {url}")
        device.run(f"chmod +x /usr/share/mender/modules/v3/{module}")
