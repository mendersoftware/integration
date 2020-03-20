# Copyright 2020 Northern.tech AS
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
import json
import logging
import pytest
import random
import time

from testutils.api.client import ApiClient
from testutils.infra.cli import CliUseradm, CliDeviceauth, CliTenantadm
import testutils.api.deviceauth as deviceauth
import testutils.api.useradm as useradm
import testutils.api.inventory as inventory
import testutils.api.inventory_v2 as inventory_v2
import testutils.api.tenantadm as tenantadm
import testutils.util.crypto

from testutils.common import (
    User,
    Device,
    Authset,
    Tenant,
    mongo,
    clean_mongo,
    create_user,
    create_org,
    create_authset,
    get_device_by_id_data,
    change_authset_status,
)


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
    for t in ["tenant1", "tenant2"]:
        deviceauth_cli.migrate(t)
        useradm_cli.migrate(t)

    yield clean_mongo


@pytest.fixture(scope="function")
def user(clean_migrated_mongo):
    yield create_user("user-foo@acme.com", "correcthorse")


@pytest.fixture(scope="function")
def tenants_users(clean_migrated_mongo_mt):
    cli = CliTenantadm()
    api = ApiClient(tenantadm.URL_INTERNAL)

    names = ["tenant1", "tenant2"]
    tenants = []

    for n in names:
        username = "user@%s.com" % n
        password = "correcthorse"
        tenant = create_org(n, username, password)
        tenants.append(tenant)

    yield tenants


def rand_id_data():
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), "x") for i in range(6)])
    sn = "".join(["{}".format(random.randint(0x00, 0xFF)) for i in range(6)])

    return {"mac": mac, "sn": sn}


def make_pending_device(utoken, tenant_token=""):
    devauthm = ApiClient(deviceauth.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)

    id_data = rand_id_data()

    priv, pub = testutils.util.crypto.get_keypair_rsa()
    new_set = create_authset(
        devauthd, devauthm, id_data, pub, priv, utoken, tenant_token=tenant_token,
    )

    dev = Device(new_set.did, new_set.id_data, utoken, tenant_token)

    dev.authsets.append(new_set)

    dev.status = "pending"

    return dev


def make_accepted_device(utoken, devauthd, tenant_token=""):
    devauthm = ApiClient(deviceauth.URL_MGMT)

    dev = make_pending_device(utoken, tenant_token=tenant_token)
    aset_id = dev.authsets[0].id
    change_authset_status(devauthm, dev.id, aset_id, "accepted", utoken)

    aset = dev.authsets[0]
    aset.status = "accepted"

    # obtain auth token
    body, sighdr = deviceauth.auth_req(
        aset.id_data, aset.pubkey, aset.privkey, tenant_token
    )

    r = devauthd.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)

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
        devauthd = ApiClient(deviceauth.URL_DEVICES)
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
        devauthd = ApiClient(deviceauth.URL_DEVICES)
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
        devauthd = ApiClient(deviceauth.URL_DEVICES)
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
            # {"inventory": 3, "identity": 1+2, "system": 2} # +2 comes from the id_data see MEN-3637
            assert len(api_dev["attributes"]) == 8
            # new scopes: identity and system holding authset status and
            #             time-stamp values respectively

            for a in api_dev["attributes"]:
                if a["name"] == "mac" and a["scope"] == "inventory":
                    assert a["value"] == "mac-new-" + str(api_dev["id"])
                elif a["name"] == "sn" and a["scope"] == "inventory":
                    assert a["value"] == ""
                elif a["name"] == "new-empty" and a["scope"] == "inventory":
                    assert a["value"] == ""
                elif a["name"] == "status" and a["scope"] == "identity":
                    assert a["value"] in ["accepted", "pending"]
                elif a["scope"] != "inventory":
                    # Check that the value is present
                    assert a["value"] != ""
                else:
                    assert False, "unexpected attribute " + a["name"]

    def test_fail_no_attr_value(self, user):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth.URL_DEVICES)
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


