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

        def get_header(t):
            return {"Authorization": "Bearer " + str(t)}

        r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (get_mender_gateway(), api_version), verify=False)
        self.auth_header = get_header(r.text)

        if r.status_code == 200:
            self.auth_header = get_header(r.text)
            r = requests.post("https://%s/api/management/%s/useradm/users/initial" % (get_mender_gateway(), api_version), headers=self.auth_header, verify=False, json={"email": email, "password": password})
            assert r.status_code == 201

        r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (get_mender_gateway(), api_version), verify=False, auth=HTTPBasicAuth(email, password))
        assert r.status_code == 200

        self.auth_header = get_header(r.text)
        logging.info("Using Authorization headers: " + str(r.text))
        return self.auth_header


    def reset_auth_token(self):
        self.auth_header = None
