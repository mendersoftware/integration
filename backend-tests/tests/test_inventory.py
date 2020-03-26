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
import json
import logging
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
import testutils.api.inventory_v2 as inventory_v2
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
    devauthm = ApiClient(deviceauth_v2.URL_MGMT)
    devauthd = ApiClient(deviceauth_v1.URL_DEVICES)

    id_data = rand_id_data()

    priv, pub = testutils.util.crypto.rsa_get_keypair()
    new_set = create_authset(
        devauthd, devauthm, id_data, pub, priv, utoken, tenant_token=tenant_token,
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
            assert len(api_dev["attributes"]) == 3

            for a in api_dev["attributes"]:
                if a["name"] == "mac":
                    assert a["value"] == "mac-new-" + str(api_dev["id"])
                elif a["name"] == "sn":
                    assert a["value"] == ""
                elif a["name"] == "new-empty":
                    assert a["value"] == ""
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

    def test_search_v2(self, clean_mongo):
        NUM_DEVICES = 100

        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invd = ApiClient(inventory.URL_DEV)
        invm_v2 = ApiClient(inventory_v2.URL_MGMT)

        tenants = []
        tenants.append(
            create_org("BobThePro", "bob@pro.org", "password", plan="professional")
        )
        tenants.append(
            create_org("BobTheOpenSource", "bob@open.src", "secretpwd", plan="os")
        )

        # Initialize devices and API tokens
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
                "tenant": tenants[0],
                "status_code": 200,
                "response": [
                    {
                        "id": str(tenants[0].devices[1].id),
                        "attributes": self.dict_to_inventoryattrs(
                            tenants[0].devices[1].inventory, scope="inventory"
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
                "tenant": tenants[0],
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
                        {"attribute": "idx", "scope": "inventory", "order": "asc"}
                    ],
                },
                "tenant": tenants[0],
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in tenants[0].devices[1:5]
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
                        {"attribute": "idx", "scope": "inventory", "order": "desc"}
                    ],
                },
                "tenant": tenants[0],
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
                            tenants[0].devices,
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
                            "value": ["v3.0", "v2.0"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc"},
                    ],
                },
                "tenant": tenants[0],
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
                            lambda dev: dev.inventory["version"]
                            not in ["v3.0", "v2.0"],
                            tenants[0].devices,
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
                "tenant": tenants[0],
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
                "tenant": tenants[0],
                "status_code": 400,
            },
            {
                "name": "Error - not a pro",
                "request": {
                    "filters": [
                        {
                            "type": "$eq",
                            "attribute": "idx",
                            "value": 0,
                            "scope": "inventory",
                        },
                    ],
                },
                "tenant": tenants[1],
                "status_code": 403,
            },
        ]

        for test_case in test_cases:
            self.logger.info("Running test case: %s" % test_case["name"])
            rsp = invm_v2.with_auth(test_case["tenant"].api_token).call(
                "POST", inventory_v2.URL_SEARCH, test_case["request"]
            )
            assert rsp.status_code == test_case["status_code"], (
                "Unexpected status code (%d) from /filters/search response: %s"
                % (rsp.status_code, rsp.text)
            )

            if rsp.status_code == 200 and "response" in test_case:
                body = rsp.json()
                if body is None:
                    assert int(rsp.headers.get("X-Total-Count", -1)) == 0
                    body = []
                assert len(body) == len(test_case["response"]), (
                    "Unexpected number of results: %s != %s"
                    % (test_case["response"], body)
                )

                if len(body) > 0:
                    assert int(rsp.headers.get("X-Total-Count", -1)) == len(body)
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

    def test_search_v2_internal(self, clean_mongo):
        NUM_DEVICES = 100

        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invd = ApiClient(inventory.URL_DEV)
        invm_v2 = ApiClient(inventory_v2.URL_INTERNAL)

        # Initialize devices and API tokens
        tenants = []
        tenants.append(
            create_org("BobThePro", "bob@pro.org", "password", "professional")
        )
        tenants.append(
            create_org("BobTheEnterprise", "bob@ent.org", "password", "enterprise")
        )
        tenants.append(create_org("BobTheOpenSource", "bob@open.src", "password", "os"))
        inventories = [
            {"tenant": tenants[0], "version": "v1.0", "grp1": "foo", "idx": 0},
            {"tenant": tenants[0], "version": "v2.0", "grp1": "bar", "idx": 1},
            {"tenant": tenants[0], "version": "v3.0", "grp1": "baz", "idx": 2},
            {"tenant": tenants[0], "version": "v1.0", "grp2": "foo", "idx": 3},
            {"tenant": tenants[0], "version": "v2.0", "grp2": "bar", "idx": 4},
            {"tenant": tenants[0], "version": "v3.0", "grp2": "baz", "idx": 5},
            {"tenant": tenants[0], "version": "v1.0", "grp3": "foo", "idx": 6},
            {"tenant": tenants[0], "version": "v2.0", "grp3": "bar", "idx": 7},
            {"tenant": tenants[0], "version": "v3.0", "grp3": "baz", "idx": 8},
            {"tenant": tenants[1], "version": "v4.1", "idx": 0},
            {"tenant": tenants[1], "version": "v4.2", "idx": 1},
            {"tenant": tenants[1], "version": "v4.3", "idx": 2},
            {"tenant": tenants[1], "version": "v5.0", "idx": 3},
            {"tenant": tenants[1], "version": "v4.1", "idx": 4},
            {"tenant": tenants[1], "version": "v3.9", "idx": 5},
            {"tenant": tenants[1], "version": "v4.2", "idx": 6},
            {"tenant": tenants[1], "version": "v4.3", "idx": 7},
            {"tenant": tenants[1], "version": "v4.0", "idx": 8},
            {"tenant": tenants[2], "version": "v1.0", "idx": 0},
            {"tenant": tenants[2], "version": "v1.0", "idx": 1},
            {"tenant": tenants[2], "version": "v1.0", "idx": 2},
        ]

        # Setup an identical inventory environment for both tenants.
        for inv in inventories:
            tenant = inv.pop("tenant")
            user = tenant.users[0]
            utoken = useradmm.call(
                "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
            ).text
            assert utoken != ""

            tenant.api_token = utoken
            device = make_accepted_device(
                utoken, devauthd, tenant_token=tenant.tenant_token
            )
            try:
                tenant.devices.append(device)
            except AttributeError:
                tenant.devices = []
                tenant.devices.append(device)

            attrs = self.dict_to_inventoryattrs(inv)
            rsp = invd.with_auth(device.token).call(
                "PATCH", inventory.URL_DEVICE_ATTRIBUTES, body=attrs
            )
            assert rsp.status_code == 200
            device.inventory = inv

        test_cases = [
            {
                "name": "Test $eq single match",
                "request": {
                    "filters": [
                        {
                            "type": "$eq",
                            "attribute": "idx",
                            "value": 0,
                            "scope": "inventory",
                        }
                    ],
                },
                "tenant_id": tenants[0].id,
                "status_code": 200,
                "response": [
                    {
                        "id": str(tenants[0].devices[0].id),
                        "attributes": self.dict_to_inventoryattrs(
                            tenants[0].devices[0].inventory, scope="inventory"
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
                "tenant_id": tenants[0].id,
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
                "tenant_id": tenants[1].id,
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in tenants[1].devices[1:5]
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
                "tenant_id": tenants[0].id,
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
                            tenants[0].devices,
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
                            "value": ["v4.2", "v4.1"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc"},
                    ],
                },
                "tenant_id": tenants[1].id,
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
                            lambda dev: dev.inventory["version"]
                            not in ["v4.2", "v4.1"],
                            tenants[1].devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            {
                "name": "Test $ne open-source",
                "request": {
                    "filters": [
                        {
                            "type": "$ne",
                            "attribute": "idx",
                            "value": 0,
                            "scope": "inventory",
                        }
                    ],
                },
                "tenant_id": tenants[2].id,
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in tenants[2].devices[1:]
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
                "tenant_id": tenants[0].id,
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
                "tenant_id": tenants[1].id,
                "status_code": 400,
            },
        ]

        for test_case in test_cases:
            self.logger.info("Running test case: %s" % test_case["name"])
            rsp = invm_v2.with_auth(tenant.api_token).call(
                "POST",
                inventory_v2.URL_SEARCH_INTERNAL.format(
                    tenant_id=test_case["tenant_id"]
                ),
                test_case["request"],
            )
            assert rsp.status_code == test_case["status_code"], (
                "Unexpected status code (%d) from %s response: %s"
                % (rsp.status_code, rsp.url, rsp.text)
            )

            if rsp.status_code == 200 and "response" in test_case:
                body = rsp.json()
                if body is None:
                    assert int(rsp.headers.get("X-Total-Count", -1)) == 0
                    body = []
                assert len(body) == len(test_case["response"]), (
                    "Unexpected number of results: %s != %s"
                    % (test_case["response"], body)
                )

                if len(body) > 0:
                    assert int(rsp.headers.get("X-Total-Count", -1)) == len(body)
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

    def test_saved_filters(self, clean_mongo):
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        usradmm = ApiClient(useradm.URL_MGMT)
        invm_v2 = ApiClient(inventory_v2.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # Setup tenants
        tenants = []
        tenants.append(
            create_org(
                "BobTheEnterprise", "bob@enterprise.org", "password", plan="enterprise"
            )
        )
        tenants.append(
            create_org("BobThePro", "bob@pro.org", "password", plan="professional")
        )
        tenants.append(
            create_org("BobTheOpenSource", "bob@open.src", "password", plan="os")
        )
        tenants[0].dev_inventories = [
            {"mndr": "v2.0", "py3": "3.3", "py2": "2.7", "idx": 0},
            {"mndr": "v2.0", "py3": "3.5", "py2": "2.7", "idx": 1},
            {"mndr": "v2.1", "py2": "2.7", "idx": 2},
            {"mndr": "v2.1", "py2": "2.7", "idx": 3},
            {"mndr": "v2.1", "py3": "3.5", "py2": "2.7", "idx": 4},
            {"mndr": "v2.2", "py3": "3.6", "py2": "2.7", "idx": 5},
            {"mndr": "v2.2", "py3": "3.6", "idx": 6},
            {"mndr": "v2.2", "py3": "3.7", "idx": 7},
            {"mndr": "v2.2", "py3": "3.7", "idx": 8},
            {"mndr": "v2.2", "py3": "3.8", "idx": 9},
        ]
        tenants[1].dev_inventories = [{"idx": 0}, {"idx": 1}, {"idx": 2}]
        tenants[2].dev_inventories = [{"idx": 0}, {"idx": 1}, {"idx": 2}]

        for tenant in tenants:
            rsp = usradmm.call(
                "POST",
                useradm.URL_LOGIN,
                auth=(tenant.users[0].name, tenant.users[0].pwd),
            )
            assert rsp.status_code == 200
            tenant.api_token = rsp.text
            for inv in tenant.dev_inventories:
                device = make_accepted_device(
                    tenant.api_token, devauthd, tenant_token=tenant.tenant_token
                )

                rsp = invd.with_auth(device.token).call(
                    "PATCH",
                    inventory.URL_DEVICE_ATTRIBUTES,
                    body=self.dict_to_inventoryattrs(inv),
                )
                assert rsp.status_code == 200
                device.inventory = inv
                try:
                    tenant.devices.append(device)
                except AttributeError:
                    tenant.devices = []
                    tenant.devices.append(device)

        test_cases = [
            {
                "name": "Simple $eq filters",
                "tenant": tenants[0],
                "request": {
                    "name": "test1",
                    "terms": [
                        {
                            "type": "$eq",
                            "scope": "inventory",
                            "attribute": "mndr",
                            "value": "v2.2",
                        }
                    ],
                },
                "status_codes": [201, 200, 200, 200],
                "result": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(dev.inventory),
                    }
                    for dev in filter(
                        lambda dev: dev.inventory["mndr"] == "v2.2", tenants[0].devices
                    )
                ],
            },
            {
                "name": "Compound filter: $in -> $exists -> $nin",
                "tenant": tenants[0],
                "request": {
                    "name": "test2",
                    "terms": [
                        {
                            "type": "$in",
                            "scope": "inventory",
                            "attribute": "mndr",
                            "value": ["v2.0", "v2.1"],
                        },
                        {
                            "type": "$exists",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": True,
                        },
                        {
                            "type": "$nin",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": ["3.5", "3.6"],
                        },
                    ],
                },
                "status_codes": [201, 200, 200, 200],
                "result": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(dev.inventory),
                    }
                    for dev in filter(
                        lambda dev: dev.inventory["mndr"] in ["v2.0", "v2.1"]
                        and "py3" in dev.inventory
                        and dev.inventory["py3"] not in ["3.5", "3.6"],
                        tenants[0].devices,
                    )
                ],
            },
            {
                "name": "Compound filter: $ne -> $lt -> $gte -> $exists",
                "tenant": tenants[0],
                "request": {
                    "name": "test3",
                    "terms": [
                        {
                            "type": "$ne",
                            "scope": "inventory",
                            "attribute": "mndr",
                            "value": "v2.0",
                        },
                        {
                            "type": "$lte",
                            "scope": "inventory",
                            "attribute": "idx",
                            "value": 8,
                        },
                        {
                            "type": "$gt",
                            "scope": "inventory",
                            "attribute": "idx",
                            "value": 1,
                        },
                        {
                            "type": "$exists",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": False,
                        },
                    ],
                },
                "status_codes": [201, 200, 200, 200],
                "result": [
                    {
                        "id": dev.id,
                        "attributes": self.dict_to_inventoryattrs(dev.inventory),
                    }
                    for dev in filter(
                        lambda dev: "py3" not in dev.inventory
                        and 2 <= dev.inventory["idx"] < 8
                        and dev.inventory["mndr"] != "v2.0",
                        tenants[0].devices,
                    )
                ],
            },
            {
                "name": "Error filter already exists",
                "tenant": tenants[0],
                "request": {
                    "name": "test1",
                    "terms": [
                        {
                            "type": "$ne",
                            "scope": "inventory",
                            "attribute": "mndr",
                            "value": "v2.2",
                        }
                    ],
                },
                "status_codes": [409, 200, 404, 404],
            },
            {
                "name": "Error not allowed for professional accounts",
                "tenant": tenants[1],
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {
                            "type": "$eq",
                            "scope": "inventory",
                            "attribute": "mndr",
                            "value": "v2.0",
                        }
                    ],
                },
                "status_codes": [403, 403, 403, 403],
            },
            {
                "name": "Error not allowed for open-source accounts",
                "tenant": tenants[2],
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {
                            "type": "$eq",
                            "scope": "inventory",
                            "attribute": "mndr",
                            "value": "v2.0",
                        }
                    ],
                },
                "status_codes": [403, 403, 403, 403],
            },
            {
                "name": "Error empty value",
                "tenant": tenants[0],
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {"type": "$eq", "scope": "inventory", "attribute": "mndr"}
                    ],
                },
                "status_codes": [400, 200, 404, 404],
            },
            {
                "name": "Error invalid filter type",
                "tenant": tenants[0],
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {
                            "type": "$type",
                            "scope": "inventory",
                            "attribute": "mndr",
                            "value": ["string", "array"],
                        }
                    ],
                },
                "status_codes": [400, 200, 404, 404],
            },
        ]

        for test_case in test_cases:
            self.logger.info("Running test: %s" % test_case["name"])
            # Test POST /filters endpoint
            rsp = invm_v2.with_auth(test_case["tenant"].api_token).call(
                "POST", inventory_v2.URL_SAVED_FILTERS, body=test_case["request"]
            )
            assert rsp.status_code == test_case["status_codes"][0], (
                "Unexpected status code (%d) on POST %s request; response: %s"
                % (rsp.status_code, rsp.url, rsp.text)
            )
            filter_url = rsp.headers.get("Location", "foobar")
            filter_id = filter_url.split("/")[-1]

            # Test GET /filters endpoint
            rsp = invm_v2.with_auth(test_case["tenant"].api_token).call(
                "GET",
                inventory_v2.URL_SAVED_FILTERS,
                qs_params={"per_page": len(test_cases)},
            )
            assert rsp.status_code == test_case["status_codes"][1]
            if test_case["status_codes"][0] == 201:
                # Check that newly posted filter is present in the result
                found = False
                for fltr in rsp.json():
                    if fltr["name"] == test_case["request"]["name"]:
                        found = True
                        break
                assert found, "GET %s did not return saved filter" % (
                    inventory_v2.URL_SAVED_FILTERS
                )

            # Test GET /filter/{id} endpoint
            rsp = invm_v2.with_auth(test_case["tenant"].api_token).call(
                "GET", inventory_v2.URL_SAVED_FILTER.format(id=filter_id)
            )
            assert rsp.status_code == test_case["status_codes"][2]

            # Test GET /filter/{id}/search endpoint
            rsp = invm_v2.with_auth(test_case["tenant"].api_token).call(
                "GET", inventory_v2.URL_SAVED_FILTER_SEARCH.format(id=filter_id),
            )

            assert rsp.status_code == test_case["status_codes"][3]
            if test_case["status_codes"][3] == 200:
                # There are no ordering guarantee on the response,
                # so let's make it so.
                match = rsp.json()
                match.sort(key=lambda m: m["id"])
                for dev in match:
                    dev["attributes"].sort(key=lambda attr: attr["name"])
                test_case["result"].sort(key=lambda m: m["id"])
                for dev in test_case["result"]:
                    dev["attributes"].sort(key=lambda attr: attr["name"])

                assert self.is_subset(match, test_case["result"]), (
                    "Unexpected results from search; expected: %s, found: %s"
                    % (test_case["result"], match)
                )

        # Final test case: delete all filters
        rsp = invm_v2.with_auth(tenants[0].api_token).call(
            "GET", inventory_v2.URL_SAVED_FILTERS
        )
        assert rsp.status_code == 200
        for fltr in rsp.json():
            rsp = invm_v2.with_auth(tenants[0].api_token).call(
                "DELETE", inventory_v2.URL_SAVED_FILTER.format(id=fltr["id"])
            )
            assert rsp.status_code == 204, (
                "Unexpected status code (%d) returned on DELETE %s. Response: %s"
                % (rsp.status_code, rsp.url, rsp.text)
            )