class TestDeviceFilteringEnterprise:
    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger

    def is_subset(self, value, subset):
        if type(value) != type(subset):
            self.logger.error("type(%s) != type(%s)" % (value, subset))
            return False

        if isinstance(subset, list):
            for i, item in enumerate(subset):
                if not self.is_subset(value[i], item):
                    return False

        elif isinstance(subset, dict):
            for k, v in subset.items():
                if k not in value:
                    self.logger.error("%s not in %s" % (k, list(value.keys())))
                    return False
                elif not self.is_subset(value[k], v):
                    return False

        elif value != subset:
            self.logger.error("%s != %s" % (value, subset))
            return False

        return True

    def dict_to_inventoryattrs(self, d, scope=None):
        attr_list = []
        for key, value in d.items():
            attr = {"name": key, "value": value}
            if scope is not None:
                attr["scope"] = scope
            attr_list.append(attr)

        return attr_list

    def test_search_v2(self, tenants_users):
        NUM_DEVICES = 100

        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invd = ApiClient(inventory.URL_DEV)
        invm_v2 = ApiClient(inventory_v2.URL_MGMT)

        # Initialize devices and API tokens
        tenants = [t for t in tenants_users]
        users = [tenant.users[0] for tenant in tenants]
        inventories = [
            {"version": "v1.0", "grp1": "foo", "idx": 0},
            {"version": "v2.0", "grp1": "bar", "idx": 1},
            {"version": "v3.0", "grp1": "baz", "idx": 2},
            {"version": "v1.0", "grp2": "foo", "idx": 3},
            {"version": "v2.0", "grp2": "bar", "idx": 4},
            {"version": "v3.0", "grp2": "baz", "idx": 5},
            {"version": "v1.0", "grp3": "foo", "idx": 6},
            {"version": "v2.0", "grp3": "bar", "idx": 7},
            {"version": "v3.0", "grp3": "baz", "idx": 8},
        ]

        # Setup an identical inventory environment for both tenants.
        for tenant in tenants:
            tenant.devices = []
            for inv in inventories:
                user = tenant.users[0]
                utoken = useradmm.call(
                    "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
                ).text
                assert utoken != ""

                tenant.api_token = utoken
                device = make_accepted_device(
                    utoken, devauthd, tenant_token=tenant.tenant_token
                )
                tenant.devices.append(device)

                attrs = self.dict_to_inventoryattrs(inv)
                rsp = invd.with_auth(device.token).call(
                    "PATCH", inventory.URL_DEVICE_ATTRIBUTES, body=attrs
                )
                assert rsp.status_code == 200
                device.inventory = inv

        tenant = tenants[0]
        test_cases = [
            {
                "name": "Test $eq single match",
                "request": {
                    "filters": [
                        {
                            "type": "$eq",
                            "attribute": "idx",
                            "value": 1,
                            "scope": "inventory",
                        }
                    ],
                },
                "status_code": 200,
                "response": [
                    {
                        "id": str(tenants[0].devices[1].id),
                        "attributes": self.dict_to_inventoryattrs(
                            tenant.devices[1].inventory, scope="inventory"
                        ),
                    }
                ],
            },
            {
                "name": "Test $eq no-match",
                "request": {
                    "filters": [
                        {
                            "type": "$eq",
                            "attribute": "id_data",
                            "value": "illegal_data",
                            "scope": "inventory",
                        }
                    ],
                },
                "status_code": 200,
                "response": [],
            },
            {
                "name": "Test $lt -> $gte range-match",
                "request": {
                    "filters": [
                        {
                            "type": "$lt",
                            "attribute": "idx",
                            "value": 5,
                            "scope": "inventory",
                        },
                        {
                            "type": "$gte",
                            "attribute": "idx",
                            "value": 1,
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "asc",}
                    ],
                },
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in tenant.devices[1:5]
                ],
            },
            {
                "name": "Test $exists -> $in, descending sort",
                "request": {
                    "filters": [
                        {
                            "type": "$exists",
                            "attribute": "grp1",
                            "value": True,
                            "scope": "inventory",
                        },
                        {
                            "type": "$in",
                            "attribute": "version",
                            "value": ["v1.0", "v3.0"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc",}
                    ],
                },
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in sorted(
                        filter(
                            lambda dev: "grp1" in dev.inventory
                            and dev.inventory["version"] in ["v1.0", "v3.0"],
                            tenant.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            {
                "name": "Test $nin, sort by descending idx",
                "request": {
                    "filters": [
                        {
                            "type": "$nin",
                            "attribute": "version",
                            "value": ["v3.0"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc",},
                    ],
                },
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    # The following is just the python expression of the
                    # above operation.
                    for dev in sorted(
                        filter(
                            lambda dev: dev.inventory["version"] != "v3.0",
                            tenant.devices,
                        ),
                        key=lambda dev: json.dumps(dev.inventory["idx"]),
                        reverse=True,
                    )
                ],
            },
            {
                "name": "Error - missing type parameter",
                "request": {
                    "filters": [
                        {
                            "attribute": "version",
                            "value": ["v1.0"],
                            "scope": "inventory",
                        },
                    ],
                },
                "status_code": 400,
            },
            {
                "name": "Error - valid mongo query unsupported operation",
                "request": {
                    "filters": [
                        {
                            "type": "$type",
                            "attribute": "version",
                            "value": ["int", "string", "array"],
                            "scope": "inventory",
                        },
                    ],
                },
                "status_code": 400,
            },
        ]

        for test_case in test_cases:
            self.logger.info("Running test case: %s" % test_case["name"])
            rsp = invm_v2.with_auth(tenant.api_token).call(
                "POST", inventory_v2.URL_SEARCH, test_case["request"]
            )
            assert rsp.status_code == test_case["status_code"], (
                "Unexpected status code (%d) from /filters/search response: %s"
                % (rsp.status_code, rsp.text)
            )

            if rsp.status_code == 200 and "response" in test_case:
                body = rsp.json()
                if body is None:
                    body = []
                assert len(body) == len(test_case["response"]), (
                    "Unexpected number of results: %s != %s"
                    % (test_case["response"], body)
                )

                if len(body) > 0:
                    # There are no guarantee on the order the attributes
                    # are returned.
                    for dev in body:
                        dev["attributes"].sort(key=lambda d: d["name"])
                    for dev in test_case["response"]:
                        dev["attributes"].sort(key=lambda d: d["name"])

                    assert self.is_subset(body, test_case["response"]), (
                        "Unexpected result from search: %s not in response %s"
                        % (test_case["response"], body)
                    )
