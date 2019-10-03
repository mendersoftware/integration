import logging
import pytest
import subprocess
import time

import pymongo

from testutils.common import mongo, mongo_cleanup
from testutils.common import User, Device, Tenant, create_user, create_tenant, \
    create_tenant_user, create_org
from testutils import api
from testutils import infra

logger = logging.getLogger(__name__)

@pytest.yield_fixture(scope="function")
def clean_mongo_tenant_migration(mongo):
    mongo_cleanup(mongo)
    tenant_cli = infra.cli.CliTenantadm()
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
        self.logger.info("Starting `test_success`")

        out = create_org("fooCorp", "user@example.com", "pwd")
        self.logger.debug("tenant id: %s" % out)

        # Retry login for 3 min
        for i in range(60 * 3):
            time.sleep(1)
            rsp = self.api_mgmt_useradm.call("POST", api.useradm.URL_LOGIN,
                                             auth=("user@example.com", "pwd"))
            if rsp.status_code == 200:
                break
        assert rsp.status_code == 200

        self.logger.info("`test_success` finished successfully.")


    def test_duplicate_username(self, clean_mongo_tenant_migration):
        """
        Duplicate username (e-mail) should not be allowed, as this
        leads to conflicting login credentials.
        """
        err = None

        self.logger.debug("Starting `test_duplicate_username`")

        self.logger.debug("First tenant creation call")
        out = create_org("fooCorp", "user@example.com", "321password")
        self.logger.debug("stdout: %s" % out)

        # Retry login for 3 min
        for i in range(60 * 3):
            time.sleep(1)
            rsp = self.api_mgmt_useradm.call("POST", api.useradm.URL_LOGIN,
                                             auth=("user@example.com", "321password"))
            if rsp.status_code == 200:
                self.logger.debug("Successfully logged into account")
                break
        assert rsp.status_code == 200

        try:
            self.logger.debug("Second tenant creation call")
            out = create_org("barCorp", "user@example.com", "321password")
            self.logger.debug("stdout: %s" % out)
        except subprocess.CalledProcessError as e:
            err = e

        if err == None:
            pytest.fail("Duplicate user email is not allowed!")

        # Retry login for 3 min
        for i in range(60 * 3):
            time.sleep(1)
            rsp = self.api_mgmt_useradm.call("POST", api.useradm.URL_LOGIN,
                                             auth=("user@example.com", "321password"))
            if rsp.status_code == 200:
                break
        assert rsp.status_code == 200

        self.logger.info("`test_duplicate_username` finished successfully.")

    def test_duplicate_organization(self, clean_mongo_tenant_migration):
        """
        It should be allowed to create duplicate organizations as long
        as the user e-mails (login credentials) differ.
        """
        self.logger.debug("Starting `test_duplicate_username`")

        out = create_org("fooCorp",
                         "foo@corp.org",
                         "321password")

        # Retry login for 3 min
        for i in range(60 * 3):
            time.sleep(1)
            rsp = self.api_mgmt_useradm.call("POST", api.useradm.URL_LOGIN,
                                             auth=("foo@corp.org",
                                                   "321password"))
            if rsp.status_code == 200:
                self.logger.debug("Successfully logged into account")
                break
        assert rsp.status_code == 200

        out = create_org("fooCorp",
                         "foo@acme.com",
                         "password123")

        # Retry login for 3 min
        for i in range(60 * 3):
            time.sleep(1)
            rsp = self.api_mgmt_useradm.call("POST", api.useradm.URL_LOGIN,
                                             auth=("foo@acme.com",
                                                   "password123"))
            if rsp.status_code == 200:
                break
        assert rsp.status_code == 200

        self.logger.info("`test_duplicate_username` finished successfully.")
