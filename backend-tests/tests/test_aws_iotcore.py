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

from dataclasses import dataclass
from typing import Dict
from typing import Optional
import boto3
import botocore
import pytest
import logging
import json
import os
import time
import uuid

from redo import retriable
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


AWS_ACCESS_KEY_ID = os.environ.get("AWS_IOTCORE_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_IOTCORE_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_IOTCORE_REGION")
AWS_DEVICE_POLICY_NAME = os.environ.get("AWS_IOTCORE_DEVICE_POLICY_NAME")


@dataclass
class Device:
    thing_name: str
    status: str


@dataclass
class DeviceShadow:
    thing_name: str
    shadow: Dict


def get_boto3_client(service: str):
    return boto3.client(
        service,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )


def get_device(device_id: str):
    iot = get_boto3_client("iot")
    response = iot.describe_thing(thingName=device_id)
    response = iot.list_thing_principals(thingName=response["thingName"])
    status = "UNKNOWN"
    for principal in response["principals"]:
        certificate_id = principal.rsplit("/", 1)[-1]
        response = iot.describe_certificate(certificateId=certificate_id)
        status = response["certificateDescription"]["status"]
        break
    return Device(thing_name=device_id, status=status)


def get_device_shadow(device_id: str):
    iot_data = get_boto3_client("iot-data")
    response = iot_data.get_thing_shadow(thingName=device_id)
    payload = response["payload"].read()
    shadow = json.loads(payload)["state"]
    return DeviceShadow(thing_name=device_id, shadow=shadow)


def delete_device(device_id: str):
    iot = get_boto3_client("iot")
    response = iot.list_thing_principals(thingName=device_id)
    for principal in response["principals"]:
        response = iot.detach_thing_principal(thingName=device_id, principal=principal,)
        #
        certificate_id = principal.rsplit("/", 1)[-1]
        iot.update_certificate(
            certificateId=certificate_id, newStatus="INACTIVE",
        )
        iot.detach_policy(
            policyName=device_id + "-policy", target=principal,
        )
        response = iot.delete_certificate(certificateId=certificate_id,)
    iot.delete_thing(thingName=device_id)
    iot.delete_policy(policyName=device_id + "-policy",)


