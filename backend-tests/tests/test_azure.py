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

import pytest
import logging
import os
import time
import uuid
from base64 import b64decode
from datetime import datetime, timedelta

import docker

from testutils.api import (
    azure,
    deviceauth,
    deviceconfig,
    useradm,
)
from testutils.api.client import ApiClient
from testutils.common import (
    Authset,
    create_org,
    create_user,
    create_user_test_setup,
    create_tenant_test_setup,
    clean_mongo,
    make_accepted_device,
    mongo_cleanup,
    mongo,
)
from testutils.infra.container_manager.docker_manager import DockerNamespace
from testutils.infra.container_manager.kubernetes_manager import (
    KubernetesNamespace,
    isK8S,
)


class _TestAzureBase:
    azure_api = ApiClient(base_url=azure.URL_MGMT, host=azure.HOST, schema="http://")

    def save_settings(self, user, settings):
        r = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("PUT", azure.URL_SETTINGS, settings)
        )
        return r

    def get_settings(self, user):
        r = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("GET", azure.URL_SETTINGS)
        )
        return r


class TestAzureSettingsEnterprise(_TestAzureBase):
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    def test_get_and_set(self, clean_mongo):
        """
        Check that we can set and get settings
        """
        self.logger.info("creating tenant and user")
        t = create_tenant_test_setup()

        for expected_settings in [
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=OldKey"
            },
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=NewKey"
            },
        ]:
            r = super().save_settings(t.users[0], expected_settings)
            assert r.status_code == 204
            self.logger.info("saved settings")

            self.logger.info("getting settings")
            r = super().get_settings(t.users[0])
            assert r.status_code == 200
            self.logger.info("got settings: %s" % r.text)
            r_json = r.json()
            assert "connection_string" in r_json.keys()
            actual = r_json["connection_string"]
            # Check for equality by parts:
            # Check that actual properties are a subset of expected settings
            for part in actual.split(";"):
                assert part in expected_settings["connection_string"]
            # Check that expected properties are a subset of actual settings
            for part in expected_settings["connection_string"].split(";"):
                assert part in actual


class TestAzureSettings(_TestAzureBase):
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    def test_get_and_set(self, clean_mongo):
        """
        Check that we can set and get settings
        """
        self.logger.info("creating tenant and user")
        u = create_user_test_setup()

        for expected_settings in [
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=OldKey"
            },
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=NewKey"
            },
        ]:
            r = super().save_settings(u, expected_settings)
            assert r.status_code == 204
            self.logger.info("saved settings")

            self.logger.info("getting settings")
            r = super().get_settings(u)
            assert r.status_code == 200
            self.logger.info("got settings: %s" % r.text)
            r_json = r.json()
            assert "connection_string" in r_json.keys()
            actual = r_json["connection_string"]
            # Check for equality by parts:
            # Check that actual properties are a subset of expected settings
            for part in actual.split(";"):
                assert part in expected_settings["connection_string"]
            # Check that expected properties are a subset of actual settings
            for part in expected_settings["connection_string"].split(";"):
                assert part in actual


@pytest.fixture(scope="function")
def azure_user(clean_mongo):
    connection_string = os.environ.get("AZURE_IOTHUB_CONNECTIONSTRING")
    if connection_string is None:
        cs_b64 = os.environ.get("AZURE_IOTHUB_CONNECTIONSTRING_B64")
        if cs_b64 is None:
            pytest.skip(
                "Test requires setting AZURE_IOTHUB_CONNECTIONSTRING "
                + "or AZURE_IOTHUB_CONNECTIONSTRING_B64"
            )
        connection_string = b64decode(cs_b64)
    api_azure = ApiClient(base_url=azure.URL_MGMT)
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
    rsp = api_azure.with_auth(user.token).call("PUT", azure.URL_SETTINGS, body=settings)
    assert rsp.status_code == 204
    yield user


class _TestAzureDeviceLifecycle:
    def test_device_provision_and_decomission(self, azure_user):
        timeout = datetime.now() + timedelta(minutes=5)
        api_devauth_devices = ApiClient(base_url=deviceauth.URL_DEVICES)
        api_devauth_mgmt = ApiClient(base_url=deviceauth.URL_MGMT)
        api_azure = ApiClient(base_url=azure.URL_MGMT)
        api_deviceconfig = ApiClient(base_url=deviceconfig.URL_MGMT)

        tenant_token = getattr(getattr(azure_user, "tenant", {}), "tenant_token", "")
        dev = make_accepted_device(
            api_devauth_devices,
            api_devauth_mgmt,
            azure_user.token,
            tenant_token=tenant_token,
        )

        # Query iothub for device while it is being provisioned
        rsp = None
        while datetime.now() < timeout:
            rsp = api_azure.with_auth(azure_user.token).call(
                "GET", azure.URL_DEVICE(dev.id)
            )
            if rsp.status_code == 200:
                azure_dev = rsp.json()
                break
            time.sleep(1.0)
        else:
            raise TimeoutError("timed out waiting for hub to provision device")
        assert rsp.status_code == 200

        try:
            # Check deviceconfig
            conf = {}
            while datetime.now() < timeout:
                rsp = api_deviceconfig.with_auth(azure_user.token).call(
                    "GET", deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=dev.id)
                )
                assert rsp.status_code == 200
                conf = rsp.json().get("configured", None)
                if len(conf) > 0:
                    break
                time.sleep(1)
            else:
                raise TimeoutError("timed out waiting for deviceconfig to update")
            assert "$azure.primaryKey" in conf
            assert "$azure.secondaryKey" in conf

        finally:
            # Make sure we at least try to decommission the device,
            # which in turn removes the device from iothub.
            rsp = api_devauth_mgmt.with_auth(azure_user.token).call(
                "DELETE", deviceauth.URL_DEVICE.format(id=dev.id),
            )
            assert rsp.status_code == 204

            while datetime.now() < timeout:
                rsp = api_azure.with_auth(azure_user.token).call(
                    "GET", azure.URL_DEVICE(dev.id)
                )
                if rsp.status_code != 200:
                    break
                time.sleep(1.0)
            else:
                raise TimeoutError("timed out waiting for hub to decommission device")

            assert rsp.status_code == 404


class TestAzureDeviceLifecycle(_TestAzureDeviceLifecycle):
    pass


class TestAzureDeviceLifecycleEnterprise(_TestAzureDeviceLifecycle):
    pass
