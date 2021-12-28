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

from typing import Optional
import pytest
import logging
import os
import re
import ssl
import uuid
from base64 import b64decode
from typing import Dict
from unittest.mock import Mock, MagicMock, PropertyMock


import trustme
from azure.iot.hub import IoTHubRegistryManager
from pytest_httpserver import HTTPServer, httpserver
from redo import retrier, retriable
from requests.models import Response

from testutils.api import (
    deviceauth,
    deviceconfig,
    iot_manager as iot,
    useradm,
)
from testutils.api.client import ApiClient
from testutils.common import (
    Device,
    User,
    create_org,
    create_user,
    create_user_test_setup,
    create_tenant_test_setup,
    clean_mongo,
    make_accepted_device,
    mongo,
)


HTTPServer.DEFAULT_LISTEN_PORT = 8888
HTTPServer.DEFAULT_LISTEN_HOST = (
    "mender-backend-tests-runner"  # name of the compose service
)


@pytest.fixture(scope="session")
def ca():
    return trustme.CA()


@pytest.fixture(scope="session")
def localhost_cert(ca):
    return ca.issue_cert(HTTPServer.DEFAULT_LISTEN_HOST)


@pytest.fixture(scope="session")
def httpserver_ssl_context(localhost_cert) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    crt = localhost_cert.cert_chain_pems[0]
    key = localhost_cert.private_key_pem
    with crt.tempfile() as crt_file, key.tempfile() as key_file:
        context.load_cert_chain(crt_file, key_file)

    return context


class _TestAzureBase:
    azure_api = ApiClient(base_url=iot.URL_MGMT, host=iot.HOST, schema="http://")

    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    def save_settings(self, user: User, settings: Dict) -> Response:
        response = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("PUT", iot.URL_SETTINGS, settings)
        )
        return response

    def get_settings(self, user: User) -> Response:
        response = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("GET", iot.URL_SETTINGS)
        )
        return response

    def check_settings(self, user: User):
        """Make sure iot-manager properly saves connection strings in its database."""
        for expected_settings in [
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=OldKey"
            },
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=NewKey"
            },
        ]:
            response = self.save_settings(user, expected_settings)
            assert response.status_code == 204
            self.logger.info("saved settings")

            self.logger.info("getting settings")
            response = self.get_settings(user)
            assert response.status_code == 200
            self.logger.info(f"got settings: {response.text}")
            assert "connection_string" in response.json().keys()
            actual = response.json()["connection_string"]
            # Check for equality by parts:
            # Check that actual properties are a subset of expected settings
            for part in actual.split(";"):
                assert part in expected_settings["connection_string"]
            # Check that expected properties are a subset of actual settings
            for part in expected_settings["connection_string"].split(";"):
                assert part in actual


class TestAzureSettings(_TestAzureBase):
    def test_get_and_set(self, clean_mongo):
        """
        Check that we can set and get settings
        """
        self.logger.info("creating user in OS mode")
        user = create_user_test_setup()
        self.check_settings(user)


class TestAzureSettingsEnterprise(_TestAzureBase):
    def test_get_and_set(self, clean_mongo):
        """
        Check that we can set and get settings
        """
        self.logger.info("creating tenant and user in enterprise mode")
        tenant = create_tenant_test_setup()
        user = tenant.users[0]
        self.check_settings(user)


def get_connection_string():
    """Determine whether AZURE_IOTHUB_CONNECTIONSTRING or AZURE_IOTHUB_CONNECTIONSTRING_B64
    environment variable is set.
    """
    connection_string = os.environ.get("AZURE_IOTHUB_CONNECTIONSTRING")
    if connection_string is None:
        cs_b64 = os.environ.get("AZURE_IOTHUB_CONNECTIONSTRING_B64")
        if cs_b64 is None:
            pytest.skip(
                "Test requires setting AZURE_IOTHUB_CONNECTIONSTRING "
                + "or AZURE_IOTHUB_CONNECTIONSTRING_B64"
            )
        connection_string = b64decode(cs_b64).decode("utf-8")
    return connection_string


