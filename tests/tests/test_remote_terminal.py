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
#

import os
import subprocess
import time

from tempfile import NamedTemporaryFile

from ..common_setup import standard_setup_one_client
from ..MenderAPI import authentication, devauth, get_container_manager, logger
from .common_connect import wait_for_connect
from .common import md5sum
from .mendertesting import MenderTesting


class TestRemoteTerminal(MenderTesting):
    """Tests the port forward functionality"""

    def test_remote_terminal(self, standard_setup_one_client):
        # accept the device
        devauth.accept_devices(1)

        # list of devices
        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        # wait for the device to connect via websocket
        auth = authentication.Authentication()
        wait_for_connect(auth, devices[0])

        # device ID and auth token
        devid = devices[0]
        assert devid is not None

        # authenticate with mender-cli
        server_url = "https://" + get_container_manager().get_mender_gateway()
        username = auth.username
        password = auth.password
        p = subprocess.Popen(
            [
                "mender-cli",
                "--skip-verify",
                "--server",
                server_url,
                "login",
                "--username",
                username,
                "--password",
                password,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = p.communicate()
        exit_code = p.wait()
        assert exit_code == 0, (stdout, stderr)

        # connect to the remote termianl using mender-cli
        logger.info("connect to the remote termianl using mender-cli")
        p = subprocess.Popen(
            ["mender-cli", "--skip-verify", "--server", server_url, "terminal", devid],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # wait a few seconds
        time.sleep(2)

        # run a command and evaluate the output
        logger.info("run a command and evaluate the output")
        stdout, stderr = p.communicate(input=b"ls /etc/mender/\nexit\n", timeout=30)
        exit_code = p.wait(timeout=30)

        assert exit_code == 0, (stdout, stderr)
        assert b"mender.conf" in stdout, (stdout, stderr)
