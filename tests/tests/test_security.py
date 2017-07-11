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
import time
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

class TestSecurity(MenderTesting):

    @pytest.mark.usefixtures("standard_setup_without_client")
    def test_ssl_only(self):
        """ make sure we are not exposing any non-ssl connections"""

        # get all exposed ports from docker
        exposed_hosts = subprocess.check_output("docker ps | grep %s | grep -o -E '0.0.0.0:[0-9]*'" % (conftest.docker_compose_instance), shell=True)

        for host in exposed_hosts.split():
            with contextlib.closing(ssl.wrap_socket(socket.socket())) as sock:
                logging.info("%s: connect to host with TLS" % host)
                host, port = host.split(":")
                sock.connect((host, int(port)))
