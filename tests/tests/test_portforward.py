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

import os
import subprocess
import time

from multiprocessing import Process
from tempfile import NamedTemporaryFile

from DNS import DnsRequest

from ..common_setup import standard_setup_one_client_bootstrapped, enterprise_no_client
from .common_connect import prepare_env_for_connect
from ..MenderAPI import authentication, devauth, get_container_manager, logger
from .common_connect import wait_for_connect
from .common import md5sum
from .mendertesting import MenderTesting


class BaseTestPortForward(MenderTesting):
    """Tests the port forward functionality"""

    def do_test_portforward(self, env, auth, devid):
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

        # start the port forwarding session in a different thread
        def port_forward(server_url, dev_id, port_mapping, *port_mappings):
            p = subprocess.Popen(
                [
                    "mender-cli",
                    "--skip-verify",
                    "--server",
                    server_url,
                    "port-forward",
                    devid,
                    port_mapping,
                ]
                + list(port_mappings),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = p.communicate()
            p.wait()

        pfw = Process(
            target=port_forward,
            args=(server_url, devid, "9922:22", "udp/9953:8.8.8.8:53"),
        )
        pfw.start()

        # wait a few seconds to let the port-forward start
        logger.info("port-forward started, waiting a few seconds")
        time.sleep(10)

        # verify the UDP port-forward querying the Google's DNS server
        logger.info("resolve mender.io (A record)")
        req = DnsRequest(name="mender.io", qtype="A", server="localhost", port=9953)
        response = req.req()
        assert len(response.answers) >= 1, response.show()

        logger.info("resolve mender.io (MX record)")
        req = DnsRequest(name="mender.io", qtype="MX", server="localhost", port=9953)
        response = req.req()
        assert len(response.answers) >= 1, response.show()

        # verify the TCP port-forward using scp to upload and download files
        try:
            # create a 40MB random file
            f = NamedTemporaryFile(delete=False)
            for i in range(40 * 1024):
                f.write(os.urandom(1024))
            f.close()

            logger.info("created a 40MB random file: " + f.name)

            # upload the file using scp
            logger.info("uploading the file to the device using scp")
            p = subprocess.Popen(
                [
                    "scp",
                    "-O",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-P",
                    "9922",
                    f.name,
                    "root@localhost:/tmp/random.bin",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = p.communicate()
            exit_code = p.wait()
            assert exit_code == 0, (stdout, stderr)

            # download the file using scp
            logger.info("download the file from the device using scp")
            p = subprocess.Popen(
                [
                    "scp",
                    "-O",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-P",
                    "9922",
                    "root@localhost:/tmp/random.bin",
                    f.name + ".download",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = p.communicate()
            exit_code = p.wait()
            assert exit_code == 0, (stdout, stderr)

            # assert the files are not corrupted
            logger.info("checking the checksums of the uploaded and downloaded files")
            assert md5sum(f.name) == md5sum(f.name + ".download")
        finally:
            os.unlink(f.name)
            if os.path.isfile(f.name + ".download"):
                os.unlink(f.name + ".download")

        # stop the port-forwarding
        pfw.kill()


class TestPortForwardOpenSource(BaseTestPortForward):
    def test_portforward(self, standard_setup_one_client_bootstrapped):
        # list of devices
        devices = devauth.get_devices_status("accepted")
        assert 1 == len(devices)
        # device ID
        devid = devices[0]["id"]
        assert devid is not None
        #
        auth = authentication.Authentication()
        self.do_test_portforward(standard_setup_one_client_bootstrapped, auth, devid)


class TestPortForwardEnterprise(BaseTestPortForward):
    def test_portforward(self, enterprise_no_client):
        devid, _, auth, _ = prepare_env_for_connect(enterprise_no_client)
        self.do_test_portforward(enterprise_no_client, auth, devid)
