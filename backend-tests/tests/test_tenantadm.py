import logging
import pytest
import subprocess
import time

import pymongo

from testutils.common import mongo, mongo_cleanup
from testutils.common import User, Device
from testutils.infra import cli
from testutils import api

logger = logging.getLogger(__name__)


@pytest.yield_fixture(scope="function")
def clean_mongo_tenant_migration(mongo):
    mongo_cleanup(mongo)
    tenant_cli = cli.CliTenantadm()
    tenant_cli.migrate()
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

        tenant_id = tenantadm_cli.create_org(
            name="fooCorp", username="user@example.com", password="password"
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 3 min
        for i in range(60 * 3):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=("user@example.com", "password")
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
        err = None

        self.logger.debug("Starting `test_duplicate_username`")

        self.logger.debug("First tenant creation call")
        tenant_id = tenantadm_cli.create_org(
            name="fooCorp", username="user@example.com", password="321password"
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 3 min
        for i in range(60 * 3):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=("user@example.com", "321password")
            )
            if rsp.status_code == 200:
                self.logger.debug("Successfully logged into account")
                break
            time.sleep(1)
        assert rsp.status_code == 200

        try:
            self.logger.debug("Second tenant creation call")
            tenant_id = tenantadm_cli.create_org(
                name="barCorp", username="user@example.com", password="321password"
            )
            pytest.fail("Multiple users with the same username is not allowed")
        except subprocess.CalledProcessError as e:
            pass

        self.logger.info("`test_duplicate_username` finished successfully.")

    def test_duplicate_organization(self, clean_mongo_tenant_migration):
        """
        It should be allowed to create duplicate organizations as long
        as the user e-mails (login credentials) differ.
        """
        self.logger.debug("Starting `test_duplicate_username`")
        tenantadm_cli = cli.CliTenantadm()

        tenant_id = tenantadm_cli.create_org(
            name="fooCorp", username="foo@corp.org", password="321password"
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 3 min
        for i in range(60 * 3):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=("foo@corp.org", "321password")
            )
            if rsp.status_code == 200:
                self.logger.debug("Successfully logged into account")
                break
            time.sleep(1)

        assert rsp.status_code == 200

        tenant_id = tenantadm_cli.create_org(
            name="fooCorp", username="foo@acme.com", password="password123"
        )
        self.logger.debug("Tenant id: %s" % tenant_id)

        # Retry login every second for 3 min
        for i in range(60 * 3):
            rsp = self.api_mgmt_useradm.call(
                "POST", api.useradm.URL_LOGIN, auth=("foo@acme.com", "password123")
            )
            if rsp.status_code == 200:
                break
            time.sleep(1)
        assert rsp.status_code == 200

        self.logger.info("`test_duplicate_username` finished successfully.")
