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

import sys
import subprocess
import contextlib
import ssl
import socket
import time

from fabric.api import *
import pytest

from .. import conftest
from ..common import *
from ..common_setup import running_custom_production_setup, standard_setup_with_short_lived_token
from ..common_docker import get_mender_clients
from .common_update import common_update_procedure
from .mendertesting import MenderTesting

class TestSecurity(MenderTesting):

    @pytest.mark.timeout(678)
    @pytest.mark.usefixtures("running_custom_production_setup")
    def test_ssl_only(self):
        """ make sure we are not exposing any non-ssl connections in production environment """
        done = False
        sleep_time = 2
        # start production environment
        subprocess.call(["./production_test_env.py", "--start",
                         "--docker-compose-instance", conftest.docker_compose_instance])
        logging.info("test_ssl_only %s sleeping waiting for startup." % conftest.docker_compose_instance)
        time.sleep(8)
        try:

            # get all exposed ports from docker

            for _ in range(64):
                exposed_hosts = subprocess.check_output("docker ps | grep %s | grep -o -E '0.0.0.0:[0-9]*' | cat"
                                                        % conftest.docker_compose_instance,
                                                        shell=True)

                logging.info("test_ssl_only %s trying to connect to: %s." % (conftest.docker_compose_instance,exposed_hosts))
                try:
                    for host in exposed_hosts.split():
                        with contextlib.closing(ssl.wrap_socket(socket.socket())) as sock:
                            logging.info("test_ssl_only %s %s: connect to host with TLS" % (conftest.docker_compose_instance, host))
                            host, port = host.split(":")
                            sock.connect((host, int(port)))
                            done = True
                except:
                    sleep_time += 2
                    time.sleep(sleep_time)
                    logging.info("test_ssl_only %s next attempt" % conftest.docker_compose_instance)
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

        timeout_time = int(time.time()) + 512
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
