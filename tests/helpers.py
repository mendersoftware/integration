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

import time
from fabric.api import *
from fabric.network import disconnect_all
import subprocess
import logging
import random
import tempfile
import pytest
import os
import socket
import traceback
import json
from fabric.contrib.files import exists
from . import conftest
from .common_docker import *
from .common import *

from MenderAPI import auth_v2

logger = logging.getLogger("root")

class FabricFatalException(BaseException):
    pass

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

        except Exception, e:
            pytest.fail("Unexpected error trying to read ext4 image: %s, error: %s" % (filename, str(e)))

    @classmethod
    def yocto_id_installed_on_machine(self):
        cmd = "mender -show-artifact"
        output = run(cmd).strip()
        return output

    @staticmethod
    def get_active_partition():
        cmd = "mount | awk '/on \/ / { print $1}'"
        with quiet():
            active = run(cmd)
        return active.strip()

    @staticmethod
    def get_passive_partition():
        active = Helpers.get_active_partition()
        cmd = "fdisk -l | grep $(blockdev --getsz %s) | grep -v %s | awk '{ print $1}'" % (active, active)
        with quiet():
            passive = run(cmd)
        return passive.strip()

    @staticmethod
    # simulate broken internet by drop packets to gateway and fileserver
    def gateway_connectivity(accessible, hosts=["mender-artifact-storage.localhost", "mender-api-gateway"]):
        try:
            with settings(hide('everything'), warn_only=True):
                for h in hosts:
                    gateway_ip = run("nslookup %s | grep -A1 'Name:' | egrep '^Address( 1)?:'  | grep -oE '((1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])\.){3}(1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])'" % (h)).strip()

                    if accessible:
                        logger.info("Allowing network communication to %s" % h)
                        run("iptables -D INPUT -s %s -j DROP" % (gateway_ip))
                        run("iptables -D OUTPUT -s %s -j DROP" % (gateway_ip))
                    else:
                        logger.info("Disallowing network communication to %s" % h)
                        run("iptables -I INPUT 1 -s %s -j DROP" % gateway_ip)
                        run("iptables -I OUTPUT 1 -s %s -j DROP" % gateway_ip)
        except Exception, e:
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
    def ip_to_device_id_map(clients):
        # Get deviceauth data, which includes device identity.
        devauth_devices = auth_v2.get_devices(expected_devices=len(clients))

        # Collect identity of each client.
        ret = execute(run, "/usr/share/mender/identity/mender-device-identity", hosts=clients)

        # Calculate device identities.
        identity_to_ip = {}
        for client in clients:
            identity_to_ip[Helpers.identity_script_to_identity_string(ret[client])] = client

        # Match them.
        ip_to_device_id = {}
        for device in devauth_devices:
            ip_to_device_id[identity_to_ip[json.dumps(device['identity_data'], separators=(",", ":"))]] = device['id']

        return ip_to_device_id

    @staticmethod
    def ssh_is_opened(host):
        @parallel
        def ssh_is_opened_impl(cmd="true", wait=60*60):
            count = 0
            sleeptime = 1

            while count < wait:
                try:
                    # no point in printing this with each test
                    with quiet():
                        return run(cmd)
                except BaseException:
                    time.sleep(sleeptime)
                    count += sleeptime
                    sleeptime *= 2
                    continue
                else:
                    break
            else:
                logger.fatal("Unable to connect to host: %s", env.host_string)

        execute(ssh_is_opened_impl, hosts=host)

    class RebootDetector:
        server = None
        client_ip = None
        # This global one is used to increment each port used.
        port = 8181

        def __init__(self, client_ip=None):
            self.port = Helpers.RebootDetector.port
            Helpers.RebootDetector.port += 1
            self.client_ip = client_ip

        def __enter__(self):
            # The mender-reboot-detector service in the image will connect to the
            # port we list here and tell us about startups and shutdowns.
            ip = docker_get_docker_host_ip()

            def setup_client():
                local_name = "test.mender-reboot-detector.txt.%s" % env.host_string
                with open(local_name, "w") as fd:
                    fd.write("%s:%d" % (ip, self.port))
                try:
                    put(local_name, remote_path="/data/mender/test.mender-reboot-detector.txt")
                finally:
                    os.unlink(local_name)

                run("systemctl restart mender-reboot-detector")

            if env.host_string:
                setup_client()
            else:
                execute(setup_client, hosts=self.client_ip)

            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((ip, self.port))
            self.server.listen(1)

            return self

        def __exit__(self, type, value, trace):
            if self.server:
                self.server.close()
            self.server = None

            cmd = "systemctl stop mender-reboot-detector ; rm -f /data/mender/test.mender-reboot-detector.txt"
            try:
                if env.host_string:
                    run(cmd)
                else:
                    execute(run, cmd, hosts=self.client_ip)
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
                    connection, address = self.server.accept()
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
