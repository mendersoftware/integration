#!/usr/bin/python
# Copyright 2019 Northern.tech AS
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

import json
import os
import time
from requests.auth import HTTPBasicAuth

from . import logger
from . import api_version
from .requests_helpers import requests_retry
from ..common_docker import get_mender_gateway

from ..conftest import docker_compose_instance
from testutils.infra.cli import CliUseradm, CliTenantadm

class Authentication:
    auth_header = None

    org_name = "admin"
    username = "admin@admin.net"
    password = "averyverystrongpasswordthatyouwillneverguess!haha!"

    multitenancy = False
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

    def set_tenant(self, org_name, username, password):
        self.new_tenant(org_name, username, password)

    def new_tenant(self, org_name, username, password):
        self.multitenancy = True
        self.reset_auth_token()
        self.org_name = org_name
        self.org_create = True
        self.username = username
        self.password = password
        self.get_auth_token()

    def get_auth_token(self, create_new_user=True):
        if self.auth_header is not None:
            return self.auth_header

        # try login - the user might be in a shared db
        #             already (if not running xdist)
        r = self._do_login(self.username, self.password)

        logger.info("Getting authentication token for user %s@%s"
                    % (self.username, self.org_name))

        if create_new_user:
            if r.status_code is not 200:
                if self.multitenancy and self.org_create:
                    tenant_id = self._create_org(self.org_name,
                                                 self.username,
                                                 self.password)
                    tenant_id = tenant_id.strip()

                    tenant_data = self._get_tenant_data(tenant_id)
                    tenant_data_json = json.loads(tenant_data)

                    self.current_tenant = {
                        "tenant_id":    tenant_id,
                        "tenant_token": tenant_data_json["tenant_token"],
                        "name":         tenant_data_json["name"]
                    }
                    self.org_create = False

                else:
                    self.create_user(self.username, self.password)

            # It might take some time for create_org to propagate the new user.
            # Retry login for a minute.
            for i in range(60):
                r = self._do_login(self.username, self.password)
                if r.status_code == 200:
                    break
                time.sleep(1)
            assert r.status_code == 200

        logger.info("Using Authorization headers: " + str(r.text))
        return self.auth_header

    def create_user(self, username, password, tenant_id=""):
        cli = CliUseradm(containers_namespace=docker_compose_instance)
        uid = cli.create_user(username, password, tenant_id)

    def get_tenant_id(self):
        return self.current_tenant["tenant_id"]

    def reset_auth_token(self):
        self.auth_header = None

    def _do_login(self, username, password):
        r = requests_retry().post(
            "https://%s/api/management/%s/useradm/auth/login" %
            (get_mender_gateway(), api_version),
            verify=False,
            auth=HTTPBasicAuth(username, password))
        assert r.status_code == 200 or r.status_code == 401

        if r.status_code == 200:
            self.auth_header = {"Authorization": "Bearer " + str(r.text)}
        return r

    def _create_org(self, name, username, password):
        cli = CliTenantadm(containers_namespace=docker_compose_instance)
        tenant_id = cli.create_org(name, username, password)
        return tenant_id

    def _get_tenant_data(self, tenant_id):
        cli = CliTenantadm(containers_namespace=docker_compose_instance)
        tenant = cli.get_tenant(tenant_id)
        return tenant
