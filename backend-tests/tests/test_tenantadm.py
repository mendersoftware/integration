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
import logging
import pytest
import subprocess
import time
import json
import uuid

from redo import retrier

import testutils.api.tenantadm_v2 as tenantadm_v2
import testutils.api.tenantadm as tenantadm_v1
import testutils.api.useradm as useradm

from testutils.api.client import ApiClient
from testutils.infra import cli
from testutils import api
from testutils.common import (
    mongo,
    mongo_cleanup,
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def clean_mongo_tenant_migration(mongo):
    mongo_cleanup(mongo)
    useradm_cli = cli.CliUseradm()
    useradm_cli.migrate()
    tenantadm_cli = cli.CliTenantadm()
    tenantadm_cli.migrate()
    yield mongo
    mongo_cleanup(mongo)


class TestCreateOrganizationCLIEnterprise:
    api_mgmt_useradm = api.client.ApiClient(api.useradm.URL_MGMT)
    logger = logger.getChild("TestCreateOrganizationCLIEnterprise")

    def test_success(self, clean_mongo_tenant_migration):
        """
        Create a single organization and verify that the created user
        is able to log in.
        """
        tenantadm_cli = cli.CliTenantadm()
        self.logger.info("Starting `test_success`")

        uuidv4 = str(uuid.uuid4())
        name, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant_id = tenantadm_cli.create_org(
            name=name, username=username, password=password
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 3 min
        for i in range(60 * 3):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=(username, password)
            )
            if rsp.status_code == 200:
                break
            time.sleep(1)

        assert rsp.status_code == 200

        self.logger.info("`test_success` finished successfully.")

    def test_duplicate_username(self, clean_mongo_tenant_migration):
        """
        Duplicate username (e-mail) should not be allowed, as this
        leads to conflicting login credentials.
        """
        tenantadm_cli = cli.CliTenantadm()
        self.logger.debug("Starting `test_duplicate_username`")

        self.logger.debug("First tenant creation call")
        uuidv4 = str(uuid.uuid4())
        name, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant_id = tenantadm_cli.create_org(
            name=name, username=username, password=password
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 2 min
        for i in range(60 * 2):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=(username, password)
            )
            if rsp.status_code == 200:
                self.logger.debug("Successfully logged into account")
                break
            time.sleep(1)
        assert rsp.status_code == 200

        try:
            self.logger.debug("Second tenant creation call")
            tenantadm_cli.create_org(
                name=name, username=username, password="321password"
            )
            pytest.fail("Multiple users with the same username is not allowed")
        except subprocess.CalledProcessError:
            pass

        self.logger.info("`test_duplicate_username` finished successfully.")

    def test_duplicate_organization(self, clean_mongo_tenant_migration):
        """
        It should be allowed to create duplicate organizations as long
        as the user e-mails (login credentials) differ.
        """
        self.logger.debug("Starting `test_duplicate_username`")
        tenantadm_cli = cli.CliTenantadm()

        uuidv4 = str(uuid.uuid4())
        name, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant_id = tenantadm_cli.create_org(
            name=name, username=username, password=password
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 2 min
        for _ in retrier(attempts=120, sleepscale=1, sleeptime=1):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=(username, password)
            )
            if rsp.status_code == 200:
                self.logger.debug("Successfully logged into account")
                break

        assert rsp.status_code == 200

        name, username, password = (
            "test.mender.io-" + uuidv4,
            "some.other.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant_id = tenantadm_cli.create_org(
            name=name, username=username, password=password
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 2 min
        for _ in retrier(attempts=120, sleepscale=1, sleeptime=1):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=(username, password)
            )
            if rsp.status_code == 200:
                break
        assert rsp.status_code == 200

        self.logger.info("`test_duplicate_username` finished successfully.")


class TestDeleteTenantsEnterprise:
    def create_trial_tenant(self):
        client_v2 = ApiClient(tenantadm_v2.URL_MGMT)
        client_v1 = ApiClient(tenantadm_v1.URL_MGMT)
        client_useradm = ApiClient(useradm.URL_MGMT)
        username = f"user+trial-{uuid.uuid4().hex}@mender.io"
        password = "correcthorsebatterystaple"
        req = {
            "organization": "Trailer corp",
            "email": username,
            "password": password,
            "name": "Trailer corp",
            "g-recaptcha-response": "test",
        }
        res = client_v2.call("POST", tenantadm_v2.URL_CREATE_ORG_TRIAL, body=req)
        assert (
            res.status_code == 202
        ), f"Error submitting signup request: unexpected status code {res.status_code}"

        authz = ""
        for _ in range(30):
            r = client_useradm.call(
                "POST", useradm.URL_LOGIN, auth=(username, password)
            )
            if r.status_code == 200:
                authz = r.text
                break
            time.sleep(1)
        else:
            raise TimeoutError("Timeout trying to log in after creating trial tenant")

        rsp = client_v1.with_auth(authz).call("GET", tenantadm_v1.URL_MGMT_THIS_TENANT)
        assert rsp.status_code == 200, "Error fetching tenant info"

        return {
            "id": rsp.json()["id"],
            "username": username,
            "password": password,
            "authorization": authz,
            "trial": True,
        }

    def create_tenant(self, plan: str = "enterprise"):
        client_useradm = ApiClient(useradm.URL_MGMT)
        cli_tenantadm = cli.CliTenantadm()
        username = f"user+{uuid.uuid4().hex}@mender.io"
        password = "correcthorsebatterystaple"
        tenant_id = cli_tenantadm(
            "create-org",
            "--name",
            "Integration Mc. Test Face",
            "--username",
            username,
            "--password",
            password,
        )

        r = client_useradm.call("POST", useradm.URL_LOGIN, auth=(username, password))
        assert (
            r.status_code == 200
        ), f"Unexpected status code ({r.status_code}) logging in"
        authz = r.text

        return {
            "id": tenant_id,
            "username": username,
            "password": password,
            "authorization": authz,
        }

    def test_delete_tenants(self, mongo, clean_mongo_tenant_migration):
        client_tenantadm = ApiClient(tenantadm_v2.URL_MGMT)
        cli_tenantadm = cli.CliTenantadm()

        tenants = [
            self.create_tenant("enterprise"),
            self.create_tenant("enterprise"),
            self.create_tenant("professional"),
            self.create_tenant("os"),
            self.create_trial_tenant(),
        ]

        # Cancel all tenants but the first one
        for tenant in tenants[1:]:
            tenant_id, authz = tenant["id"], tenant["authorization"]
            rsp = client_tenantadm.call(
                "POST",
                f"/tenants/{tenant_id}/cancel",
                headers={"Authorization": f"Bearer {authz}"},
                body={"reason": "just doing some testing..."},
            )
            assert (
                rsp.status_code < 300
            ), f"Unexpected status code ({rsp.status_code}) cancelling tenant"
            if "trial" not in tenant:
                # NOTE: cancel tenant does not suspend the tenant if not trial (why?)
                mongo.client.tenantadm.tenants.update_one(
                    {"_id": tenant_id}, {"$set": {"status": "suspended"}}
                )

            tenant = json.loads(cli_tenantadm("get-tenant", "--id", tenant_id))
            assert tenant["status"] == "suspended"

        # First delete suspended trial accounts
        #   Should only remove the last tenant in the list
        cli_tenantadm(
            "maintenance",
            "delete-suspended-tenants",
            "--threshold-days=0",
            "--only-trial",
        )

        # The tenant removal is processed asynchronously: poll tenantadm for 30s
        actual = []
        for _ in range(30):
            time.sleep(1)
            actual = json.loads(cli_tenantadm("list-tenants"))
            if len(actual) < len(tenants):
                break
        else:
            pytest.fail("Tenant was not removed within 30s as expected")

        expected_ids = sorted([tenant["id"] for tenant in tenants[:-1]])
        actual_ids = sorted([tenant["id"] for tenant in actual])
        assert expected_ids == actual_ids, "Command did not delete the expected tenants"

        # Remove all suspended tenants this time
        cli_tenantadm(
            "maintenance", "delete-suspended-tenants", "--threshold-days=0",
        )

        # The tenant removal is processed asynchronously: poll tenantadm for 30s
        for _ in range(30):
            time.sleep(1)
            actual = json.loads(cli_tenantadm("list-tenants"))
            if len(actual) <= 1:
                break
        else:
            pytest.fail("Tenant was not removed within 30s as expected")
        # Only the first tenant in the list remains
        expected_ids = sorted([tenant["id"] for tenant in tenants[:1]])
        actual_ids = sorted([tenant["id"] for tenant in actual])
        assert expected_ids == actual_ids, "Command did not delete the expected tenants"
