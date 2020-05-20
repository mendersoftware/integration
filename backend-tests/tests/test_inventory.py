# Copyright 2019 Northern.tech AS
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
import pytest
import random
import time

from testutils.api.client import ApiClient
from testutils.common import mongo, clean_mongo
from testutils.infra.cli import CliUseradm, CliDeviceauth, CliTenantadm
import testutils.api.deviceauth as deviceauth_v1
import testutils.api.deviceauth_v2 as deviceauth_v2
import testutils.api.useradm as useradm
import testutils.api.inventory as inventory
import testutils.api.tenantadm as tenantadm
import testutils.util.crypto
from testutils.common import (
    User,
    Device,
    Authset,
    Tenant,
    create_user,
    create_org,
    create_authset,
    get_device_by_id_data,
    change_authset_status,
)


@pytest.yield_fixture(scope="function")
def clean_migrated_mongo(clean_mongo):
    deviceauth_cli = CliDeviceauth()
    useradm_cli = CliUseradm()

    deviceauth_cli.migrate()
    useradm_cli.migrate()

    yield clean_mongo


@pytest.yield_fixture(scope="function")
def clean_migrated_mongo_mt(clean_mongo):
    deviceauth_cli = CliDeviceauth()
    useradm_cli = CliUseradm()
    for t in ["tenant1", "tenant2"]:
        deviceauth_cli.migrate(t)
        useradm_cli.migrate(t)

    yield clean_mongo


@pytest.yield_fixture(scope="function")
def user(clean_migrated_mongo):
    yield create_user("user-foo@acme.com", "correcthorse")


@pytest.yield_fixture(scope="function")
def tenants_users(clean_migrated_mongo_mt):
    cli = CliTenantadm()
    api = ApiClient(tenantadm.URL_INTERNAL)

    names = ["tenant1", "tenant2"]
    tenants = []

    for n in names:
        username = "user@%s.com" % n
        password = "correcthorse"
        tenant = create_org(n, username, password)

    yield tenants


def rand_id_data():
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), "x") for i in range(6)])
    sn = "".join(["{}".format(random.randint(0x00, 0xFF)) for i in range(6)])

    return {"mac": mac, "sn": sn}


def make_pending_device(utoken, tenant_token=""):
    devauthm = ApiClient(deviceauth_v2.URL_MGMT)
    devauthd = ApiClient(deviceauth_v1.URL_DEVICES)

    id_data = rand_id_data()

    priv, pub = testutils.util.crypto.rsa_get_keypair()
    new_set = create_authset(
        devauthd, devauthm, id_data, pub, priv, utoken, tenant_token=tenant_token
    )

    dev = Device(new_set.did, new_set.id_data, utoken, tenant_token)

    dev.authsets.append(new_set)

    dev.status = "pending"

    return dev


def make_accepted_device(utoken, devauthd, tenant_token=""):
    devauthm = ApiClient(deviceauth_v2.URL_MGMT)

    dev = make_pending_device(utoken, tenant_token=tenant_token)
    aset_id = dev.authsets[0].id
    change_authset_status(devauthm, dev.id, aset_id, "accepted", utoken)

    aset = dev.authsets[0]
    aset.status = "accepted"

    # obtain auth token
    body, sighdr = deviceauth_v1.auth_req(
        aset.id_data, aset.pubkey, aset.privkey, tenant_token
    )

    r = devauthd.call("POST", deviceauth_v1.URL_AUTH_REQS, body, headers=sighdr)

    assert r.status_code == 200
    dev.token = r.text

    dev.status = "accepted"

    return dev


def make_accepted_devices(utoken, devauthd, num_devices=1, tenant_token=""):
    """ Create accepted devices.
        returns list of Device objects."""
    devices = []

    # some 'accepted' devices, single authset
    for _ in range(num_devices):
        dev = make_accepted_device(utoken, devauthd, tenant_token=tenant_token)
        devices.append(dev)

    return devices


