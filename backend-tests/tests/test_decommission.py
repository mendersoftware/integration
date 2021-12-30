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

import time
import logging
import pytest
import uuid

from testutils.api.client import ApiClient
import testutils.api.useradm as useradm
import testutils.api.deviceauth as deviceauth
import testutils.api.deployments as deployments
import testutils.api.inventory as inventory
from testutils.infra.cli import CliTenantadm, CliUseradm, CliDeviceauth
from testutils.common import (
    Device,
    mongo,
    clean_mongo,
    create_org,
    create_random_authset,
    change_authset_status,
    create_user,
)

logging.basicConfig(format="%(asctime)s %(message)s")
logger = logging.getLogger("test_decomission")
logger.setLevel(logging.INFO)


def isK8Smock():
    return True


@pytest.fixture(scope="function")
def clean_migrated_mongo(clean_mongo):
    deviceauth_cli = CliDeviceauth()
    useradm_cli = CliUseradm()

    deviceauth_cli.migrate()
    useradm_cli.migrate()

    yield clean_mongo


@pytest.fixture(scope="function")
def clean_migrated_mongo_mt(clean_mongo):
    deviceauth_cli = CliDeviceauth()
    useradm_cli = CliUseradm()
    tenantadm_cli = CliTenantadm()
    for t in ["tenant1", "tenant2"]:
        deviceauth_cli.migrate(t)
        useradm_cli.migrate(t)
        tenantadm_cli.migrate()

    yield clean_mongo


@pytest.fixture(scope="function")
def user(clean_migrated_mongo):
    yield create_user("user-foo@acme.com", "correcthorse")


@pytest.fixture(scope="function")
def devices(clean_migrated_mongo, user):
    useradmm = ApiClient(useradm.URL_MGMT)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)

    r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert r.status_code == 200
    utoken = r.text

    devices = []

    for _ in range(2):
        aset = create_random_authset(devauthd, devauthm, utoken)
        dev = Device(aset.did, aset.id_data, aset.pubkey)
        dev.authsets.append(aset)
        devices.append(dev)

    yield devices


@pytest.fixture(scope="function")
def tenants(clean_migrated_mongo_mt):
    tenants = []

    for n in range(2):
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenants.append(create_org(tenant, username, password))

    yield tenants


@pytest.fixture(scope="function")
def tenants_users_devices(tenants, clean_migrated_mongo_mt):
    useradmm = ApiClient(useradm.URL_MGMT)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)
    for t in tenants:
        user = t.users[0]
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        for _ in range(2):
            aset = create_random_authset(devauthd, devauthm, utoken, t.tenant_token)
            dev = Device(aset.did, aset.id_data, aset.pubkey, t.tenant_token)
            dev.authsets.append(aset)
            t.devices.append(dev)

    yield tenants


class TestDeviceDecomissioningBase:
    def do_test_ok(self, user, device, tenant_token=None):
        devauthd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        useradmm = ApiClient(useradm.URL_MGMT)
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        inventoryd = ApiClient(inventory.URL_DEV)
        inventorym = ApiClient(inventory.URL_MGMT)

        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        aset = device.authsets[0]
        change_authset_status(devauthm, aset.did, aset.id, "accepted", utoken)

        # request auth
        body, sighdr = deviceauth.auth_req(
            aset.id_data, aset.pubkey, aset.privkey, tenant_token
        )

        r = devauthd.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)
        assert r.status_code == 200
        dtoken = r.text

        # wait for the device provisioning workflow to do its job
        timeout = time.time() + 60
        while time.time() < timeout:
            r = inventorym.with_auth(utoken).call(
                "GET", inventory.URL_DEVICE, path_params={"id": aset.did}
            )
            if r.status_code == 200:
                break
            else:
                logger.debug("waiting for the device to be added to inventory...")
                time.sleep(1)
        else:
            assert False, "device not added to the inventory"

        # check if the device can access API by patching device inventory
        payload = [{"name": "mac", "value": "foo"}]
        r = inventoryd.with_auth(dtoken).call(
            "PATCH", inventory.URL_DEVICE_ATTRIBUTES, payload
        )
        assert r.status_code == 200

        # decommission
        r = devauthm.with_auth(utoken).call(
            "DELETE", deviceauth.URL_DEVICE.format(id=aset.did)
        )

        # check device is rejected
        r = deploymentsd.with_auth(dtoken).call(
            "GET",
            deployments.URL_NEXT,
            qs_params={"device_type": "foo", "artifact_name": "bar"},
        )
        assert r.status_code == 401

        # check device gone from inventory
        # this may take some time because it's done as an async job (workflow)
        timeout = time.time() + (60 * 3)
        while time.time() < timeout:
            r = inventorym.with_auth(utoken).call(
                "GET", inventory.URL_DEVICE, path_params={"id": aset.did}
            )
            if r.status_code == 404:
                break
            else:
                logger.debug("waiting for the device to be removed from inventory...")
                time.sleep(1)
        else:
            assert False, "device not removed from the inventory"

        # check device gone from deviceauth
        timeout = time.time() + 60
        while time.time() < timeout:
            r = devauthm.with_auth(utoken).call(
                "GET", deviceauth.URL_DEVICE.format(id=aset.did)
            )
            if r.status_code == 404:
                break
            else:
                logger.debug("waiting for the device to be removed from deviceauth...")
                time.sleep(1)
        else:
            assert False, "device not removed from the deviceauth"


class TestDeviceDecomissioning(TestDeviceDecomissioningBase):
    def test_ok(self, user, devices):
        self.do_test_ok(user, devices[0])


@pytest.mark.skipif(
    isK8Smock(), reason="not possible to test in a staging or production environment",
)
class TestDeviceDecomissioningEnterprise(TestDeviceDecomissioningBase):
    def test_ok(self, tenants_users_devices):
        t = tenants_users_devices[0]
        self.do_test_ok(
            user=t.users[0], device=t.devices[0], tenant_token=t.tenant_token
        )

        t1 = tenants_users_devices[1]
        self.verify_devices_unmodified(t1.users[0], t1.devices)

    def verify_devices_unmodified(self, user, in_devices):
        devauthm = ApiClient(deviceauth.URL_MGMT)
        useradmm = ApiClient(useradm.URL_MGMT)

        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200

        utoken = r.text

        r = devauthm.with_auth(utoken).call("GET", deviceauth.URL_MGMT_DEVICES)
        assert r.status_code == 200
        api_devs = r.json()

        assert len(api_devs) == len(in_devices)
        for ad in api_devs:
            assert ad["status"] == "pending"
