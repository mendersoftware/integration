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

from typing import Dict
from typing import Optional
import pytest
import logging
import os
import re
import ssl
import uuid
from base64 import b64decode

import trustme
from azure.iot.hub import IoTHubRegistryManager
from pytest_httpserver import HTTPServer
from redo import retrier, retriable
from requests.models import Response

from testutils.api import (
    deviceauth,
    deviceconfig,
    iot_manager as iot,
    useradm,
)
from testutils.api.client import ApiClient, get_free_tcp_port
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


HTTPServer.DEFAULT_LISTEN_PORT = get_free_tcp_port()
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

    def save_integration(self, user: User, integration: Dict) -> Response:
        response = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("POST", iot.URL_INTEGRATIONS, integration)
        )
        return response

    def get_integrations(self, user: User) -> Response:
        response = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("GET", iot.URL_INTEGRATIONS)
        )
        return response

    def check_integrations(self, user: User, expected_integration: Dict):
        """Make sure iot-manager properly saves connection strings in its database."""
        response = self.save_integration(user, expected_integration)
        assert response.status_code == 201
        self.logger.info("saved integrations")

        self.logger.info("getting integrations")
        response = self.get_integrations(user)
        assert response.status_code == 200
        self.logger.info(f"got integrations: {response.text}")
        integrations = response.json()
        assert len(integrations) > 0
        assert "credentials" in integrations[0].keys()
        assert "connection_string" in integrations[0]["credentials"].keys()
        actual = integrations[0]["credentials"]["connection_string"]
        # Check for equality by parts:
        # Check that actual properties are a subset of expected integrations
        for part in actual.split(";"):
            # SharedAccessKey will be masked, with only the first 4 characters visible
            # and the rest of the string replaced with a place holder. For this reason,
            # we'll test the first 20 bytes only
            if part.startswith("SharedAccessKey="):
                part = part[:20]
            assert part in expected_integration["credentials"]["connection_string"]
        # Check that expected properties are a subset of actual integrations
        for part in expected_integration["credentials"]["connection_string"].split(";"):
            # SharedAccessKey will be masked, with only the first 4 characters visible
            # and the rest of the string replaced with a place holder. For this reason,
            # we'll test the first 20 bytes only
            if part.startswith("SharedAccessKey="):
                part = part[:20]
            assert part in actual


class TestAzureIntegrations(_TestAzureBase):
    @pytest.mark.parametrize(
        "expected_integration",
        [
            {
                "provider": "iot-hub",
                "credentials": {
                    "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=OldKey",
                    "type": "sas",
                },
            },
            {
                "provider": "iot-hub",
                "credentials": {
                    "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=NewKey",
                    "type": "sas",
                },
            },
        ],
    )
    def test_get_and_set(self, clean_mongo, expected_integration):
        """
        Check that we can set and get integrations
        """
        self.logger.info("creating user in OS mode")
        user = create_user_test_setup()
        self.check_integrations(user, expected_integration)


class TestAzureIntegrationsEnterprise(_TestAzureBase):
    @pytest.mark.parametrize(
        "expected_integration",
        [
            {
                "provider": "iot-hub",
                "credentials": {
                    "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=OldKey",
                    "type": "sas",
                },
            },
            {
                "provider": "iot-hub",
                "credentials": {
                    "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=NewKey",
                    "type": "sas",
                },
            },
        ],
    )
    def test_get_and_set(self, clean_mongo, expected_integration):
        """
        Check that we can set and get integrations
        """
        self.logger.info("creating tenant and user in enterprise mode")
        tenant = create_tenant_test_setup()
        user = tenant.users[0]
        self.check_integrations(user, expected_integration)


