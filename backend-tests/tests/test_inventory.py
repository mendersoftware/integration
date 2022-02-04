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
import logging
import pytest
import time
import uuid

from testutils.api.client import ApiClient
from testutils.infra.cli import CliUseradm, CliDeviceauth
from testutils.infra.container_manager.kubernetes_manager import isK8S
import testutils.api.deviceauth as deviceauth
import testutils.api.useradm as useradm
import testutils.api.inventory as inventory
import testutils.api.inventory_v2 as inventory_v2

from testutils.common import (
    mongo,
    clean_mongo,
    mongo_cleanup,
    create_user,
    create_org,
    make_accepted_device,
    make_accepted_devices,
    useExistingTenant,
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


class TestGetDevicesBase:
    def do_test_get_devices_ok(self, user, tenant_token=""):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        invm = ApiClient(inventory.URL_MGMT)

        # log in user
        r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # count existing devices
        r = invm.with_auth(utoken).call(
            "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
        )
        assert r.status_code == 200
        count = int(r.headers["X-Total-Count"])

        # prepare accepted devices
        make_accepted_devices(devauthd, devauthm, utoken, tenant_token, 40)

        # wait for devices to be provisioned
        time.sleep(3)

        r = invm.with_auth(utoken).call(
            "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
        )
        assert r.status_code == 200
        new_count = int(r.headers["X-Total-Count"])
        assert new_count == count + 40

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

        r = invm.with_auth(utoken).call(
            "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
        )
        assert r.status_code == 200
        count = int(r.headers["X-Total-Count"])

        # prepare accepted devices
        devs = make_accepted_devices(devauthd, devauthm, utoken, tenant_token, 40)

        # wait for devices to be provisioned
        time.sleep(3)

        r = invm.with_auth(utoken).call(
            "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
        )
        assert r.status_code == 200
        new_count = int(r.headers["X-Total-Count"])
        assert new_count == count + 40

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
            # {"inventory": 3, "identity": 1+2, "system": 2}
            # +2 comes from the id_data see MEN-3637
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


def add_devices_to_tenant(tenant, dev_inventories):
    try:
        tenant.devices
    except AttributeError:
        tenant.devices = []

    useradmm = ApiClient(useradm.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    invd = ApiClient(inventory.URL_DEV)

    user = tenant.users[0]
    utoken = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)).text
    assert utoken != ""
    tenant.api_token = utoken

    for inv in dev_inventories:
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

    return tenant


