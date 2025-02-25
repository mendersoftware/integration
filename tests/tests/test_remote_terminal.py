# Copyright 2022 Northern.tech AS
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

import subprocess
import time

from ..common_setup import standard_setup_one_client_bootstrapped, enterprise_no_client
from .common_connect import prepare_env_for_connect
from ..MenderAPI import authentication, devauth, get_container_manager, logger
from .common_connect import wait_for_connect
from .mendertesting import MenderTesting

from flaky import flaky


class BaseTestRemoteTerminal(MenderTesting):
    """Tests the remote terminal functionality"""

    def do_test_remote_terminal(self, env, auth, devid):
        # wait for the device to connect via websocket
        wait_for_connect(auth, devid)

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


class TestRemoteTerminalOpenSource(BaseTestRemoteTerminal):
    def test_portforward(self, standard_setup_one_client_bootstrapped):
        # list of devices
        devices = devauth.get_devices_status("accepted")
        assert 1 == len(devices)
        # device ID
        devid = devices[0]["id"]
        assert devid is not None
        #
        auth = authentication.Authentication()
        self.do_test_remote_terminal(
            standard_setup_one_client_bootstrapped, auth, devid
        )


class TestRemoteTerminalEnterprise(BaseTestRemoteTerminal):
    def test_portforward(self, enterprise_no_client):
        devid, _, auth, _ = prepare_env_for_connect(enterprise_no_client)
        self.do_test_remote_terminal(enterprise_no_client, auth, devid)
