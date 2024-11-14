# Copyright 2023 Northern.tech AS
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
import queue
import threading
import time
import subprocess
from tempfile import NamedTemporaryFile
from os import path

from datetime import datetime, timedelta, timezone

from testutils.infra.container_manager import factory
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra.device import MenderDevice
from testutils.common import create_org, create_user
from testutils.api.client import ApiClient
from testutils.api import deviceauth, useradm, inventory, deployments
import uuid


container_factory = factory.get_factory()

TIMEOUT = timedelta(minutes=5)
"""
 COMPAT_MENDER_VERSIONS array stores the versions of the virtual device images we test against.
 In order to add a new client: add a new a composition file in
extra/integration-testing/test-compat/docker-compose.compat-VERSION.yml
where VERSION is the version string.
"""
COMPAT_MENDER_VERSIONS = factory.DockerComposeCompatibilitySetup.get_versions()


@pytest.fixture(scope="function")
def setup_os_compat():
    def create(client_service):
        env = container_factory.get_compatibility_setup(client_service=client_service)
        env.setup()

        uuid_val = str(uuid.uuid4())
        env.user = create_user(
            f"test-{uuid_val}@mender.io", "correcthorse", containers_namespace=env.name
        )
        env.populate_clients()

        clients = env.get_mender_clients()
        assert len(clients) == 1, "Failed to setup clients: expecting exactly one."
        env.devices = []
        dev = MenderDevice(clients[0])
        dev.ssh_is_opened()
        env.devices.append(dev)

        return env

    return create


@pytest.fixture(scope="function")
def setup_ent_compat():
    def create(client_service):
        env = container_factory.get_compatibility_setup(
            client_service=client_service, enterprise=True
        )
        env.setup()

        uuid_val = str(uuid.uuid4())
        env.tenant = create_org(
            "Mender",
            "test-%s@mender.io" % uuid_val,
            "correcthorse",
            containers_namespace=env.name,
            container_manager=env,
        )
        env.user = env.tenant.users[0]

        env.populate_clients(tenant_token=env.tenant.tenant_token)

        clients = env.get_mender_clients()
        assert len(clients) == 1, "Failed to setup clients: expecting exactly one."
        env.devices = []
        dev = MenderDevice(clients[0])
        dev.ssh_is_opened()
        env.devices.append(dev)

        return env

    return create


def accept_devices(api_deviceauth, devices=None):
    """
    Update the device status for the given set of devices to "accepted"

    :param api_deviceauth: testutils.api.client.ApiClient setup and authorized
                           to use the deviceauth management api,
                           i.e. api_client.with_auth(api_token)
    :param devices: list of dict-type devices as returned by
                    GET /api/management/v1/devauth/devices
                    If left None, all pending devices are accepted.
    """
    if devices is None:
        rsp = api_deviceauth.call(
            "GET", deviceauth.URL_MGMT_DEVICES, qs_params={"status": "pending"}
        )
        assert rsp.status_code == 200
        devices = rsp.json()

    for device in devices:
        rsp = api_deviceauth.call(
            "PUT",
            deviceauth.URL_AUTHSET_STATUS.format(
                did=device["id"], aid=device["auth_sets"][0]["id"]
            ),
            body={"status": "accepted"},
        )
        assert rsp.status_code == 204


def assert_inventory_updated(api_inventory, num_devices, timeout=TIMEOUT):
    """
    Polls the inventory every second, checking all devices reported some
    attributes with inventory scope.
    :param api_inventory: testutils.api.client.ApiClient setup and authorized
                          to use the inventory management api,
                          i.e. api_client.with_auth(api_token).
    :param num_devices: the number of devices to wait for.
    :param timeout: optional timeout (defaults to 5min).
    """
    update_after = datetime.now(timezone.utc)
    deadline = update_after + timeout
    num_updated = 0
    while num_updated < num_devices:
        if datetime.now(timezone.utc) > deadline:
            pytest.fail("timeout waiting for devices to submit inventory")

        rsp = api_inventory.call(
            "GET", inventory.URL_DEVICES, qs_params={"per_page": num_devices * 2}
        )
        assert rsp.status_code == 200
        dev_invs = rsp.json()
        assert (
            len(dev_invs) <= num_devices
        ), "Received more devices from inventory than there exists"
        if len(dev_invs) < num_devices:
            time.sleep(1)
            continue
        # Check if inventory attributes has been reported
        num_updated = 0
        for device in dev_invs:
            updated = False
            for attr in device["attributes"]:
                if attr["scope"] == "inventory":
                    num_updated += 1
                    updated = True
                    break
            if updated == False:
                time.sleep(1)
                break