def get_connection_string():
    """Determine whether AZURE_IOTHUB_CONNECTIONSTRING or AZURE_IOTHUB_CONNECTIONSTRING_B64
    environment variable is set.
    """
    azure_iot_hub_mock = os.environ.get("AZURE_IOTHUB_MOCK")
    if azure_iot_hub_mock:
        mock_sas_key = "QXp1cmUgSW90IEh1YiBjb25uZWN0aW9uIHN0cmluZw=="
        mock_sas_policy = "mender-test-policy"
        return f"HostName={HTTPServer.DEFAULT_LISTEN_HOST}:{HTTPServer.DEFAULT_LISTEN_PORT};SharedAccessKeyName={mock_sas_policy};SharedAccessKey={mock_sas_key}"
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
    """Create Mender user and create an Azure IoT Hub integration in iot-manager using the connection string."""
    api_azure = ApiClient(base_url=iot.URL_MGMT)
    uuidv4 = str(uuid.uuid4())
    try:
        tenant = create_org(
            "test.mender.io-" + uuidv4, f"user+{uuidv4}@example.com", "password123",
        )
        user = tenant.users[0]
        user.tenant = tenant
    except RuntimeError:  # If open-source
        user = create_user(f"user+{uuidv4}@example.com", "password123")

    # Authorize
    rsp = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert rsp.status_code == 200
    user.token = rsp.text

    connection_string = get_connection_string()
    integration = {
        "provider": "iot-hub",
        "credentials": {"connection_string": connection_string, "type": "sas"},
    }
    # create the integration in iot-manager
    rsp = api_azure.with_auth(user.token).call(
        "POST", iot.URL_INTEGRATIONS, body=integration
    )
    assert rsp.status_code == 201
    yield user


