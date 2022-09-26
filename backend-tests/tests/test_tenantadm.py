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
import uuid

from redo import retrier

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
