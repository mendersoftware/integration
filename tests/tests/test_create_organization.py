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
from mendertesting import MenderTesting
import sys
sys.path.insert(0, '..')
import time
import requests
import fake_smtp
from threading import Thread
import asyncore
from MenderAPI import *

class TestCreateOrganization(MenderTesting):

    @pytest.mark.usefixtures("multitenancy_setup_without_client_with_smtp")
    def test_success(self):

        print("Starting TestCreateOrganization")
        smtp_mock = SMTPMock()

        thread = Thread(target=smtp_mock.start)
        thread.daemon = True
        thread.start()

        print("TestCreateOrganization: making request")

        payload = {"request_id": "123456", "tenant_id":"123456", "organization": "tenant-foo", "email":"piotr.przybylak@gmail.com", "password": "asdfqwer1234", "g-recaptcha-response": "foobar"}
        rsp = requests.post("https://%s/api/management/v1/tenantadm/tenants" % get_mender_gateway(), data=payload, verify=False)

        print("TestCreateOrganization: workflow started. Waiting...")
        for i in range(100):
            print("waiting: ", i)
            if smtp_mock.server.recieved == True:
                break
            time.sleep(0.5)
        print("TestCreateOrganization: Waiting finished. Stoping mock")
        smtp_mock.stop()
        print("TestCreateOrganization: Mock stopped.")
        smtp_mock.assert_called()
        print("TestCreateOrganization: Assert ok.")


class SMTPMock:
    def start(self):
        self.server = fake_smtp.FakeSMTPServer(('0.0.0.0', 4444), None)
        asyncore.loop()

    def stop(self):
        self.server.close()

    def assert_called(self):
        assert self.server.recieved == True