def get_azure_client():
    connection_string = get_connection_string()
    azure_iot_hub_mock = os.environ.get("AZURE_IOTHUB_MOCK")
    if azure_iot_hub_mock:
        client = IoTHubRegistryManager(
            connection_string=connection_string,
            host="mock_host",
            token_credential="test_token",
        )
        client.protocol.config.connection.verify = False
        return client
    return IoTHubRegistryManager.from_connection_string(connection_string)


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
        cls.azure_iot_hub_mock = os.environ.get("AZURE_IOTHUB_MOCK")
        cls.azure_client = get_azure_client()

        cls.api_devauth_devices = ApiClient(base_url=deviceauth.URL_DEVICES)
        cls.api_devauth_mgmt = ApiClient(base_url=deviceauth.URL_MGMT)
        cls.api_azure = ApiClient(base_url=iot.URL_MGMT)
        cls.api_deviceconfig = ApiClient(base_url=deviceconfig.URL_MGMT)

        cls.devices = list()
        cls.logger = logging.getLogger(cls.__class__.__name__)

    @classmethod
    def teardown_class(cls):
        """Remove all devices created during test from Azure IoT Hub."""
        if not cls.azure_iot_hub_mock:
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
                "provider": "sas",
                "symmetricKey": {
                    "primaryKey": "Tm9ydGhlcm4udGVjaCBpcyB0aGUgYmVzdCBjb21wYW55IGluIHRoZSB3b3JsZA==",
                    "secondaryKey": "Tm9ydGhlcm4udGVjaCAtIHNlY3VyaW5nIHdvcmxkJ3MgY29ubmVjdGVkIGRldmljZXM=",
                },
                "x509Thumbprint": {"primaryThumbprint": "", "secondaryThumbprint": ""},
            },
            "properties": {
                "desired": {"key": "value"},
                "reported": {"another-key": "another-value"},
            },
            "tags": {"tag-key": "tag-value"},
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
        if self.azure_iot_hub_mock:
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
            httpserver.expect_oneshot_request(
                re.compile("^/devices"),
                method="PUT",
                query_string="api-version=2021-04-12",
            ).respond_with_data(status=200)
            httpserver.expect_oneshot_request(
                re.compile("^/twins"),
                method="PATCH",
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
            if self.azure_iot_hub_mock:
                httpserver.expect_oneshot_request(
                    re.compile("^/twins"),
                    method="GET",
                    query_string="api-version=2021-04-12",
                ).respond_with_json(self._prepare_iot_hub_upsert_device_response())
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
        assert "azureConnectionString" in conf

    @retriable(sleeptime=2, attempts=5)
    def _check_if_device_status_is_set_to_value(
        self, azure_user: User, httpserver: HTTPServer, device_id: str, status: str
    ):
        """Check if device status in IoT Hub is set to the desired value."""
        if self.azure_iot_hub_mock:
            httpserver.expect_oneshot_request(
                re.compile("^/devices"),
                method="GET",
                query_string="api-version=2021-04-12",
            ).respond_with_json(
                self._prepare_iot_hub_upsert_device_response(status=status)
            )
        # device exists in iot-manager
        rsp = self.api_azure.with_auth(azure_user.token).call(
            "GET", iot.URL_DEVICE_STATE(device_id)
        )
        assert rsp.status_code == 200
        # check the status of the device in IoT Hub
        device = get_azure_client().get_device(device_id)
        assert device.status == status

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
            if self.azure_iot_hub_mock:
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

        self._check_deviceconfig(azure_user, dev.id)
        self._check_if_device_status_is_set_to_value(
            azure_user, httpserver, dev.id, "enabled"
        )
        #
        set_device_status_in_mender(status)
        self._check_if_device_status_is_set_to_value(
            azure_user, httpserver, dev.id, "disabled"
        )

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
            if self.azure_iot_hub_mock:
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
            if self.azure_iot_hub_mock:
                httpserver.expect_oneshot_request(
                    re.compile("^/devices"),
                    method="GET",
                    query_string="api-version=2021-04-12",
                ).respond_with_data(status=404)

            rsp = self.api_azure.with_auth(azure_user.token).call(
                "GET", iot.URL_DEVICE_STATE(dev.id)
            )
            assert rsp.status_code == 404
            self.devices.remove(dev.id)

        self._check_deviceconfig(azure_user, dev.id)
        self._check_if_device_status_is_set_to_value(
            azure_user, httpserver, dev.id, "enabled"
        )
        #
        decommission_device()
        check_if_device_was_removed_from_azure()

    def test_device_twin(
        self,
        azure_user: User,
        httpserver: HTTPServer,
        httpserver_ssl_context: ssl.SSLContext,
    ):
        """Test device state synchronization with IoT Hub Device Twin"""
        dev = self._prepare_device(azure_user, httpserver, httpserver_ssl_context)
        self._check_if_device_status_is_set_to_value(
            azure_user, httpserver, dev.id, "enabled"
        )

        # get the all device states (device twins)
        if self.azure_iot_hub_mock:
            httpserver.expect_oneshot_request(
                re.compile("^/devices"),
                method="GET",
                query_string="api-version=2021-04-12",
            ).respond_with_json(self._prepare_iot_hub_upsert_device_response())
        rsp = self.api_azure.with_auth(azure_user.token).call(
            "GET", iot.URL_DEVICE_STATE(dev.id)
        )
        assert rsp.status_code == 200
        states = rsp.json()
        assert len(states.keys()) == 1
        integration_id = list(states.keys())[0]
        assert "desired" in states[integration_id]
        assert "reported" in states[integration_id]

        # set the device state (device twin)
        if self.azure_iot_hub_mock:
            httpserver.expect_oneshot_request(
                re.compile("^/twins"),
                method="GET",
                query_string="api-version=2021-04-12",
            ).respond_with_json(self._prepare_iot_hub_upsert_device_response())
            httpserver.expect_oneshot_request(
                re.compile("^/twins"),
                method="PUT",
                query_string="api-version=2021-04-12",
            ).respond_with_data(status=200)
        twin = {
            "desired": {"key": "value"},
        }
        rsp = (
            self.api_azure.with_auth(azure_user.token)
            .with_header("Content-Type", "application/json")
            .call("PUT", iot.URL_DEVICE_STATE(dev.id) + "/" + integration_id, twin)
        )
        assert rsp.status_code == 200
        state = rsp.json()
        assert "desired" in state
        assert "reported" in states[integration_id]
        assert state["desired"]["key"] == "value"

        # get the device state (device twin)
        if self.azure_iot_hub_mock:
            httpserver.expect_oneshot_request(
                re.compile("^/twins"),
                method="GET",
                query_string="api-version=2021-04-12",
            ).respond_with_json(self._prepare_iot_hub_upsert_device_response())
        rsp = self.api_azure.with_auth(azure_user.token).call(
            "GET", iot.URL_DEVICE_STATE(dev.id) + "/" + integration_id
        )
        assert rsp.status_code == 200
        state = rsp.json()
        assert "desired" in state
        assert "reported" in states[integration_id]
        assert state["desired"]["key"] == "value"


class TestAzureDeviceLifecycle(_TestAzureDeviceLifecycleBase):
    pass


class TestAzureDeviceLifecycleEnterprise(_TestAzureDeviceLifecycleBase):
    pass