@pytest.mark.skipif(
    useExistingTenant(), reason="not feasible to test with existing tenant",
)
class TestDeviceFilteringEnterprise:
    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger

    @pytest.fixture(autouse=True)
    def setup_tenants(self, clean_mongo):
        # Initialize tenants and devices
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        self.tenant_ent = create_org(tenant, username, password, "enterprise")
        #
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        self.tenant_pro = create_org(tenant, username, password, "professional")
        #
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        self.tenant_os = create_org(tenant, username, password, "os")
        #
        add_devices_to_tenant(
            self.tenant_ent,
            [
                {"artifact": ["v1"], "py3": "3.3", "py2": "2.7", "idx": 0},
                {"artifact": ["v1", "v2"], "py3": "3.5", "py2": "2.7", "idx": 1},
                {"artifact": ["v1", "v2"], "py2": "2.6", "idx": 2},
                {"artifact": ["v1", "v2"], "py2": "2.7", "idx": 3},
                {"artifact": ["v2"], "py3": "3.5", "py2": "2.7", "idx": 4},
                {"artifact": ["v2"], "py3": "3.6", "py2": "2.7", "idx": 5},
                {"artifact": ["v2", "v3"], "py3": "3.6", "idx": 6},
                {"artifact": ["v2", "v3"], "py3": "3.7", "idx": 7},
                {"artifact": ["v2", "v3"], "py3": "3.7", "idx": 8},
                {"artifact": ["v1", "v2", "v3"], "py3": "3.8", "idx": 9},
            ],
        )
        add_devices_to_tenant(
            self.tenant_pro,
            [
                {"artifact": ["v2"], "idx": 0},
                {"artifact": ["v2"], "idx": 1},
                {"artifact": ["v2"], "idx": 2},
                {"artifact": ["v2"], "idx": 3},
                {"artifact": ["v2"], "idx": 4},
                {"artifact": ["v2"], "idx": 5},
                {"artifact": ["v2", "v3"], "idx": 6},
                {"artifact": ["v2", "v3"], "idx": 7},
                {"artifact": ["v2", "v3"], "idx": 8},
            ],
        )
        add_devices_to_tenant(
            self.tenant_os,
            [
                {"artifact": ["v1"], "idx": 0},
                {"artifact": ["v1"], "idx": 1},
                {"artifact": ["v1"], "idx": 2},
            ],
        )

    def test_search_v2(self):
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
                        "id": str(self.tenant_ent.devices[1].id),
                        "attributes": dict_to_inventoryattrs(
                            self.tenant_ent.devices[1].inventory, scope="inventory"
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
                        {"attribute": "idx", "scope": "inventory", "order": "asc"}
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
                    for dev in filter(
                        lambda dev: dev.inventory["idx"] < 5
                        and dev.inventory["idx"] >= 1,
                        self.tenant_ent.devices,
                    )
                ],
            },
            {
                "name": "Test $exists -> $in, descending sort",
                "request": {
                    "filters": [
                        {
                            "type": "$exists",
                            "attribute": "py3",
                            "value": True,
                            "scope": "inventory",
                        },
                        {
                            "type": "$in",
                            "attribute": "artifact",
                            "value": ["v2", "v3"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc"}
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
                            lambda dev: "py3" in dev.inventory
                            and any(
                                [
                                    ver in ["v2", "v3"]
                                    for ver in dev.inventory["artifact"]
                                ]
                            ),
                            self.tenant_ent.devices,
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
                            "attribute": "artifact",
                            "value": ["v3"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc"},
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
                            lambda dev: "v3" not in dev.inventory["artifact"],
                            self.tenant_ent.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            {
                "name": "Error - missing type parameter",
                "request": {
                    "filters": [
                        {
                            "attribute": "artifact",
                            "value": ["v1"],
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
                            "attribute": "artifact",
                            "value": ["int", "string", "array"],
                            "scope": "inventory",
                        },
                    ],
                },
                "status_code": 400,
            },
        ]
        invm_v2 = ApiClient(inventory_v2.URL_MGMT)

        for test_case in test_cases:
            self.logger.info("Running test case: %s" % test_case["name"])
            rsp = invm_v2.with_auth(self.tenant_ent.api_token).call(
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
                self.logger.info(test_case["response"])
                self.logger.info(body)
                assert len(test_case["response"]) == len(body), (
                    "Unexpected number of results: %s != %s"
                    % (
                        [dev["id"] for dev in test_case["response"]],
                        [dev["id"] for dev in body],
                    )
                )

                if len(test_case["response"]) > 0:
                    if "sort" not in test_case["request"]:
                        body = sorted(body, key=lambda dev: dev["id"])
                        test_case["response"] = sorted(
                            test_case["response"], key=lambda dev: dev["id"]
                        )

                    for i, dev in enumerate(test_case["response"]):
                        assert (
                            dev["id"] == body[i]["id"]
                        ), "Unexpected device in response"
                        assert_device_attributes(dev, body[i])

    def test_search_v2_internal(self):
        """
        Tests the internal v2/{tenant_id}/filters/search endpoint.
        This test along with the former covers all allowed operation
        types.
        """
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
                "tenant_id": self.tenant_os.id,
                "status_code": 200,
                "response": [
                    {
                        "id": str(self.tenant_os.devices[0].id),
                        "attributes": dict_to_inventoryattrs(
                            self.tenant_os.devices[0].inventory, scope="inventory"
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
                "tenant_id": self.tenant_ent.id,
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
                "tenant_id": self.tenant_pro.id,
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in self.tenant_pro.devices[1:5]
                ],
            },
            {
                "name": "Test $exists -> $in, descending sort",
                "request": {
                    "filters": [
                        {
                            "type": "$exists",
                            "attribute": "py3",
                            "value": True,
                            "scope": "inventory",
                        },
                        {
                            "type": "$in",
                            "attribute": "py3",
                            "value": ["3.5", "3.7"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc"}
                    ],
                },
                "status_code": 200,
                "tenant_id": self.tenant_ent.id,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in sorted(
                        filter(
                            lambda dev: "py3" in dev.inventory
                            and dev.inventory["py3"] in ["3.5", "3.7"],
                            self.tenant_ent.devices,
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
                            "attribute": "artifact",
                            "value": ["v1"],
                            "scope": "inventory",
                        },
                    ],
                    "sort": [
                        {"attribute": "idx", "scope": "inventory", "order": "desc"},
                    ],
                },
                "tenant_id": self.tenant_pro.id,
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
                            lambda dev: "v1" not in dev.inventory["artifact"],
                            self.tenant_pro.devices,
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
                "tenant_id": self.tenant_os.id,
                "status_code": 200,
                "response": [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in self.tenant_os.devices[1:]
                ],
            },
            {
                "name": "Error - missing type parameter",
                "request": {
                    "filters": [
                        {
                            "attribute": "artifact",
                            "value": ["v1.0"],
                            "scope": "inventory",
                        },
                    ],
                },
                "tenant_id": self.tenant_ent.id,
                "status_code": 400,
            },
            {
                "name": "Error - valid mongo query unsupported operation",
                "request": {
                    "filters": [
                        {
                            "type": "$type",
                            "attribute": "artifact",
                            "value": ["int", "string", "array"],
                            "scope": "inventory",
                        },
                    ],
                },
                "tenant_id": self.tenant_pro.id,
                "status_code": 400,
            },
        ]
        invm_v2 = ApiClient(
            inventory_v2.URL_INTERNAL, host=inventory_v2.HOST, schema="http://"
        )

        for test_case in test_cases:
            self.logger.info("Running test case: %s" % test_case["name"])
            rsp = invm_v2.call(
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
                    body = []
                assert len(body) == len(test_case["response"]), (
                    "Unexpected number of results: %s != %s"
                    % (test_case["response"], body)
                )

                if len(test_case["response"]) > 0:
                    if "sort" not in test_case["request"]:
                        body = sorted(body, key=lambda dev: dev["id"])
                        test_case["response"] = sorted(
                            test_case["response"], key=lambda dev: dev["id"]
                        )

                    for i, dev in enumerate(test_case["response"]):
                        assert (
                            dev["id"] == body[i]["id"]
                        ), "Unexpected device in response"
                        assert_device_attributes(dev, body[i])

    def test_saved_filters(self):
        """
        Test saved filters covers saving new filters, getting all
        filters, getting filter by id, executing filter and deleting
        filters.
        """
        test_cases = [
            {
                "name": "Simple $eq filters",
                "tenant": self.tenant_ent,
                "request": {
                    "name": "test1",
                    "terms": [
                        {
                            "type": "$eq",
                            "scope": "inventory",
                            "attribute": "idx",
                            "value": 5,
                        }
                    ],
                },
                "status_codes": [201, 200, 200, 200],
                "result": [
                    {"id": dev.id, "attributes": dict_to_inventoryattrs(dev.inventory)}
                    for dev in filter(
                        lambda dev: dev.inventory["idx"] == 5, self.tenant_ent.devices,
                    )
                ],
            },
            {
                "name": "Compound filter: $in -> $exists -> $nin",
                "tenant": self.tenant_ent,
                "request": {
                    "name": "test2",
                    "terms": [
                        {
                            "type": "$in",
                            "scope": "inventory",
                            "attribute": "artifact",
                            "value": ["v2", "v3"],
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
                    {"id": dev.id, "attributes": dict_to_inventoryattrs(dev.inventory)}
                    for dev in filter(
                        lambda dev: dev.inventory["artifact"] in ["v2.0", "v2.1"]
                        and "py3" in dev.inventory
                        and dev.inventory["py3"] not in ["3.5", "3.6"],
                        self.tenant_ent.devices,
                    )
                ],
            },
            {
                "name": "Compound filter: $exists -> $ne -> $lte -> $gt",
                "tenant": self.tenant_ent,
                "request": {
                    "name": "test3",
                    "terms": [
                        {
                            "type": "$exists",
                            "scope": "inventory",
                            "attribute": "py2",
                            "value": True,
                        },
                        {
                            "type": "$ne",
                            "scope": "inventory",
                            "attribute": "py2",
                            "value": "2.6",
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
                    ],
                },
                "status_codes": [201, 200, 200, 200],
                "result": [
                    {"id": dev.id, "attributes": dict_to_inventoryattrs(dev.inventory)}
                    for dev in filter(
                        lambda dev: "py3" not in dev.inventory
                        and 1 < dev.inventory["idx"] <= 8
                        and dev.inventory["py2"] != "2.6",
                        self.tenant_ent.devices,
                    )
                ],
            },
            {
                "name": "Error filter already exists",
                "tenant": self.tenant_ent,
                "request": {
                    "name": "test1",
                    "terms": [
                        {
                            "type": "$ne",
                            "scope": "inventory",
                            "attribute": "artifact",
                            "value": "v2",
                        }
                    ],
                },
                # After an unsuccessfully first call, the filter_id will
                # be replaced by "foobar", hence the 404 response codes.
                "status_codes": [409, 200, 404, 404],
            },
            {
                "name": "Error not allowed for professional accounts",
                "tenant": self.tenant_pro,
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {
                            "type": "$eq",
                            "scope": "inventory",
                            "attribute": "py3",
                            "value": "3.5",
                        }
                    ],
                },
                "status_codes": [403, 403, 403, 403],
            },
            {
                "name": "Error not allowed for open-source accounts",
                "tenant": self.tenant_os,
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {
                            "type": "$eq",
                            "scope": "inventory",
                            "attribute": "artifact",
                            "value": "v2",
                        }
                    ],
                },
                "status_codes": [403, 403, 403, 403],
            },
            {
                "name": "Error empty value",
                "tenant": self.tenant_ent,
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {"type": "$eq", "scope": "inventory", "attribute": "artifact"}
                    ],
                },
                "status_codes": [400, 200, 404, 404],
            },
            {
                "name": "Error invalid filter type",
                "tenant": self.tenant_ent,
                "request": {
                    "name": "forbidden",
                    "terms": [
                        {
                            "type": "$type",
                            "scope": "inventory",
                            "attribute": "artifact",
                            "value": ["string", "array"],
                        }
                    ],
                },
                "status_codes": [400, 200, 404, 404],
            },
        ]
        invm_v2 = ApiClient(inventory_v2.URL_MGMT)

        for test_case in test_cases:
            self.logger.info("Running test: %s" % test_case["name"])
            tenant = test_case["tenant"]
            # Test POST /filters endpoint
            rsp = invm_v2.with_auth(tenant.api_token).call(
                "POST", inventory_v2.URL_SAVED_FILTERS, body=test_case["request"]
            )
            assert rsp.status_code == test_case["status_codes"][0], (
                "Unexpected status code (%d) on POST %s request; response: %s"
                % (rsp.status_code, rsp.url, rsp.text)
            )
            filter_url = rsp.headers.get("Location", "foobar")
            filter_id = filter_url.split("/")[-1]

            # Test GET /filters endpoint
            rsp = invm_v2.with_auth(tenant.api_token).call(
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
            rsp = invm_v2.with_auth(tenant.api_token).call(
                "GET", inventory_v2.URL_SAVED_FILTER.format(id=filter_id)
            )
            assert rsp.status_code == test_case["status_codes"][2]

            # Test GET /filter/{id}/search endpoint
            rsp = invm_v2.with_auth(tenant.api_token).call(
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
        rsp = invm_v2.with_auth(self.tenant_ent.api_token).call(
            "GET", inventory_v2.URL_SAVED_FILTERS
        )
        assert rsp.status_code == 200
        for fltr in rsp.json():
            rsp = invm_v2.with_auth(self.tenant_ent.api_token).call(
                "DELETE", inventory_v2.URL_SAVED_FILTER.format(id=fltr["id"])
            )
            assert rsp.status_code == 204, (
                "Unexpected status code (%d) returned on DELETE %s. Response: %s"
                % (rsp.status_code, rsp.url, rsp.text)
            )

    @pytest.mark.parametrize(
        "test_case",
        [
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
                    {"idx": 16, "py3": 3.7},
                    {"idx": 17, "py2": 2.7},
                    {"idx": 18, "py2": 2.6, "py3": 3.3},
                    {"idx": 19, "py2": 2.7, "py3": 3.5},
                    {"idx": 20, "py2": 2.7, "py3": 3.7},
                    {"idx": 21, "py2": 2.7, "py3": 3.7, "misc": "foo"},
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
                    {"idx": 16, "deb": "squeeze"},
                    {"idx": 17, "deb": "wheezy"},
                    {"idx": 18, "deb": "wheezy", "py3": 3.3},
                    {"idx": 19, "deb": "jessie", "py3": 3.5},
                    {"idx": 20, "deb": "jessie", "py3": 3.7},
                    {"idx": 21, "deb": "buster", "py3": 3.8, "misc": "foo"},
                ],
                "remove": [
                    lambda dev: "py3" in dev.inventory and dev.inventory["py3"] < 3.5
                ],
            },
        ],
    )
    def test_saved_filters_dynamic(self, clean_mongo, test_case):
        """
        Check that the saved filters return the correct set of
        devices when the inventory changes dynamically. That is,
        when devices modify their inventory or get removed entirely.
        """

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
            {"deb": "buster", "py3": 3.8, "idx": 12},
            {"deb": "buster", "py3": 3.8, "idx": 13},
            {"deb": "buster", "py3": 3.8, "idx": 14},
            {"deb": "buster", "py3": 3.8, "idx": 15},
        ]

        self.logger.info("Running test case: %s" % test_case["name"])

        # Setup tenant and (initial) device set.
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        rsp = usradmm.call(
            "POST", useradm.URL_LOGIN, auth=(tenant.users[0].name, tenant.users[0].pwd),
        )
        assert rsp.status_code == 200
        tenant.api_token = rsp.text

        # Create accepted devices with inventory.
        add_devices_to_tenant(tenant, inventories)

        # Save test filter.
        rsp = invm_v2.with_auth(tenant.api_token).call(
            "POST", inventory_v2.URL_SAVED_FILTERS, body=test_case["filter_req"],
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
            [dev.id for dev in filter(test_case["filter"], tenant.devices)]
        )
        assert devs_recv == devs_exct, (
            "Unexpected device set returned by saved filters, "
            + "expected: %s, received: %s" % (devs_recv, devs_exct)
        )

        # Perform perturbations to the device set.
        # Temporary dict representation mapping device.id -> device
        devices = {}
        for dev in tenant.devices:
            devices[dev.id] = dev
        # Starting with modifications
        for fltr, change in test_case["mods"]:
            for dev in filter(fltr, devices.values()):
                for k, v in change.items():
                    dev.inventory[k] = v

                rsp = invd.with_auth(dev.token).call(
                    "PATCH",
                    inventory.URL_DEVICE_ATTRIBUTES,
                    body=dict_to_inventoryattrs(dev.inventory),
                )
                assert rsp.status_code == 200
                devices[dev.id] = dev
            # when running against staging, wait 5 seconds to avoid hitting
            # the rate limits for the devices (one inventory update / 5 seconds)
            isK8S() and time.sleep(5.0)

        # Remove devices
        for fltr in test_case["remove"]:
            for dev in filter(fltr, list(devices.values())):
                devauthm.with_auth(tenant.api_token).call(
                    "DELETE", deviceauth.URL_DEVICE.format(id=dev.id)
                )
                devices.pop(dev.id)

        tenant.devices = list(devices.values())

        # Add new devices
        add_devices_to_tenant(tenant, test_case["new"])

        # Check that we get the exected devices from the perturbed set.
        rsp = invm_v2.with_auth(tenant.api_token).call(
            "GET",
            inventory_v2.URL_SAVED_FILTER_SEARCH.format(id=filter_id),
            qs_params={"per_page": len(tenant.devices) + 1},
        )
        assert rsp.status_code == 200

        devs_recv = sorted([dev["id"] for dev in rsp.json()])
        devs_exct = sorted(
            [dev.id for dev in filter(test_case["filter"], tenant.devices)]
        )
        assert devs_recv == devs_exct, (
            "Unexpected device set returned by saved filters, "
            + "expected: %s, received: %s" % (devs_recv, devs_exct)
        )


def assert_device_attributes(dev, api_dev):
    for attr in dev["attributes"]:
        assert attr in api_dev["attributes"], (
            "Missing inventory attribute: %s; device attributes: %s"
            % (attr, api_dev["attributes"])
        )
