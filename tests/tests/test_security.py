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

from fabric.api import *
import pytest
from common import *
from common_docker import *
from common_setup import *
from helpers import Helpers
from MenderAPI import auth, adm, deploy, image, logger
from common_update import common_update_procedure
from mendertesting import MenderTesting
import subprocess
import sys
sys.path.insert(0, '..')
import conftest
import contextlib
import ssl
import socket
import time

class TestSecurity(MenderTesting):

    @pytest.mark.usefixtures("running_custom_production_setup")
    def test_ssl_only(self):
        """ make sure we are not exposing any non-ssl connections in production environment """
        done = False
        sleep_time = 2
        # start production environment
        subprocess.call(["./production_test_env.py", "--start",
                         "--docker-compose-instance", conftest.docker_compose_instance])

        try:

            # get all exposed ports from docker

            for _ in range(3):
                exposed_hosts = subprocess.check_output("docker ps | grep %s | grep -o -E '0.0.0.0:[0-9]*' | cat"
                                                        % conftest.docker_compose_instance,
                                                        shell=True)

                try:
                    for host in exposed_hosts.split():
                        with contextlib.closing(ssl.wrap_socket(socket.socket())) as sock:
                            logging.info("%s: connect to host with TLS" % host)
                            host, port = host.split(":")
                            sock.connect((host, int(port)))
                            done = True
                except:
                    sleep_time *= 2
                    time.sleep(sleep_time)
                    continue

                if done:
                    break

            if not done:
                pytest.fail("failed to connect to production env. using SSL")

        finally:
            # tear down production env
            subprocess.call(["./production_test_env.py", "--kill",
                             "--docker-compose-instance", conftest.docker_compose_instance])


    @pytest.mark.usefixtures("standard_setup_with_short_lived_token")
    def test_token_token_expiration(self):
        """ verify that an expired token is handled correctly (client gets a new, valid one)
            and that deployments are still recieved by the client
        """

        if not env.host_string:
            execute(self.test_token_token_expiration,
                    hosts=get_mender_clients())
            return

        timeout_time = int(time.time()) + 60
        while int(time.time()) < timeout_time:
            with quiet():
                output = run("journalctl -u mender -l --no-pager | grep \"received new authorization data\"")
                time.sleep(1)

            if output.return_code == 0:
                logging.info("mender logs indicate new authorization data available")
                break

        if timeout_time <= int(time.time()):
            pytest.fail("timed out waiting for download retries")


        # this call verifies that the deployment process goes into an "inprogress" state
        # which is only possible when the client has a valid token.
        common_update_procedure(install_image=conftest.get_valid_image())
