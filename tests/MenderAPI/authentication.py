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

from MenderAPI import *

class Authentication:
    auth_header = None

    username = "admin"
    email = "admin@admin.net"
    password = "averyverystrongpasswordthatyouwillneverguess!haha!"

    multitenancy = False
    current_tenant = {}

    def __init__(self, username=username, email=password, password=password):
        self.reset()
        self.username = username
        self.email = email
        self.password = password

    def reset(self):
        # Reset all temporary values.
        self.auth_header = Authentication.auth_header
        self.username = Authentication.username
        self.email = Authentication.email
        self.password = Authentication.password
        self.multitenancy = Authentication.multitenancy
        self.current_tenant = Authentication.current_tenant

    def set_tenant(self, username, email, password):
        self.new_tenant(username, email, password)

    def new_tenant(self, username, email, password):
        self.multitenancy = True
        self.reset_auth_token()
        self.username = username
        self.email = email
        self.password = password
        self.get_auth_token()

    def get_auth_token(self):
        if self.auth_header is not None:
            return self.auth_header

        # try login - the user might be in a shared db already (if not running xdist)
        r = self._do_login(self.email, self.password)

        # ...if not, create user
        if r.status_code is not 200:
            if self.multitenancy:
                tenant_id = self._create_tenant(self.username)
                tenant_id = tenant_id.strip()

                self._create_user(self.email, self.password, tenant_id)

                tenant_data = self._get_tenant_data(tenant_id)
                tenant_data_json = json.loads(tenant_data)

                self.current_tenant = {"tenant_id": tenant_id,
                                       "tenant_token": tenant_data_json["tenant_token"],
                                       "name": tenant_data_json["name"]}

            else:
                self._create_user(self.email, self.password)

            r = self._do_login(self.email, self.password)
            assert r.status_code == 200

        logging.info("Using Authorization headers: " + str(r.text))
        return self.auth_header

    def get_tenant_id(self):
        return self.current_tenant["tenant_id"]

    def reset_auth_token(self):
        self.auth_header = None

    def _do_login(self, username, password):
        r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (get_mender_gateway(), api_version), verify=False, auth=HTTPBasicAuth(username, password))
        assert r.status_code == 200 or r.status_code == 401

        if r.status_code == 200:
            self.auth_header = {"Authorization": "Bearer " + str(r.text)}
        return r

    def _create_user(self, username, password, tenant_id=""):
        if tenant_id != "":
            tenant_id = "--tenant-id " + tenant_id

        cmd = 'exec -T mender-useradm /usr/bin/useradm create-user --username %s --password %s %s' % (username,
                                                                                                      password, tenant_id)
        docker_compose_cmd(cmd)

    def _create_tenant(self, username):
        cmd = '-f ../docker-compose.tenant.yml %s exec -T mender-tenantadm /usr/bin/tenantadm create-tenant --name %s' % (conftest.mt_docker_compose_file,
                                                                                          username)
        return docker_compose_cmd(cmd)

    def _get_tenant_data(self, tenant_id):
        cmd = '-f ../docker-compose.tenant.yml %s exec -T mender-tenantadm /usr/bin/tenantadm get-tenant --id %s' % (conftest.mt_docker_compose_file,
                                                                                     tenant_id)
        return docker_compose_cmd(cmd)
