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
import os
import os.path
import socket
import socketserver
import warnings

import requests
import time

from urllib3.exceptions import InsecureRequestWarning

GATEWAY_HOSTNAME = os.environ.get("GATEWAY_HOSTNAME") or "mender-api-gateway"


def get_free_tcp_port() -> int:
    with socketserver.TCPServer(("localhost", 0), None) as s:
        return s.server_address[1]


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
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=InsecureRequestWarning)
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


def wait_for_port(port=8080, host="localhost", timeout=10.0):
    """Wait until a port starts accepting TCP connections.
    Args:
        port (int): Port number.
        host (str): Host address on which the port should exist.
        timeout (float): In seconds. How long to wait before raising errors.
    Raises:
        TimeoutError: The port isn't accepting connection after time specified in `timeout`.
    """
    start_time = time.perf_counter()
    while True:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                break
        except OSError as ex:
            time.sleep(0.50)
            if time.perf_counter() - start_time >= timeout:
                raise TimeoutError(
                    "Waited too long for the port {} on host {} to start accepting "
                    "connections.".format(port, host)
                ) from ex
