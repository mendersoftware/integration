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
import smtpd_mock
from threading import Thread
import asyncore
from MenderAPI import *

class TestCreateOrganization(MenderTesting):
    @pytest.mark.usefixtures("multitenancy_setup_without_client_with_smtp")
    def test_success(self):

        logging.info("Starting TestCreateOrganization")
        smtp_mock = SMTPMock()

        thread = Thread(target=smtp_mock.start)
        thread.daemon = True
        thread.start()

        logging.info("TestCreateOrganization: making request")

        payload = {"request_id": "123456", "organization": "tenant-foo", "email":"some.user@example.com", "password": "asdfqwer1234", "g-recaptcha-response": "foobar"}
        rsp = requests.post("https://%s/api/management/v1/tenantadm/tenants" % get_mender_gateway(), data=payload, verify=False)

        assert rsp.status_code == 202

        logging.info("TestCreateOrganization: workflow started. Waiting...")

        for i in range(60 * 5):
            if len(smtp_mock.server.messages) > 0:
                break
            time.sleep(1)

        logging.info("TestCreateOrganization: Waiting finished. Stoping mock")
        smtp_mock.stop()
        logging.info("TestCreateOrganization: Mock stopped.")
        smtp_mock.assert_called()
        logging.info("TestCreateOrganization: Assert ok.")

        r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (get_mender_gateway(), api_version),
                verify=False,
                auth=HTTPBasicAuth("some.user@example.com", "asdfqwer1234"))
        assert r.status_code == 200

    @pytest.mark.usefixtures("multitenancy_setup_without_client_with_smtp")
    def test_duplicate_organization_name(self):
        payload = {"request_id": "123456", "organization": "tenant-foo", "email":"some.user@example.com", "password": "asdfqwer1234", "g-recaptcha-response": "foobar"}
        rsp = requests.post("https://%s/api/management/v1/tenantadm/tenants" % get_mender_gateway(), data=payload, verify=False)
        assert rsp.status_code == 202
        payload = {"request_id": "123457", "organization": "tenant-foo", "email":"some.user2@example.com", "password": "asdfqwer1234", "g-recaptcha-response": "foobar"}
        rsp = requests.post("https://%s/api/management/v1/tenantadm/tenants" % get_mender_gateway(), data=payload, verify=False)
        assert rsp.status_code == 202

    @pytest.mark.usefixtures("multitenancy_setup_without_client_with_smtp")
    def test_duplicate_email(self):
        payload = {"request_id": "123456", "organization": "tenant-foo", "email":"some.user@example.com", "password": "asdfqwer1234", "g-recaptcha-response": "foobar"}
        rsp = requests.post("https://%s/api/management/v1/tenantadm/tenants" % get_mender_gateway(), data=payload, verify=False)
        logging.debug("first request to tenant adm returned: ", rsp.text)
        assert rsp.status_code == 202

        payload = {"request_id": "123457", "organization": "tenant-foo2", "email":"some.user@example.com", "password": "asdfqwer1234", "g-recaptcha-response": "foobar"}
        rsp = requests.post("https://%s/api/management/v1/tenantadm/tenants" % get_mender_gateway(), data=payload, verify=False)
        logging.debug("second request to tenant adm returned: ", rsp.text)
        assert rsp.status_code == 409


class SMTPMock:
    def start(self):
        self.server = smtpd_mock.SMTPServerMock(('0.0.0.0', 4444), None)
        asyncore.loop()

    def stop(self):
        self.server.close()

    def assert_called(self):
        assert len(self.server.messages) == 1
        m = self.server.messages[0]
        assert m.mailfrom == "contact@mender.io"
        assert m.rcpttos[0] == "some.user@example.com"

        logging.debug("message data: " + m.data)
        assert len(m.data) > 0

