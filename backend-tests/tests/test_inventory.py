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
    mongo_cleanup,
    create_user,
    create_org,
    create_authset,
    get_device_by_id_data,
    change_authset_status,
    make_accepted_device,
    make_accepted_devices,
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
    names = ["tenant1", "tenant2"]
    tenants = []

    for n in names:
        username = "user@%s.com" % n
        password = "correcthorse"
        tenant = create_org(n, username, password)
        tenants.append(tenant)

    yield tenants


class TestGetDevicesBase:
    def do_test_get_devices_ok(self, user, tenant_token=""):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(devauthd, devauthm, utoken, tenant_token, 40)

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
        devauthm = ApiClient(deviceauth.URL_MGMT)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(devauthd, devauthm, utoken, tenant_token, 40)

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
        devauthm = ApiClient(deviceauth.URL_MGMT)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(devauthd, devauthm, utoken, "", 3)

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
        devauthm = ApiClient(deviceauth.URL_MGMT)
        invm = ApiClient(inventory.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(devauthd, devauthm, utoken, "", 1)

        # wait for devices to be provisioned
        time.sleep(3)

        for i, d in enumerate(devs):
            payload = [{"name": "mac"}]
            r = invd.with_auth(d.token).call(
                "PATCH", inventory.URL_DEVICE_ATTRIBUTES, payload
            )
            assert r.status_code == 400


def dict_to_inventoryattrs(d, scope="inventory"):
    attr_list = []
    for key, value in d.items():
        attr = {"name": key, "value": value}
        if scope is not None:
            attr["scope"] = scope
        attr_list.append(attr)

    return attr_list


class TestDeviceFilteringEnterprise:
    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger

    def test_search_v2(self, tenants_users):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)
        invm_v2 = ApiClient(inventory_v2.URL_MGMT)

        # Initialize devices and API tokens
        users = [tenant.users[0] for tenant in tenants_users]
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

        tenant = tenants_users[0]
        tenant.devices = []
        for inv in inventories:
            user = tenant.users[0]
            utoken = useradmm.call(
                "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
            ).text
            assert utoken != ""

            tenant.api_token = utoken
            device = make_accepted_device(
                devauthd, devauthm, utoken, tenant_token=tenant.tenant_token
            )
            tenant.devices.append(device)

            attrs = dict_to_inventoryattrs(inv)
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
                "status_code": 200,
                "response": [
                    {
                        "id": str(tenant.devices[1].id),
                        "attributes": dict_to_inventoryattrs(
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
                        "attributes": dict_to_inventoryattrs(
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
                        "attributes": dict_to_inventoryattrs(
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
                        "attributes": dict_to_inventoryattrs(
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
                    for dev in test_case["response"]:
                        found = False
                        for api_dev in body:
                            if dev["id"] == api_dev["id"]:
                                assert_device_attributes(dev, api_dev)
                                found = True
                        assert found, "Missing device with id: %s" % dev["id"]

    def test_search_v2_internal(self, clean_mongo):
        """
        Tests the internal v2/{tenant_id}/filters/search endpoint.
        This test along with the former covers all allowed operation
        types.
        """

        useradmm = ApiClient(useradm.URL_MGMT)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        devauthd = ApiClient(deviceauth.URL_DEVICES)
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
                devauthd, devauthm, utoken, tenant_token=tenant.tenant_token
            )
            try:
                tenant.devices.append(device)
            except AttributeError:
                tenant.devices = []
                tenant.devices.append(device)

            attrs = dict_to_inventoryattrs(inv)
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
                        "attributes": dict_to_inventoryattrs(
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
                        "attributes": dict_to_inventoryattrs(
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
                        "attributes": dict_to_inventoryattrs(
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
                        "attributes": dict_to_inventoryattrs(
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
                        "attributes": dict_to_inventoryattrs(
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
                assert len(body) == len(test_case["response"]), (
                    "Unexpected number of results: %s != %s"
                    % (test_case["response"], body)
                )

                if len(body) > 0:
                    for dev in test_case["response"]:
                        found = False
                        for api_dev in body:
                            if dev["id"] == api_dev["id"]:
                                assert_device_attributes(dev, api_dev)
                                found = True
                        assert found, "Missing device with id: %s" % dev["id"]

    def test_saved_filters(self, clean_mongo):
        """
        Test saved filters covers saving new filters, getting all
        filters, getting filter by id, executing filter and deleting
        filters.
        """
        devauthd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
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
                    devauthd,
                    devauthm,
                    tenant.api_token,
                    tenant_token=tenant.tenant_token,
                )

                rsp = invd.with_auth(device.token).call(
                    "PATCH",
                    inventory.URL_DEVICE_ATTRIBUTES,
                    body=dict_to_inventoryattrs(inv),
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
                    {"id": dev.id, "attributes": dict_to_inventoryattrs(dev.inventory),}
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
                    {"id": dev.id, "attributes": dict_to_inventoryattrs(dev.inventory),}
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
                    {"id": dev.id, "attributes": dict_to_inventoryattrs(dev.inventory),}
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
                match = rsp.json()
                for dev in test_case["result"]:
                    found = False
                    for api_dev in match:
                        if dev["id"] == api_dev["id"]:
                            assert_device_attributes(dev, api_dev)
                            found = True
                    assert found, "Missing device with id: %s" % dev["id"]

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

    def test_saved_filters_dynamic(self, clean_mongo, mongo):
        """
        Check that the saved filters return the correct set of
        devices when the inventory changes dynamically. That is,
        when devices modify their inventory or get removed entirely.
        """

        devauthd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        usradmm = ApiClient(useradm.URL_MGMT)
        invm_v2 = ApiClient(inventory_v2.URL_MGMT)
        invd = ApiClient(inventory.URL_DEV)

        # Initial device inventory setup
        inventories = [
            {"deb": "squeeze", "py3": 3.3, "py2": 2.7, "idx": 0},
            {"deb": "squeeze", "py3": 3.5, "py2": 2.7, "idx": 1},
            {"deb": "wheezy", "py2": 2.7, "idx": 2},
            {"deb": "wheezy", "py2": 2.7, "idx": 3},
            {"deb": "wheezy", "py3": 3.5, "py2": 2.7, "idx": 4},
            {"deb": "wheezy", "py3": 3.6, "py2": 2.7, "idx": 5},
            {"deb": "wheezy", "py3": 3.6, "idx": 6},
            {"deb": "jessie", "py3": 3.7, "idx": 7},
            {"deb": "jessie", "py3": 3.7, "idx": 8},
            {"deb": "jessie", "py3": 3.8, "idx": 9},
            {"deb": "jessie", "py3": 3.8, "idx": 10},
            {"deb": "jessie", "py3": 3.8, "idx": 11},
            {"deb": "jessie", "py3": 3.8, "idx": 12},
            {"deb": "jessie", "py3": 3.8, "idx": 13},
            {"deb": "buster", "py3": 3.8, "idx": 14},
            {"deb": "buster", "py3": 3.8, "idx": 15},
            {"deb": "buster", "py3": 3.8, "idx": 16},
            {"deb": "buster", "py3": 3.8, "idx": 17},
            {"deb": "buster", "py3": 3.8, "idx": 18},
            {"deb": "buster", "py3": 3.8, "idx": 19},
            {"deb": "buster", "py3": 3.8, "idx": 20},
        ]

        test_cases = [
            {
                "name": "Test $eq modify string",
                "filter_req": {
                    "name": "test",
                    "terms": [
                        {
                            "type": "$eq",
                            "scope": "inventory",
                            "attribute": "deb",
                            "value": "jessie",
                        }
                    ],
                },
                "filter": lambda dev: dev.inventory["deb"] == "jessie",
                # Perturbations
                "new": [],
                # Modifications in (device filter, change) pairs
                "mods": [
                    (lambda dev: dev.inventory["idx"] in range(3, 6), {"deb": "jessie"})
                ],
                # List of device filters to remove.
                "remove": [],
            },
            {
                "name": "Test $exists -> $gte removing devices",
                "filter_req": {
                    "name": "test",
                    "terms": [
                        {
                            "type": "$exists",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": True,
                        },
                        {
                            "type": "$gte",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": 3.7,
                        },
                    ],
                },
                "filter": lambda dev: "py3" in dev.inventory
                and dev.inventory["py3"] >= 3.7,
                "new": [],
                "mods": [],
                "remove": [
                    lambda dev: "py3" in dev.inventory and dev.inventory["py3"] == 3.7
                ],
            },
            {
                "name": "Test $exists adding new devices",
                "filter_req": {
                    "name": "test",
                    "terms": [
                        {
                            "type": "$exists",
                            "scope": "inventory",
                            "attribute": "py2",
                            "value": True,
                        }
                    ],
                },
                "filter": lambda dev: "py2" in dev.inventory,
                "new": [
                    {"idx": 20, "py3": 3.7},
                    {"idx": 21, "py2": 2.7},
                    {"idx": 22, "py2": 2.6, "py3": 3.3},
                    {"idx": 23, "py2": 2.7, "py3": 3.5},
                    {"idx": 24, "py2": 2.7, "py3": 3.7},
                    {"idx": 25, "py2": 2.7, "py3": 3.7, "misc": "foo"},
                ],
                "mods": [],
                "remove": [],
            },
            {
                "name": "Compound test: modify, remove and add inventories",
                "filter_req": {
                    "name": "test",
                    "terms": [
                        {
                            "type": "$ne",
                            "scope": "inventory",
                            "attribute": "deb",
                            "value": "buster",
                        },
                        {
                            "type": "$exists",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": True,
                        },
                        {
                            "type": "$gte",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": 3.7,
                        },
                    ],
                },
                "filter": lambda dev: dev.inventory["deb"] != "buster"
                and "py3" in dev.inventory
                and dev.inventory["py3"] >= 3.7,
                "mods": [
                    (
                        lambda dev: dev.inventory["deb"] == "squeeze",
                        {"deb": "buster", "py3": 3.8},
                    ),
                    (
                        lambda dev: "py2" in dev.inventory,
                        {"deb": "jessie", "py2": 2.7, "py3": 3.8},
                    ),
                ],
                "new": [
                    {"idx": 20, "deb": "squeeze"},
                    {"idx": 21, "deb": "wheezy"},
                    {"idx": 22, "deb": "wheezy", "py3": 3.3},
                    {"idx": 23, "deb": "jessie", "py3": 3.5},
                    {"idx": 24, "deb": "jessie", "py3": 3.7},
                    {"idx": 25, "deb": "buster", "py3": 3.8, "misc": "foo"},
                ],
                "remove": [
                    lambda dev: "py3" in dev.inventory and dev.inventory["py3"] < 3.5
                ],
            },
        ]

        for test_case in test_cases:
            self.logger.info("Running test case: %s" % test_case["name"])

            # Setup tenant and (initial) device set.
            tenant = create_org(
                "BobTheEnterprise",
                username="bob@ent.org",
                password="password",
                plan="enterprise",
            )
            rsp = usradmm.call(
                "POST",
                useradm.URL_LOGIN,
                auth=(tenant.users[0].name, tenant.users[0].pwd),
            )
            assert rsp.status_code == 200
            tenant.api_token = rsp.text

            # Create accepted devices with inventory.
            tenant.devices = {}
            for inv in inventories:
                device = make_accepted_device(
                    devauthd,
                    devauthm,
                    tenant.api_token,
                    tenant_token=tenant.tenant_token,
                )
                rsp = invd.with_auth(device.token).call(
                    "PATCH",
                    inventory.URL_DEVICE_ATTRIBUTES,
                    body=dict_to_inventoryattrs(inv),
                )
                assert rsp.status_code == 200

                device.inventory = inv
                tenant.devices[device.id] = device

            # Save test filter.
            rsp = invm_v2.with_auth(tenant.api_token).call(
                "POST",
                inventory_v2.URL_SAVED_FILTERS,
                body=test_case["filter_req"],
                qs_params={"per_page": len(tenant.devices)},
            )
            assert rsp.status_code == 201, (
                "Failed to save filter, received status code: %d" % rsp.status_code
            )
            filter_id = rsp.headers.get("Location").split("/")[-1]

            # Check that we get the exected devices from the set.
            rsp = invm_v2.with_auth(tenant.api_token).call(
                "GET", inventory_v2.URL_SAVED_FILTER_SEARCH.format(id=filter_id)
            )
            assert rsp.status_code == 200

            devs_recv = sorted([dev["id"] for dev in rsp.json()])
            devs_exct = sorted(
                [dev.id for dev in filter(test_case["filter"], tenant.devices.values())]
            )
            assert devs_recv == devs_exct, (
                "Unexpected device set returned by saved filters, "
                + "expected: %s, received: %s" % (devs_recv, devs_exct)
            )

            # Perform perturbations to the device set.
            # Starting with modifications
            for fltr, change in test_case["mods"]:
                for dev in filter(fltr, tenant.devices.values(),):
                    for k, v in change.items():
                        dev.inventory[k] = v

                    rsp = invd.with_auth(dev.token).call(
                        "PATCH",
                        inventory.URL_DEVICE_ATTRIBUTES,
                        body=dict_to_inventoryattrs(dev.inventory),
                    )
                    assert rsp.status_code == 200
                    tenant.devices[dev.id] = dev

            # Remove devices
            for fltr in test_case["remove"]:
                for dev in filter(fltr, list(tenant.devices.values())):
                    devauthm.with_auth(tenant.api_token).call(
                        "DELETE", deviceauth.URL_DEVICE.format(id=dev.id)
                    )
                    tenant.devices.pop(dev.id)

            # Add new devices
            for inv in test_case["new"]:
                device = make_accepted_device(
                    devauthd,
                    devauthm,
                    tenant.api_token,
                    tenant_token=tenant.tenant_token,
                )
                rsp = invd.with_auth(device.token).call(
                    "PATCH",
                    inventory.URL_DEVICE_ATTRIBUTES,
                    body=dict_to_inventoryattrs(inv),
                )
                assert rsp.status_code == 200
                device.inventory = inv
                tenant.devices[device.id] = device

            # Check that we get the exected devices from the perturbed set.
            rsp = invm_v2.with_auth(tenant.api_token).call(
                "GET",
                inventory_v2.URL_SAVED_FILTER_SEARCH.format(id=filter_id),
                qs_params={"per_page": len(tenant.devices)},
            )
            assert rsp.status_code == 200

            devs_recv = sorted([dev["id"] for dev in rsp.json()])
            devs_exct = sorted(
                [dev.id for dev in filter(test_case["filter"], tenant.devices.values())]
            )
            assert devs_recv == devs_exct, (
                "Unexpected device set returned by saved filters, "
                + "expected: %s, received: %s" % (devs_recv, devs_exct)
            )

            mongo_cleanup(mongo)


def assert_device_attributes(dev, api_dev):
    for attr in dev["attributes"]:
        assert attr in api_dev["attributes"], (
            "Missing inventory attribute: %s; device attributes: %s"
            % (attr, api_dev["attributes"])
        )
