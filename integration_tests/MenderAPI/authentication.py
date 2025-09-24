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

import json
import time
from requests.auth import HTTPBasicAuth

from . import logger
from . import api_version
from . import get_container_manager
from .requests_helpers import requests_retry

from integration_testutils.infra.cli import CliUseradm, CliTenantadm
from integration_testutils.infra.container_manager.kubernetes_manager import isK8S


class Authentication:
    auth_header = None

    org_name = "admin"
    username = "admin@admin.net"
    password = "averyverystrongpasswordthatyouwillneverguess!haha!"

    multitenancy = isK8S()
    if isK8S():
        plan = "enterprise"
    current_tenant = {}

    def __init__(self, name=org_name, username=username, password=password):
        """
        :param org_name: Name of tenant organization
        :param username: Username - must be an email
        :param password: Password associated with tenant user
        """
        self.reset()
        self.org_name = name
        self.org_create = True
        self.username = username
        self.password = password

    def reset(self):
        # Reset all temporary values.
        self.auth_header = Authentication.auth_header
        self.org_name = Authentication.org_name
        self.username = Authentication.username
        self.password = Authentication.password
        self.multitenancy = Authentication.multitenancy
        self.current_tenant = Authentication.current_tenant

    def set_tenant(self, org_name, username, password, plan="os"):
        self.new_tenant(org_name, username, password, plan)

    def new_tenant(self, org_name, username, password, plan="os"):
        self.multitenancy = True
        self.reset_auth_token()
        self.org_name = org_name
        self.org_create = True
        self.username = username
        self.password = password
        self.plan = plan
        self.get_auth_token()

    def get_auth_token(self, create_new_user=True):
        if self.auth_header is not None:
            return self.auth_header

        # try login - the user might be in a shared db
        #             already (if not running xdist)
        r = self._do_login(self.username, self.password)

        logger.info(
            "Getting authentication token for user %s@%s"
            % (self.username, self.org_name)
        )

        if create_new_user:
            if r.status_code != 200:
                if self.multitenancy and self.org_create:
                    tenant_id = self._create_org(
                        self.org_name, self.username, self.password, self.plan
                    )
                    tenant_id = tenant_id.strip()

                    tenant_data = self._get_tenant_data(tenant_id)
                    tenant_data_json = json.loads(tenant_data)

                    self.current_tenant = {
                        "tenant_id": tenant_id,
                        "tenant_token": tenant_data_json["tenant_token"],
                        "name": tenant_data_json["name"],
                    }
                    self.org_create = False

                else:
                    self.create_user(self.username, self.password)

            # It might take some time for create_org to propagate the new user.
            # Retry login for a minute.
            for _ in range(60):
                r = self._do_login(self.username, self.password)
                if r.status_code == 200:
                    break
                time.sleep(1)
            assert r.status_code == 200

        return self.auth_header

    def create_user(self, username, password, tenant_id=""):
        namespace = get_container_manager().name
        cli = CliUseradm(containers_namespace=namespace)
        cli.create_user(username, password, tenant_id)

    def get_tenant_id(self):
        return self.current_tenant["tenant_id"]

    def reset_auth_token(self):
        self.auth_header = None

    def _do_login(self, username, password):
        r = requests_retry().post(
            "https://%s/api/management/%s/useradm/auth/login"
            % (get_container_manager().get_mender_gateway(), api_version),
            verify=False,
            auth=HTTPBasicAuth(username, password),
        )
        assert r.status_code == 200 or r.status_code == 401

        if r.status_code == 200:
            self.auth_header = {"Authorization": "Bearer " + str(r.text)}
        logger.info("Using Authorization headers: " + str(r.text))
        return r

    def _create_org(self, name, username, password, plan="os"):
        namespace = get_container_manager().name
        cli = CliTenantadm(containers_namespace=namespace)
        tenant_id = cli.create_org(name, username, password, plan)
        return tenant_id

    def _get_tenant_data(self, tenant_id):
        namespace = get_container_manager().name
        cli = CliTenantadm(containers_namespace=namespace)
        tenant = cli.get_tenant(tenant_id)
        return tenant
