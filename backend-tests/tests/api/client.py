# Copyright 2018 Northern.tech AS
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
import os.path

import requests

GATEWAY_URL='https://mender-api-gateway'

class ApiClient:
    def __init__(self, base_url=GATEWAY_URL):
        self.base_url = base_url

        # default content type should be ok for 99% of requests
        self.headers = {'Content-Type': 'application/json'}

    def with_auth(self, token):
        return self.with_header('Authorization', 'Bearer ' + token)

    def with_header(self, hdr, val):
        self.headers[hdr]=val
        return self

    def call(self, method, url, body=None, path_params={}, qs_params={}, headers={}, auth=None):
        url = self.__make_url(url)
        url = self.__subst_path_params(url, path_params)
        return requests.request(method, url, json=body, params=qs_params, headers=self.__make_headers(headers), auth=auth, verify=False)

    def __make_url(self, path):
        return os.path.join(self.base_url,
                            path if not path.startswith("/") else path[1:])
        pass

    def __subst_path_params(self, url, path_params):
        return url.format_map(path_params)

    def __make_headers(self, headers):
        return dict(self.headers, **headers)
