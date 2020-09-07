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
import os
import os.path
import subprocess

import requests
import time

from testutils.infra.container_manager.kubernetes_manager import isK8S

GATEWAY_HOSTNAME = os.environ.get("GATEWAY_HOSTNAME") or "mender-api-gateway"


class ApiClient:
    def __init__(self, base_url="", host=GATEWAY_HOSTNAME, schema="https://"):
        self.host = host
        self.schema = schema
        self.base_url = schema + host + base_url
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
        try:
            p = None
            if isK8S() and url.startswith("http://mender-"):
                host = self.host.split(":", 1)[0]
                port = self.host.split(":", 1)[1] if ":" in self.host else "80"
                cmd = ["kubectl", "port-forward", "service/" + host, "8080:%s" % port]
                p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL)
                url = "http://localhost:8080/" + url.split("/", 3)[-1]
                # wait a few seconds to let the port-forwarding fully initialize
                time.sleep(3)
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
        finally:
            if p is not None:
                p.terminate()

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
