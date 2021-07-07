# Copyright 2021 Northern.tech AS
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


import glob
import json
import logging
import os
import pytest
import requests
import subprocess
import tempfile
import yaml

from testutils.api.client import GATEWAY_HOSTNAME


logging.basicConfig(format="%(asctime)s %(message)s")
logger = logging.getLogger("test_decomission")
logger.setLevel(logging.INFO)


REPO_TO_ENV_VARIABLE = {
    "auditlogs": "AUDITLOGS_REV",
    "deployments": "DEPLOYMENTS_REV",
    "deployments-enterprise": "DEPLOYMENTS_ENTERPRISE_REV",
    "deviceauth": "DEVICEAUTH_REV",
    "deviceconfig": "DEVICECONFIG_REV",
    "deviceconnect": "DEVICECONNECT_REV",
    "inventory": "INVENTORY_REV",
    "inventory-enterprise": "INVENTORY_ENTERPRISE_REV",
    "tenantadm": "TENANTADM_REV",
    "useradm": "USERADM_REV",
    "useradm-enterprise": "USERADM_ENTERPRISE_REV",
    "workflows": "WORKFLOWS_REV",
    "workflows-enterprise": "WORKFLOWS_ENTERPRISE_REV",
}


def get_api_docs(repo):
    git_repository = f"git@github.com:mendersoftware/{repo}.git"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_repo = os.path.join(tmp, repo)
        subprocess.check_output(["git", "clone", git_repository, tmp_repo])
        env_var_name = REPO_TO_ENV_VARIABLE.get(repo)
        branch_name = env_var_name and os.getenv(env_var_name) or "master"
        branch_name != "master" and subprocess.check_output(
            ["git", "fetch", "origin", branch_name + ":prtest"], cwd=tmp_repo,
        )
        branch_name != "master" and subprocess.check_output(
            ["git", "checkout", "prtest"], cwd=tmp_repo,
        )
        files = glob.glob(os.path.join(tmp_repo, "docs", "*.yml"))
        for file in files:
            basename = os.path.basename(file)
            kind = (
                basename.startswith("management_")
                and "management"
                or basename.startswith("devices_")
                and "devices"
                or "internal"
            )
            with open(file) as f:
                data = yaml.load(f, Loader=yaml.FullLoader)
                yield kind, data


def get_api_endpoints(repo):
    for kind, data in get_api_docs(repo):
        if data.get("swagger"):
            scheme, host, base_path = (
                data["schemes"][0],
                data["host"],
                data.get("basePath", "/"),
            )
        elif data.get("openapi"):
            parts = data["servers"][0]["url"].split("/", 3)
            scheme = parts[0].rstrip(":")
            host, base_path = parts[2:4]
        else:
            logger.error(f"unknown specification file: {json.dumps(data)}")
            raise ValueError(
                "Unknown specification file, only swagger and openapi 3 are supported!"
            )
        for path, path_value in data["paths"].items():
            for method, definition in path_value.items():
                requires_auth = (
                    len(definition.get("security") or ()) > 0
                    or len(data.get("security") or ()) > 0
                    or path.rstrip("/").endswith("/verify")  # JWT token verifications
                    or path.rstrip("/").endswith("/2faqr")  # 2FA QR code
                    or path.rstrip("/").endswith("/2faverify")  # 2FA code verification
                )
                yield {
                    "auth": requires_auth,
                    "kind": kind,
                    "method": method,
                    "scheme": scheme,
                    "host": host,
                    "path": base_path.rstrip("/") + path,
                }


def get_all_api_endpoints(repos):
    for repo in repos:
        for endpoint in get_api_endpoints(repo):
            yield (
                endpoint["kind"],
                endpoint["auth"],
                endpoint["method"],
                endpoint["scheme"],
                endpoint["host"],
                endpoint["path"],
            )


class BaseTestAPIEndpoints:
    def do_test_api_endpoints(self, kind, auth, method, scheme, host, path):
        assert method in ("get", "post", "put", "delete", "patch")
        requests_method = getattr(requests, method)
        if host == "hosted.mender.io" or kind in ("management", "devices"):
            base_url = f"{scheme}://{GATEWAY_HOSTNAME}"
        else:
            base_url = f"{scheme}://{host}"
        r = requests_method(
            base_url + "/" + path.lstrip("/"), verify=False, timeout=2.0
        )
        if auth:
            assert 401 == int(r.status_code)
        else:
            assert 401 != int(r.status_code)
            assert (
                int(r.status_code) >= 200
                and int(r.status_code) < 500
                and int(r.status_code) != 405
            )


class TestAPIEndpoints(BaseTestAPIEndpoints):
    REPOS = (
        "deployments",
        "deviceauth",
        "deviceconfig",
        "deviceconnect",
        "inventory",
        "useradm",
        "workflows",
    )

    @pytest.mark.parametrize(
        "kind,auth,method,scheme,host,path", get_all_api_endpoints(REPOS),
    )
    def test_api_endpoints(self, kind, auth, method, scheme, host, path):
        self.do_test_api_endpoints(kind, auth, method, scheme, host, path)


class TestAPIEndpointsEnterprise(BaseTestAPIEndpoints):
    REPOS = (
        "auditlogs",
        "deployments-enterprise",
        "deviceauth",
        "deviceconfig",
        "deviceconnect",
        "inventory-enterprise",
        "tenantadm",
        "useradm-enterprise",
        "workflows-enterprise",
    )

    @pytest.mark.parametrize(
        "kind,auth,method,scheme,host,path", get_all_api_endpoints(REPOS),
    )
    def test_api_endpoints(self, kind, auth, method, scheme, host, path):
        self.do_test_api_endpoints(kind, auth, method, scheme, host, path)
