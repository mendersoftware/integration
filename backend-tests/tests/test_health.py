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

import pytest

from urllib import parse

from testutils.api import client


class TestHealthCheck:
    @pytest.mark.parametrize(
        "url",
        [
            "http://mender-deployments:8080/api/internal/v1/deployments/health",
            "http://mender-device-auth:8080/api/internal/v1/devauth/health",
            "http://mender-deviceconfig:8080/api/internal/v1/deviceconfig/health",
            "http://mender-deviceconnect:8080/api/internal/v1/deviceconnect/health",
            "http://mender-inventory:8080/api/internal/v1/inventory/health",
            "http://mender-iot-manager:8080/api/internal/v1/iot-manager/health",
            "http://mender-useradm:8080/api/internal/v1/useradm/health",
            "http://mender-workflows-server:8080/api/v1/health",
        ],
    )
    def test_health_check(self, url):
        parsed = parse.urlparse(url)
        api_client = client.ApiClient(
            base_url="",
            host=parsed.hostname + ":" + str(parsed.port),
            schema=parsed.scheme + "://",
        )
        rsp = api_client.call("GET", parsed.path)
        assert rsp.status_code == 204, rsp.text


class TestHealthCheckEnterprise:
    @pytest.mark.parametrize(
        "url",
        [
            "http://mender-auditlogs:8080/api/internal/v1/auditlogs/health",
            "http://mender-deployments:8080/api/internal/v1/deployments/health",
            "http://mender-device-auth:8080/api/internal/v1/devauth/health",
            "http://mender-deviceconfig:8080/api/internal/v1/deviceconfig/health",
            "http://mender-deviceconnect:8080/api/internal/v1/deviceconnect/health",
            "http://mender-devicemonitor:8080/api/internal/v1/devicemonitor/health",
            "http://mender-inventory:8080/api/internal/v1/inventory/health",
            "http://mender-iot-manager:8080/api/internal/v1/iot-manager/health",
            "http://mender-tenantadm:8080/api/internal/v1/tenantadm/health",
            "http://mender-useradm:8080/api/internal/v1/useradm/health",
            "http://mender-workflows-server:8080/api/v1/health",
        ],
    )
    def test_health_check(self, url):
        parsed = parse.urlparse(url)
        api_client = client.ApiClient(
            base_url="",
            host=parsed.hostname + ":" + str(parsed.port),
            schema=parsed.scheme + "://",
        )
        rsp = api_client.call("GET", parsed.path)
        assert rsp.status_code == 204, rsp.text
