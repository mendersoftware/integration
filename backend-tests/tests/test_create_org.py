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

import pytest
import time
import logging
import uuid

from urllib import parse

from testutils.common import mongo, clean_mongo
from testutils.api.client import ApiClient
import testutils.api.useradm as useradm
import testutils.api.tenantadm as tenantadm
import testutils.api.deviceauth as deviceauth_v1
import testutils.integration.stripe as stripeutils
from testutils.infra.cli import CliTenantadm, CliUseradm


@pytest.fixture(scope="function")
def clean_migrated_mongo(clean_mongo):
    useradm_cli = CliUseradm()
    useradm_cli.migrate()

    tenantadm_cli = CliTenantadm()
    tenantadm_cli.migrate()
    yield clean_mongo


class TestCreateOrganizationEnterprise:
    def _cleanup_stripe(self, tenant_email):
        cust = stripeutils.customer_for_tenant(tenant_email)
        stripeutils.delete_cust(cust["id"])

    def test_success(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT, host=tenantadm.HOST, schema="http://")
        uc = ApiClient(useradm.URL_MGMT)
        tenantadmi = ApiClient(
            tenantadm.URL_INTERNAL, host=tenantadm.HOST, schema="http://"
        )
        devauthi = ApiClient(
            deviceauth_v1.URL_INTERNAL, host=deviceauth_v1.HOST, schema="http://"
        )

        logging.info("Starting TestCreateOrganizationEnterprise")

        uuidv4 = str(uuid.uuid4())
        tenant = "test.mender.io-" + uuidv4
        email = "some.user@{}.com".format(tenant)

        payload = {
            "request_id": "123456",
            "organization": tenant,
            "email": email,
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
            "token": "tok_visa",
        }
        r = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert r.status_code == 202

        # Try log in every second for 3 minutes.
        # - There usually is a slight delay (in order of ms) for propagating
        #   the created user to the db.
        for i in range(3 * 60):
            rsp = uc.call("POST", useradm.URL_LOGIN, auth=(email, "asdfqwer1234"),)
            if rsp.status_code == 200:
                break
            time.sleep(1)

        if rsp.status_code != 200:
            raise ValueError(
                "User could not log in within three minutes after organization has been created."
            )

        # get the tenant id (and verify that only one tenant exists)
        qs = parse.urlencode({"q": tenant})
        r = tenantadmi.call("GET", tenantadm.URL_INTERNAL_TENANTS + "?" + qs)
        assert r.status_code == 200
        api_tenants = r.json()
        assert len(api_tenants) == 1

        # verify the device limit via internal api
        # the default plan is "os" so the device limit should be set to 50
        r = devauthi.call(
            "GET",
            deviceauth_v1.URL_INTERNAL_LIMITS_MAX_DEVICES,
            path_params={"tid": api_tenants[0]["id"]},
        )
        assert r.status_code == 200
        assert r.json()["limit"] == 50

        # verify there is a stripe customer with a correctly assigned source
        cust = stripeutils.customer_for_tenant(email)
        assert cust.default_source is not None
        assert len(cust.sources) == 1

        self._cleanup_stripe(email)

    def test_success_with_plan(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT, host=tenantadm.HOST, schema="http://")
        uc = ApiClient(useradm.URL_MGMT)
        tenantadmi = ApiClient(
            tenantadm.URL_INTERNAL, host=tenantadm.HOST, schema="http://"
        )
        devauthi = ApiClient(
            deviceauth_v1.URL_INTERNAL, host=deviceauth_v1.HOST, schema="http://"
        )

        logging.info("Starting TestCreateOrganizationEnterprise")

        uuidv4 = str(uuid.uuid4())
        tenant = "test.mender.io-" + uuidv4
        email = "some.user@{}.com".format(tenant)

        payload = {
            "request_id": "123456",
            "organization": tenant,
            "email": email,
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
            "plan": "professional",
            "token": "tok_visa",
        }
        r = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert r.status_code == 202

        # Try log in every second for 5 minutes.
        # Creating organization is an async job
        # and may take some time to complete.
        for i in range(5 * 60):
            rsp = uc.call("POST", useradm.URL_LOGIN, auth=(email, "asdfqwer1234"),)
            if rsp.status_code == 200:
                break
            time.sleep(1)

        if rsp.status_code != 200:
            raise ValueError(
                "User could not log in within five minutes after organization has been created."
            )

        # get the tenant id (and verify that only one tenant exists)
        qs = parse.urlencode({"q": tenant})
        r = tenantadmi.call("GET", tenantadm.URL_INTERNAL_TENANTS + "?" + qs)
        assert r.status_code == 200
        api_tenants = r.json()
        assert len(api_tenants) == 1

        # verify the device limit via internal api
        # the device limit for professional plan should be 250
        r = devauthi.call(
            "GET",
            deviceauth_v1.URL_INTERNAL_LIMITS_MAX_DEVICES,
            path_params={"tid": api_tenants[0]["id"]},
        )
        assert r.status_code == 200
        assert r.json()["limit"] == 250

        self._cleanup_stripe(email)

    def test_duplicate_organization_name(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT, host=tenantadm.HOST, schema="http://")

        uuidv4 = str(uuid.uuid4())
        tenant = "test.mender.io-" + uuidv4
        email = f"some.user@{tenant}.com"

        payload = {
            "request_id": "123456",
            "organization": tenant,
            "email": email,
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
            "token": "tok_visa",
        }
        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 202

        email2 = f"some.user1@{tenant}.com"
        payload = {
            "request_id": "123457",
            "organization": tenant,
            "email": email2,
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
            "token": "tok_visa",
        }

        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 202

        self._cleanup_stripe(email)
        self._cleanup_stripe(email2)

    def test_duplicate_email(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT, host=tenantadm.HOST, schema="http://")

        uuidv4 = str(uuid.uuid4())
        tenant = "test.mender.io-" + uuidv4
        email = "some.user@{}.com".format(tenant)

        payload = {
            "request_id": "123456",
            "organization": tenant,
            "email": email,
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
            "token": "tok_visa",
        }
        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 202

        uuidv4 = str(uuid.uuid4())
        tenant = "test.mender.io-" + uuidv4

        payload = {
            "request_id": "123457",
            "organization": tenant,
            "email": email,
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
            "token": "tok_visa",
        }

        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 409

        self._cleanup_stripe(email)

    def test_plan_invalid(self, clean_migrated_mongo):
        tc = ApiClient(tenantadm.URL_MGMT, host=tenantadm.HOST, schema="http://")
        payload = {
            "request_id": "123456",
            "organization": "tenant-foo",
            "email": "some.user@example.com",
            "password": "asdfqwer1234",
            "g-recaptcha-response": "foobar",
            "plan": "foo",
            "token": "tok_visa",
        }
        rsp = tc.post(tenantadm.URL_MGMT_TENANTS, data=payload)
        assert rsp.status_code == 400