def assert_successful_deployment(api_deployments, deployment_id, timeout=TIMEOUT):
    """
    Waits for the ongoing deployment (specified by deployment_id) to finish
    and asserting all devices were successfully upgraded.
    :param api_deployments: testutils.api.client.ApiClient setup and authorized
                             to use the deployments management api,
                             i.e. api_client.with_auth(api_token)
    :param deployment_id: deployment id to watch
    :param timeout: optional timeout value to wait for deployment (defaults to 5min)
    """
    deadline = datetime.now() + timeout
    while True:
        rsp = api_deployments.call(
            "GET", deployments.URL_DEPLOYMENTS_ID.format(id=deployment_id)
        )
        assert rsp.status_code == 200

        dpl = rsp.json()
        if dpl["status"] == "finished":
            rsp = api_deployments.call(
                "GET", deployments.URL_DEPLOYMENTS_STATISTICS.format(id=deployment_id)
            )
            assert rsp.status_code == 200
            assert rsp.json()["failure"] == 0
            assert rsp.json()["success"] == dpl["device_count"]
            break
        elif datetime.now() > deadline:
            pytest.fail("timeout: Waiting for devices to update")
        else:
            time.sleep(1)


class TestClientCompatibilityBase:
    """
    This class contains compatibility tests implementation for assessing
    server compatibility with older clients.
    """

    def compatibility_test_impl(self, env):
        """
        The actual test implementation:
         - Accept devices
         - Verify devices patches inventory
         - Perform a noop rootfs update and verify the update was successful
        """
        gateway_addr = env.get_mender_gateway()
        api_useradmm = ApiClient(useradm.URL_MGMT, host=gateway_addr)
        api_devauthm = ApiClient(deviceauth.URL_MGMT, host=gateway_addr)
        api_inventory = ApiClient(inventory.URL_MGMT, host=gateway_addr)
        api_deployments = ApiClient(deployments.URL_MGMT, host=gateway_addr)

        rsp = api_useradmm.call(
            "POST", useradm.URL_LOGIN, auth=(env.user.name, env.user.pwd)
        )
        assert rsp.status_code == 200, "Failed to log in test user"
        api_token = rsp.text

        api_useradmm = api_useradmm.with_auth(api_token)
        api_devauthm = api_devauthm.with_auth(api_token)
        api_inventory = api_inventory.with_auth(api_token)
        api_deployments = api_deployments.with_auth(api_token)

        deadline = datetime.now() + TIMEOUT
        devices = []
        while True:
            rsp = api_devauthm.call(
                "GET", deviceauth.URL_MGMT_DEVICES, qs_params={"status": "pending"}
            )
            assert rsp.status_code == 200

            devices = rsp.json()
            assert len(devices) <= len(env.devices)

            if len(devices) == len(env.devices):
                break
            elif datetime.now() > deadline:
                pytest.fail("timeout waiting for devices to connect to server")
            else:
                time.sleep(1)

        # Accept all devices
        accept_devices(api_devauthm)

        # Check that inventory gets updated successfully
        assert_inventory_updated(api_inventory, len(devices))

        with NamedTemporaryFile(suffix="testcompat") as tf:

            cmd = f"single-file-artifact-gen -n {path.basename(tf.name)} -t qemux86-64 -t docker-client -o {tf.name} -d /tmp/test_file_compat tests/test_compat.py -- --no-default-software-version --no-default-clears-provides"
            subprocess.check_call(cmd, shell=True)

            rsp = api_deployments.call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS,
                files={
                    (
                        "artifact",
                        (tf.name, open(tf.name, "rb"), "application/octet-stream"),
                    ),
                },
            )

            assert rsp.status_code == 201

            rsp = api_deployments.call(
                "POST",
                deployments.URL_DEPLOYMENTS,
                body={
                    "artifact_name": f"{path.basename(tf.name)}",
                    "devices": [device["id"] for device in devices],
                    "name": "test-compat-deployment",
                },
            )
            assert rsp.status_code == 201

            deployment_id = rsp.headers.get("Location").split("/")[-1]
            assert_successful_deployment(api_deployments, deployment_id)


@pytest.mark.skipif(
    isK8S(), reason="not relevant in a staging or production environment"
)
class TestClientCompatibilityOpenSource(TestClientCompatibilityBase):
    @pytest.mark.parametrize(
        "version",
        [pytest.param(version, id=version) for version in COMPAT_MENDER_VERSIONS],
    )
    def test_compatibility(self, setup_os_compat, version):
        env = setup_os_compat(client_service=version)
        self.compatibility_test_impl(env)
        env.teardown()


@pytest.mark.skipif(
    isK8S(), reason="not relevant in a staging or production environment"
)
class TestClientCompatibilityEnterprise(TestClientCompatibilityBase):
    @pytest.mark.parametrize(
        "version",
        [pytest.param(version, id=version) for version in COMPAT_MENDER_VERSIONS],
    )
    def test_enterprise_compatibility(self, setup_ent_compat, version):
        env = setup_ent_compat(client_service=version)
        self.compatibility_test_impl(env)
        env.teardown()