class TestGetDevicesBase:
    def do_test_get_devices_ok(self, user, tenant_token=""):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 40, tenant_token)

        # wait for devices to be provisioned
        time.sleep(3)

        r = invm.with_auth(utoken).call(
            "GET", inventory.URL_DEVICES, qs_params={"per_page": 100}
        )
        assert r.status_code == 200
        api_devs = r.json()
        assert len(api_devs) == 40

    def do_test_filter_devices_ok(self, user, tenant_token=""):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 40, tenant_token)

        # wait for devices to be provisioned
        time.sleep(3)

        r = invm.with_auth(utoken).call(
            "GET", inventory.URL_DEVICES, qs_params={"per_page": 100}
        )
        assert r.status_code == 200
        api_devs = r.json()
        assert len(api_devs) == 40

        # upload inventory attributes
        for i, d in enumerate(devs):
            payload = [{"name": "mac", "value": "de:ad:be:ef:06:" + str(i)}]
            r = invd.with_auth(d.token).call(
                "PATCH", inventory.URL_DEVICE_ATTRIBUTES, payload
            )
            assert r.status_code == 200

        # get device with exact mac value
        qs_params = {}
        qs_params["per_page"] = 100
        qs_params["mac"] = "de:ad:be:ef:06:7"
        r = invm.with_auth(utoken).call(
            "GET", inventory.URL_DEVICES, qs_params=qs_params
        )
        assert r.status_code == 200
        api_devs = r.json()
        assert len(api_devs) == 1


class TestGetDevices(TestGetDevicesBase):
    def test_get_devices_ok(self, user):
        self.do_test_get_devices_ok(user)

    def test_filter_devices_ok(self, user):
        self.do_test_filter_devices_ok(user)


class TestGetDevicesEnterprise(TestGetDevicesBase):
    def test_get_devices_ok(self, tenants_users):
        for t in tenants_users:
            self.do_test_get_devices_ok(t.users[0], tenant_token=t.tenant_token)

    def test_filter_devices_ok(self, tenants_users):
        for t in tenants_users:
            self.do_test_filter_devices_ok(t.users[0], tenant_token=t.tenant_token)


class TestDevicePatchAttributes:
    def test_ok(self, user):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 3)

        # wait for devices to be provisioned
        time.sleep(3)

        for i, d in enumerate(devs):
            payload = [
                {"name": "mac", "value": "mac-new-" + str(d.id)},
                {
                    # empty value for existing
                    "name": "sn",
                    "value": "",
                },
                {
                    # empty value for new
                    "name": "new-empty",
                    "value": "",
                },
            ]
            r = invd.with_auth(d.token).call(
                "PATCH", inventory.URL_DEVICE_ATTRIBUTES, payload
            )
            assert r.status_code == 200

        for d in devs:
            r = invm.with_auth(utoken).call(
                "GET", inventory.URL_DEVICE, path_params={"id": d.id}
            )
            assert r.status_code == 200

            api_dev = r.json()
            # Expected inventory count per scope:
            # {"inventory": 3, "identity": 1, "system": 2}
            assert len(api_dev["attributes"]) == 6
            # new scopes: identity and system holding authset status and
            #             time-stamp values respectively

            for a in api_dev["attributes"]:
                if a["name"] == "mac":
                    assert a["value"] == "mac-new-" + str(api_dev["id"])
                elif a["name"] == "sn":
                    assert a["value"] == ""
                elif a["name"] == "new-empty":
                    assert a["value"] == ""
                elif a["name"] == "status":
                    assert a["value"] in ["accepted", "pending"]
                elif a["scope"] != "inventory":
                    # Check that the value is present
                    assert a["value"] != ""
                else:
                    assert False, "unexpected attribute " + a["name"]

    def test_fail_no_attr_value(self, user):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 1)

        # wait for devices to be provisioned
        time.sleep(3)

        for i, d in enumerate(devs):
            payload = [{"name": "mac"}]
            r = invd.with_auth(d.token).call(
                "PATCH", inventory.URL_DEVICE_ATTRIBUTES, payload
            )
            assert r.status_code == 400
