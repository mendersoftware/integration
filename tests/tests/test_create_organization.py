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
import requests
import fake_smtp

class TestCreateOrganization(MenderTesting):

    @pytest.mark.usefixtures("multitenancy_setup_without_client_with_smtp")
    def test_success(self):

        print("Starting TestCreateOrganization")
        smtp_mock = SMTPMock()
        smtp_mock.start()
        payload = {"request_id": "123456", "tenant_id":"123456", "organization": "tenant-foo", "email":"piotr.przybylak@gmail.com", "password": "asdfqwer1234"}
        requests.post("http://localhost:8080/api/workflow/create_organization", json=payload)
        print("TestCreateOrganization: workflow started. Waiting...")
        time.sleep( 15 )
        print("TestCreateOrganization: Waiting finished. Stoping mock")
        smtp_mock.stop()
        print("TestCreateOrganization: Mock stopped.")


class SMTPMock:
    def start(self):
        self.server = fake_smtp.FakeSMTPServer(('0.0.0.0', 4444), None)

    def stop(self):
        self.server.close()

    def assert_called(self):
        assert self.server.recieved == True