class _TestAWSIoTCoreBase:
    aws_api = ApiClient(base_url=iot.URL_MGMT, host=iot.HOST, schema="http://")

    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    def save_integration(self, user: User, integration: Dict) -> Response:
        response = (
            self.aws_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("POST", iot.URL_INTEGRATIONS, integration)
        )
        return response

    def get_integrations(self, user: User) -> Response:
        response = (
            self.aws_api.with_auth(user.utoken)
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
        assert "aws" in integrations[0]["credentials"].keys()
        assert "access_key_id" in integrations[0]["credentials"]["aws"].keys()
        assert (
            integrations[0]["credentials"]["aws"]["access_key_id"] == AWS_ACCESS_KEY_ID
        )
        # the service will mask the AWS secret access key
        assert "secret_access_key" in integrations[0]["credentials"]["aws"].keys()
        assert (
            integrations[0]["credentials"]["aws"]["secret_access_key"]
            != AWS_SECRET_ACCESS_KEY
        )
        assert "region" in integrations[0]["credentials"]["aws"].keys()
        assert integrations[0]["credentials"]["aws"]["region"] == AWS_REGION
        assert "device_policy_name" in integrations[0]["credentials"]["aws"].keys()
        assert (
            integrations[0]["credentials"]["aws"]["device_policy_name"]
            == AWS_DEVICE_POLICY_NAME
        )


class TestAWSIoTCoreIntegrations(_TestAWSIoTCoreBase):
    @pytest.mark.parametrize(
        "expected_integration",
        [
            {
                "provider": "iot-core",
                "credentials": {
                    "type": "aws",
                    "aws": {
                        "access_key_id": AWS_ACCESS_KEY_ID,
                        "secret_access_key": AWS_SECRET_ACCESS_KEY,
                        "region": AWS_REGION,
                        "device_policy_name": AWS_DEVICE_POLICY_NAME,
                    },
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


class TestAWSIoTCoreIntegrationsEnterprise(_TestAWSIoTCoreBase):
    @pytest.mark.parametrize(
        "expected_integration",
        [
            {
                "provider": "iot-core",
                "credentials": {
                    "type": "aws",
                    "aws": {
                        "access_key_id": AWS_ACCESS_KEY_ID,
                        "secret_access_key": AWS_SECRET_ACCESS_KEY,
                        "region": AWS_REGION,
                        "device_policy_name": AWS_DEVICE_POLICY_NAME,
                    },
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


@pytest.fixture(scope="function")
def user(clean_mongo) -> Optional[User]:
    """Create Mender user and create an AWS IoT Core integration in iot-manager using the connection string."""
    api_iot = ApiClient(base_url=iot.URL_MGMT)
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

    integration = {
        "provider": "iot-core",
        "credentials": {
            "type": "aws",
            "aws": {
                "access_key_id": AWS_ACCESS_KEY_ID,
                "secret_access_key": AWS_SECRET_ACCESS_KEY,
                "region": AWS_REGION,
                "device_policy_name": AWS_DEVICE_POLICY_NAME,
            },
        },
    }
    # create the integration in iot-manager
    rsp = api_iot.with_auth(user.token).call(
        "POST", iot.URL_INTEGRATIONS, body=integration
    )
    assert rsp.status_code == 201
    yield user


class _TestAWSIoTCoreDeviceLifecycleBase:
    """Test device lifecycle in real AWS IoT Core."""

    @classmethod
    def setup_class(cls):
        cls.api_devauth_devices = ApiClient(base_url=deviceauth.URL_DEVICES)
        cls.api_devauth_mgmt = ApiClient(base_url=deviceauth.URL_MGMT)
        cls.api_deviceconfig = ApiClient(base_url=deviceconfig.URL_MGMT)
        cls.api_iot = ApiClient(base_url=iot.URL_MGMT)

        cls.devices = list()
        cls.logger = logging.getLogger(cls.__class__.__name__)

    @classmethod
    def teardown_class(cls):
        """Remove all devices created during test from AWS IoT Core."""
        cls.logger.info(f"AWS IoT Core test teardown - removing devices: {cls.devices}")
        # for device_id in cls.devices:
        #     delete_device(device_id)

    def _prepare_device(self, user: User) -> Device:
        """Create accepted device in Mender and make sure it has been successfully added in AWS IoT Core."""
        tenant_token = getattr(getattr(user, "tenant", {}), "tenant_token", "")
        dev = make_accepted_device(
            self.api_devauth_devices,
            self.api_devauth_mgmt,
            user.token,
            tenant_token=tenant_token,
            test_type="aws",
        )
        self.devices.append(dev.id)
        return dev

    @retriable(sleeptime=1, attempts=5)
    def _check_deviceconfig(self, user: User, device_id: str):
        """Check if AWS IoT Core primary and secondary keys have been added to deviceconfig database."""
        rsp = self.api_deviceconfig.with_auth(user.token).call(
            "GET", deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=device_id)
        )
        assert rsp.status_code == 200
        conf = rsp.json().get("configured")
        assert len(conf) > 0
        assert "awsCertificate" in conf
        assert "awsPrivateKey" in conf

    @retriable(sleeptime=2, attempts=5)
    def _check_if_device_status_is_set_to_value(
        self, user: User, device_id: str, status: str
    ):
        """Check if device status in IoT Core is set to the desired value."""
        # device exists in iot-manager
        rsp = self.api_iot.with_auth(user.token).call(
            "GET", iot.URL_DEVICE_STATE(device_id)
        )
        assert rsp.status_code == 200
        # check the status of the device in IoT Core
        device = get_device(device_id)
        assert device.status == status

    @pytest.mark.parametrize("status", ["rejected", "noauth"])
    def test_device_accept_and_reject_or_dismiss(
        self, status, user: User,
    ):
        """Test how accepted-rejected and accepted-dismissed Mender flow affects AWS IoT Core devices."""
        dev = self._prepare_device(user)

        @retriable(sleeptime=1, attempts=5)
        def set_device_status_in_mender(desired_status: str):
            """Set device status in Mender."""
            authset_id = dev.authsets[0].id
            if status == "noauth":
                rsp = self.api_devauth_mgmt.with_auth(user.token).call(
                    "DELETE",
                    deviceauth.URL_AUTHSET,
                    path_params={"did": dev.id, "aid": authset_id},
                )
            else:
                rsp = self.api_devauth_mgmt.with_auth(user.token).call(
                    "PUT",
                    deviceauth.URL_AUTHSET_STATUS,
                    deviceauth.req_status(desired_status),
                    path_params={"did": dev.id, "aid": authset_id},
                )
            assert rsp.status_code == 204

        self._check_deviceconfig(user, dev.id)
        self._check_if_device_status_is_set_to_value(user, dev.id, "ACTIVE")
        #
        set_device_status_in_mender(status)
        self._check_if_device_status_is_set_to_value(user, dev.id, "INACTIVE")

    def test_device_provision_and_decomission(
        self, user: User,
    ):
        """Test how accepted-decommissioned Mender flow affects AWS IoT Core devices."""
        dev = self._prepare_device(user)

        @retriable(sleeptime=2, attempts=5)
        def decommission_device():
            """Decommission the device in Mender, which in turn removes the device from IoT Core."""
            rsp = self.api_devauth_mgmt.with_auth(user.token).call(
                "DELETE", deviceauth.URL_DEVICE.format(id=dev.id),
            )
            assert rsp.status_code == 204

        @retriable(sleeptime=2, attempts=5)
        def check_if_device_was_removed_from_aws():
            """Check if device was remove from AWS IoT HUb using aws-iot-manager service proxy."""
            rsp = self.api_iot.with_auth(user.token).call(
                "GET", iot.URL_DEVICE_STATE(dev.id)
            )
            assert rsp.status_code == 404
            self.devices.remove(dev.id)

        self._check_deviceconfig(user, dev.id)
        self._check_if_device_status_is_set_to_value(user, dev.id, "ACTIVE")
        #
        decommission_device()
        check_if_device_was_removed_from_aws()

    def test_device_shadow(
        self, user: User,
    ):
        """Test device state synchronization with IoT Core Device Twin"""
        dev = self._prepare_device(user)
        self._check_if_device_status_is_set_to_value(user, dev.id, "ACTIVE")

        # get the all device states (device shadows)
        rsp = self.api_iot.with_auth(user.token).call(
            "GET", iot.URL_DEVICE_STATE(dev.id)
        )
        assert rsp.status_code == 200
        states = rsp.json()
        assert len(states.keys()) == 1
        integration_id = list(states.keys())[0]
        assert "desired" in states[integration_id]
        assert "reported" in states[integration_id]

        # set the device state (device shadow)
        shadow = {
            "desired": {"key": "value"},
        }
        rsp = (
            self.api_iot.with_auth(user.token)
            .with_header("Content-Type", "application/json")
            .call("PUT", iot.URL_DEVICE_STATE(dev.id) + "/" + integration_id, shadow)
        )
        assert rsp.status_code == 200
        state = rsp.json()
        assert "desired" in state
        assert "reported" in states[integration_id]
        assert state["desired"]["key"] == "value"

        # get the device state (device shadow)
        assert rsp.status_code == 200
        state = rsp.json()
        assert "desired" in state
        assert "reported" in states[integration_id]
        assert state["desired"]["key"] == "value"


class TestAWSIoTCoreDeviceLifecycle(_TestAWSIoTCoreDeviceLifecycleBase):
    pass


class TestAWSIoTCoreDeviceLifecycleEnterprise(_TestAWSIoTCoreDeviceLifecycleBase):
    pass
