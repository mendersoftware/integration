# Copyright 2020 Northern.tech AS
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

GATEWAY_HOSTNAME = "mender-api-gateway"


class ApiClient:
    def __init__(self, base_url="", host=GATEWAY_HOSTNAME, scheme="https://"):
        self.base_url = scheme + host + base_url
        self.headers = {}

    def with_auth(self, token):
        return self.with_header("Authorization", "Bearer " + token)

    def with_header(self, hdr, val):
        self.headers[hdr] = val
        return self

    def call(
        self,
        method,
        url,
        body=None,
        data=None,
        path_params={},
        qs_params={},
        headers={},
        auth=None,
        files=None,
    ):
        url = self.__make_url(url)
        url = self.__subst_path_params(url, path_params)
        return requests.request(
            method,
            url,
            json=body,
            data=data,
            params=qs_params,
            headers=self.__make_headers(headers),
            auth=auth,
            verify=False,
            files=files,
        )

    def post(self, url, *pargs, **kwargs):
        return self.call("POST", url, *pargs, **kwargs)

    def __make_url(self, path):
        return os.path.join(
            self.base_url, path if not path.startswith("/") else path[1:]
        )

    def __subst_path_params(self, url, path_params):
        return url.format(**path_params)

    def __make_headers(self, headers):
        return dict(self.headers, **headers)
