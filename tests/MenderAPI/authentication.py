#!/usr/bin/python
# Copyright 2016 Mender Software AS
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

import requests
import logging

from common_docker import *
from MenderAPI import api_version


class Authentication:
    auth_header = None

    def get_auth_token(self):
        if self.auth_header is not None:
            return self.auth_header

        email = "admin@admin.net"
        password = "averyverystrongpasswordthatyouwillneverguess!haha!"

        # try login - the user might be in a shared db already (if not running xdist)
        r = self._do_login(email, password)

        # ...if not, create user
        if r.status_code is not 200:
            self._create_user(email, password)

            r = self._do_login(email, password)
            assert r.status_code == 200

        logging.info("Using Authorization headers: " + str(r.text))
        return self.auth_header

    def reset_auth_token(self):
        self.auth_header = None

    def _do_login(self, username, password):
        r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (get_mender_gateway(), api_version), verify=False, auth=HTTPBasicAuth(username, password))
        assert r.status_code == 200 or r.status_code == 401

        if r.status_code == 200:
            self.auth_header = {"Authorization": "Bearer " + str(r.text)}

        return r

    def _create_user(self, username, password):
        cmd = 'exec mender-useradm /usr/bin/useradm create-user --username %s --password %s' % (username, password)

        docker_compose_cmd(cmd)
