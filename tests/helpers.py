#!/usr/bin/python
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

import time
import subprocess
import logging
import random
import tempfile
import pytest
import os
import socket
import traceback
import json
from . import conftest

from MenderAPI import auth_v2

logger = logging.getLogger()

class Helpers:
    artifact_info_file = "/etc/mender/artifact_info"
    artifact_prefix = "artifact_name"

    @classmethod
    def yocto_id_from_ext4(self, filename):
        try:
            cmd = "debugfs -R 'cat %s' %s| sed -n 's/^%s=//p'" % (self.artifact_info_file, filename, self.artifact_prefix)
            output = subprocess.check_output(cmd, shell=True).strip()
            logger.info("Running: " + cmd + " returned: " + output)
            return output

        except subprocess.CalledProcessError:
            pytest.fail("Unable to read: %s, is it a broken image?" % (filename))

        except Exception as e:
            pytest.fail("Unexpected error trying to read ext4 image: %s, error: %s" % (filename, str(e)))

    @staticmethod
    def yocto_id_installed_on_machine(device):
        cmd = "mender -show-artifact"
        output = device.run(cmd, hide=True).strip()
        return output

    @staticmethod
    def get_active_partition(device):
        cmd = "mount | awk '/on \/ / { print $1}'"
        active = device.run(cmd, hide=True)
        return active.strip()

    @staticmethod
    def get_passive_partition(device):
        active = Helpers.get_active_partition(device)
        cmd = "fdisk -l | grep $(blockdev --getsz %s) | grep -v %s | awk '{ print $1}'" % (active, active)
        passive = device.run(cmd, hide=True)
        return passive.strip()

    @staticmethod
    # simulate broken internet by drop packets to gateway and fileserver
    def gateway_connectivity(
        device,
        accessible,
        hosts=["mender-artifact-storage.localhost", "mender-api-gateway"],
    ):
        try:
            for h in hosts:
                gateway_ip = device.run(
                    "nslookup %s | grep -A1 'Name:' | egrep '^Address( 1)?:'  | grep -oE '((1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])\.){3}(1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])'"
                    % (h),
                    hide=True,
                ).strip()

                if accessible:
                    logger.info("Allowing network communication to %s" % h)
                    device.run(
                        "iptables -D INPUT -s %s -j DROP" % (gateway_ip), hide=True
                    )
                    device.run(
                        "iptables -D OUTPUT -s %s -j DROP" % (gateway_ip), hide=True
                    )
                else:
                    logger.info("Disallowing network communication to %s" % h)
                    device.run(
                        "iptables -I INPUT 1 -s %s -j DROP" % gateway_ip, hide=True
                    )
                    device.run(
                        "iptables -I OUTPUT 1 -s %s -j DROP" % gateway_ip, hide=True
                    )
        except Exception as e:
            logger.info("Exception while messing with network connectivity: " + e)

    @staticmethod
    def identity_script_to_identity_string(output):
        data_dict = {}
        for line in output.split('\n'):
            split = line.split('=', 2)
            assert(len(split) == 2)
            data_dict[split[0]] = split[1]

        return json.dumps(data_dict, separators=(",", ":"))

    @staticmethod
    def ip_to_device_id_map(device_group):
        # Get deviceauth data, which includes device identity.
        devauth_devices = auth_v2.get_devices(expected_devices=len(device_group))

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
            ip_to_device_id[identity_to_ip[json.dumps(device['identity_data'], separators=(",", ":"))]] = device['id']

        return ip_to_device_id

    class RebootDetector:
        server = None
        device = None
        host_ip = None
        # This global one is used to increment each port used.
        port = 8181

        def __init__(self, device, host_ip):
            self.port = Helpers.RebootDetector.port
            Helpers.RebootDetector.port += 1
            self.host_ip = host_ip
            self.device = device

        def __enter__(self):
            local_name = "test.mender-reboot-detector.txt.%s" % self.device.host_string
            with open(local_name, "w") as fd:
                fd.write("%s:%d" % (self.host_ip, self.port))
            try:
                self.device.put(
                    local_name,
                    remote_path="/data/mender/test.mender-reboot-detector.txt",
                )
            finally:
                os.unlink(local_name)

            self.device.run("systemctl restart mender-reboot-detector")

            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((self.host_ip, self.port))
            self.server.listen(1)

            return self

        def __exit__(self, type, value, trace):
            if self.server:
                self.server.close()
            self.server = None

            cmd = "systemctl stop mender-reboot-detector ; rm -f /data/mender/test.mender-reboot-detector.txt"
            try:
                self.device.run(cmd)
            except:
                logger.error("Unable to stop reboot-detector:\n%s" % traceback.format_exc())
                # Only produce our own exception if we won't be hiding an
                # existing one.
                if type is None:
                    raise

        def verify_reboot_performed_impl(self, max_wait, number_of_reboots=1):
            up = True
            reboot_count = 0
            start_time = time.time()
            while True:
                try:
                    self.server.settimeout(start_time + max_wait - time.time())
                    connection, _ = self.server.accept()
                except socket.timeout:
                    logger.info("Client did not reboot in %d seconds" % max_wait)
                    return False

                message = connection.recv(4096).strip()
                connection.close()

                if message == "shutdown":
                    logger.debug("Got shutdown message from client")
                    if up:
                        up = False
                    else:
                        pytest.fail("Received message of shutdown when already shut down??")
                elif message == "startup":
                    logger.debug("Got startup message from client")
                    # Tempting to check up flag here, but in the spontaneous
                    # reboot case, we may not get the shutdown message.
                    up = True
                    reboot_count += 1
                else:
                    pytest.fail("Unexpected message from mender-reboot-detector")

                if reboot_count >= number_of_reboots:
                    logger.info("Client has rebooted %d time(s)" % reboot_count)
                    return True

        def verify_reboot_performed(self, max_wait=60*60, number_of_reboots=1):
            if self.server is None:
                pytest.fail("verify_reboot_performed() used outside of 'with' scope.")

            logger.info("Waiting for client to reboot %d time(s)" % number_of_reboots)
            if not self.verify_reboot_performed_impl(max_wait=max_wait, number_of_reboots=number_of_reboots):
                pytest.fail("Device never rebooted")

        def verify_reboot_not_performed(self, wait=60):
            if self.server is None:
                pytest.fail("verify_reboot_not_performed() used outside of 'with' scope.")

            logger.info("Waiting %d seconds to check that client does not reboot" % wait)
            if self.verify_reboot_performed_impl(max_wait=wait):
                pytest.fail("Device unexpectedly rebooted")