@pytest.fixture(scope="function")
def azure_user(clean_mongo) -> Optional[User]:
    """Create Mender user and save Azure IoT Hub connection string in azure-iot-manager database."""
    connection_string = get_connection_string()
    api_azure = ApiClient(base_url=iot.URL_MGMT)
    try:
        tenant = create_org(
            "TestAzureDeviceLifecycle",
            f"user+{uuid.uuid4()}@example.com",
            "password123",
        )
        user = tenant.users[0]
        user.tenant = tenant
    except RuntimeError:  # If open-source
        user = create_user(f"user+{uuid.uuid4()}@example.com", "password123")

    # Authorize
    rsp = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert rsp.status_code == 200
    user.token = rsp.text

    settings = {"connection_string": connection_string}
    # put connection_string in azure-iot-manager database
    rsp = api_azure.with_auth(user.token).call("PUT", iot.URL_SETTINGS, body=settings)
    assert rsp.status_code == 204
    yield user


class _TestAzureDeviceLifecycleBase:
    """Test device lifecycle in real or mocked Azure IoT Hub. Real Azure is used by default in CI.

    Note: Following code needs to be placed in azure-iot-manager's router.go to enable insecure HTTPS requests when mocked Azure is used
        conf := NewConfig(config...)
        customTransport := &(*http.DefaultTransport.(*http.Transport))
        customTransport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
        if conf.Client == nil {
            conf.Client = &http.Client{Transport: customTransport}
        }
    """

    @classmethod
    def setup_class(cls):
        cls.mock_azure_iot_hub = os.environ.get("MOCK_AZURE_IOT_HUB")

        if cls.mock_azure_iot_hub:
            mock_sas_key = "QXp1cmUgSW90IEh1YiBjb25uZWN0aW9uIHN0cmluZw=="
            mock_sas_policy = "mender-test-policy"
            os.environ[
                "AZURE_IOTHUB_CONNECTIONSTRING"
            ] = f"HostName={HTTPServer.DEFAULT_LISTEN_HOST}:{HTTPServer.DEFAULT_LISTEN_PORT};SharedAccessKeyName={mock_sas_policy};SharedAccessKey={mock_sas_key}"

            cls.azure_client = MagicMock()
            IoTHubRegistryManager.return_value = IoTHubRegistryManager(
                connection_string=os.environ.get("AZURE_IOTHUB_CONNECTIONSTRING"),
                host="mock_host",
                token_credential="test_token",
            )

        cls.api_devauth_devices = ApiClient(base_url=deviceauth.URL_DEVICES)
        cls.api_devauth_mgmt = ApiClient(base_url=deviceauth.URL_MGMT)
        cls.api_azure = ApiClient(base_url=iot.URL_MGMT)
        cls.api_deviceconfig = ApiClient(base_url=deviceconfig.URL_MGMT)

        cls.devices = list()
        cls.logger = logging.getLogger(cls.__class__.__name__)

        cls.connection_string = get_connection_string()
        cls.azure_client = IoTHubRegistryManager.from_connection_string(
            cls.connection_string
        )

    @classmethod
    def teardown_class(cls):
        """Remove all devices created during test from Azure IoT Hub."""
        if not cls.mock_azure_iot_hub:
            cls.logger.info(
                f"Azure IoT Hub test teardown - removing devices: {cls.devices}"
            )
            for device_id in cls.devices:
                cls.azure_client.delete_device(device_id)

    @staticmethod
    def _prepare_iot_hub_upsert_device_response(status: str = "enabled") -> Dict:
        """Adjustable Azure IoT Hub GET /devices/<ID> response model."""
        return {
            "status": status,
            "authentication": {
                "type": "sas",
                "symmetricKey": {
                    "primaryKey": "Tm9ydGhlcm4udGVjaCBpcyB0aGUgYmVzdCBjb21wYW55IGluIHRoZSB3b3JsZA==",
                    "secondaryKey": "Tm9ydGhlcm4udGVjaCAtIHNlY3VyaW5nIHdvcmxkJ3MgY29ubmVjdGVkIGRldmljZXM=",
                },
                "x509Thumbprint": {"primaryThumbprint": "", "secondaryThumbprint": ""},
            },
            "capabilities": {"iotEdge": False},
            "connectionState": "Disconnected",
        }

    def _prepare_device(
        self,
        azure_user: User,
        httpserver: HTTPServer,
        httpserver_ssl_context: ssl.SSLContext,
    ) -> Device:
        """Create accepted device in Mender and make sure it has been successfully added in Azure IoT Hub."""
        if self.mock_azure_iot_hub:
            httpserver.expect_oneshot_request(
                re.compile("^/devices"),
                method="PUT",
                query_string="api-version=2021-04-12",
            ).respond_with_json(self._prepare_iot_hub_upsert_device_response())
            httpserver.expect_oneshot_request(
                re.compile("^/devices"),
                method="GET",
                query_string="api-version=2021-04-12",
            ).respond_with_data(status=200)

        tenant_token = getattr(getattr(azure_user, "tenant", {}), "tenant_token", "")
        dev = make_accepted_device(
            self.api_devauth_devices,
            self.api_devauth_mgmt,
            azure_user.token,
            tenant_token=tenant_token,
            test_type="azure",
        )
        self.devices.append(dev.id)
        for _ in retrier(attempts=5, sleeptime=1):
            rsp = self.api_azure.with_auth(azure_user.token).call(
                "GET", iot.URL_DEVICE(dev.id)
            )
            if rsp.status_code == 200:
                break
        return dev

    @retriable(sleeptime=1, attempts=5)
    def _check_deviceconfig(self, azure_user: User, device_id: str):
        """Check if Azure IoT Hub primary and secondary keys have been added to deviceconfig database."""
        rsp = self.api_deviceconfig.with_auth(azure_user.token).call(
            "GET", deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=device_id)
        )
        assert rsp.status_code == 200
        conf = rsp.json().get("configured")
        assert len(conf) > 0
        assert "$azure.primaryKey" in conf
        assert "$azure.secondaryKey" in conf

    @retriable(sleeptime=1, attempts=5)
    def _check_deviceauth(self, azure_user: User, device_id: str):
        """Check if Azure IoT Hub device ID has been added to deviceauth database (devices collection)."""
        response = self.api_devauth_mgmt.with_auth(azure_user.token).call(
            "GET", deviceauth.URL_DEVICE.format(id=device_id)
        )
        assert response.status_code == 200
        external_config = response.json().get("external")
        assert len(external_config) > 0
        assert external_config["provider"] == "Azure"

        if self.mock_azure_iot_hub:
            self.azure_client.get_device = Mock()
            type(self.azure_client.get_device.return_value).device_id = PropertyMock(
                return_value=device_id
            )

        device_info = self.azure_client.get_device(device_id)
        assert external_config["id"] == device_info.device_id

    @pytest.mark.parametrize("status", ["rejected", "noauth"])
    def test_device_accept_and_reject_or_dismiss(
        self,
        status,
        azure_user: User,
        httpserver: HTTPServer,
        httpserver_ssl_context: ssl.SSLContext,
    ):
        """Test how accepted-rejected and accepted-dismissed Mender flow affects Azure IoT Hub devices."""
        dev = self._prepare_device(azure_user, httpserver, httpserver_ssl_context)

        @retriable(sleeptime=1, attempts=5)
        def set_device_status_in_mender(desired_status: str):
            """Set device status in Mender."""
            if self.mock_azure_iot_hub:
                httpserver.expect_oneshot_request(
                    re.compile("^/devices"),
                    method="GET",
                    query_string="api-version=2021-04-12",
                ).respond_with_json(self._prepare_iot_hub_upsert_device_response())
                httpserver.expect_oneshot_request(
                    re.compile("^/devices"),
                    method="PUT",
                    query_string="api-version=2021-04-12",
                ).respond_with_json(
                    self._prepare_iot_hub_upsert_device_response(status="disabled")
                )

            authset_id = dev.authsets[0].id
            if status == "noauth":
                rsp = self.api_devauth_mgmt.with_auth(azure_user.token).call(
                    "DELETE",
                    deviceauth.URL_AUTHSET,
                    path_params={"did": dev.id, "aid": authset_id},
                )
            else:
                rsp = self.api_devauth_mgmt.with_auth(azure_user.token).call(
                    "PUT",
                    deviceauth.URL_AUTHSET_STATUS,
                    deviceauth.req_status(desired_status),
                    path_params={"did": dev.id, "aid": authset_id},
                )
            assert rsp.status_code == 204

        @retriable(sleeptime=2, attempts=5)
        def check_if_device_status_is_set_to_disabled():
            """Check if device status in IoT Hub was changed to "disabled"."""
            if self.mock_azure_iot_hub:
                httpserver.expect_oneshot_request(
                    re.compile("^/devices"),
                    method="GET",
                    query_string="api-version=2021-04-12",
                ).respond_with_json(
                    self._prepare_iot_hub_upsert_device_response(status="disabled")
                )

            rsp = self.api_azure.with_auth(azure_user.token).call(
                "GET", iot.URL_DEVICE(dev.id)
            )
            assert rsp.status_code == 200
            assert rsp.json()["status"] == "disabled"

        self._check_deviceconfig(azure_user, dev.id)
        self._check_deviceauth(azure_user, dev.id)
        set_device_status_in_mender(status)
        check_if_device_status_is_set_to_disabled()

    def test_device_provision_and_decomission(
        self,
        azure_user: User,
        httpserver: HTTPServer,
        httpserver_ssl_context: ssl.SSLContext,
    ):
        """Test how accepted-decommissioned Mender flow affects Azure IoT Hub devices."""
        dev = self._prepare_device(azure_user, httpserver, httpserver_ssl_context)

        @retriable(sleeptime=2, attempts=5)
        def decommission_device():
            """Decommission the device in Mender, which in turn removes the device from IoT Hub."""
            if self.mock_azure_iot_hub:
                httpserver.expect_oneshot_request(
                    re.compile("^/devices"),
                    method="DELETE",
                    query_string="api-version=2021-04-12",
                ).respond_with_data(status=200)
                httpserver.expect_oneshot_request(
                    re.compile("^/devices"),
                    method="GET",
                    query_string="api-version=2021-04-12",
                ).respond_with_data(status=404)

            rsp = self.api_devauth_mgmt.with_auth(azure_user.token).call(
                "DELETE", deviceauth.URL_DEVICE.format(id=dev.id),
            )
            assert rsp.status_code == 204

        @retriable(sleeptime=2, attempts=5)
        def check_if_device_was_removed_from_azure():
            """Check if device was remove from Azure IoT HUb using azure-iot-manager service proxy."""
            if self.mock_azure_iot_hub:
                httpserver.expect_oneshot_request(
                    re.compile("^/devices"),
                    method="GET",
                    query_string="api-version=2021-04-12",
                ).respond_with_data(status=404)

            rsp = self.api_azure.with_auth(azure_user.token).call(
                "GET", iot.URL_DEVICE(dev.id)
            )
            assert rsp.status_code == 404
            self.devices.remove(dev.id)

        self._check_deviceconfig(azure_user, dev.id)
        self._check_deviceauth(azure_user, dev.id)
        decommission_device()
        check_if_device_was_removed_from_azure()


class TestAzureDeviceLifecycle(_TestAzureDeviceLifecycleBase):
    pass


class TestAzureDeviceLifecycleEnterprise(_TestAzureDeviceLifecycleBase):
    pass
