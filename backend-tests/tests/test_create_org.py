# Copyright 2020 Northern.tech AS
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

import pytest
import time
import logging
import asyncore
from threading import Thread

from testutils.infra.smtpd_mock import SMTPServerMock

from testutils.common import mongo, clean_mongo
from testutils.api.client import ApiClient
import testutils.api.useradm as useradm
import testutils.api.tenantadm as tenantadm
from testutils.infra.cli import CliTenantadm


@pytest.yield_fixture(scope="function")
def clean_migrated_mongo(clean_mongo):
    tenantadm_cli = CliTenantadm()
    tenantadm_cli.migrate()
    yield clean_mongo


class TestCreateOrganizationEnterprise:
    def test_success(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT)
        uc = ApiClient(useradm.URL_MGMT)

        logging.info("Starting TestCreateOrganizationEnterprise")
        smtp_mock = SMTPMock()

        thread = Thread(target=smtp_mock.start)
        thread.daemon = True
        thread.start()

        payload = {
            "request_id": "123456",
            "organization": "tenant-foo",
            "email": "some.user@example.com",
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
        }
        r = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert r.status_code == 202

        for i in range(60 * 5):
            if len(smtp_mock.server.messages) > 0:
                break
            time.sleep(1)

        logging.info("TestCreateOrganizationEnterprise: Waiting finished. Stoping mock")
        smtp_mock.stop()
        logging.info("TestCreateOrganizationEnterprise: Mock stopped.")
        smtp_mock.assert_called()
        logging.info("TestCreateOrganizationEnterprise: Assert ok.")

        r = uc.call(
            "POST", useradm.URL_LOGIN, auth=("some.user@example.com", "asdfqwer1234")
        )
        assert r.status_code == 200

    def test_duplicate_organization_name(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT)
        payload = {
            "request_id": "123456",
            "organization": "tenant-foo",
            "email": "some.user@example.com",
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
        }
        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 202

        payload = {
            "request_id": "123457",
            "organization": "tenant-foo",
            "email": "some.user1@example.com",
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
        }
        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 202

    def test_duplicate_email(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT)
        payload = {
            "request_id": "123456",
            "organization": "tenant-foo",
            "email": "some.user@example.com",
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
        }
        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 202

        payload = {
            "request_id": "123457",
            "organization": "tenant-foo",
            "email": "some.user@example.com",
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
        }
        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 409


class SMTPMock:
    def start(self):
        self.server = SMTPServerMock(("0.0.0.0", 4444), None, enable_SMTPUTF8=True)
        asyncore.loop()

    def stop(self):
        self.server.close()

    def assert_called(self):
        assert len(self.server.messages) == 1
        m = self.server.messages[0]
        assert m.mailfrom == "contact@mender.io"
        assert m.rcpttos[0] == "some.user@example.com"

        assert len(m.data) > 0
