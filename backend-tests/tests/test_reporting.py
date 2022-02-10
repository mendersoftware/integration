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
from urllib import request
import pytest
import time
import uuid

import requests

from testutils.api.client import ApiClient
from testutils.infra.container_manager.kubernetes_manager import isK8S
import testutils.api.deviceauth as deviceauth
import testutils.api.inventory as inventory
import testutils.api.reporting as reporting
import testutils.api.useradm as useradm

from testutils.common import (
    clean_mongo,
    create_user,
    create_org,
    make_accepted_device,
    mongo,
    useExistingTenant,
)


def assert_device_attributes(dev, api_dev):
    for attr in dev["attributes"]:
        assert attr in api_dev["attributes"], (
            "Missing inventory attribute: %s; device attributes: %s"
            % (attr, api_dev["attributes"])
        )


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


def add_devices_to_user(user, dev_inventories):
    try:
        user.devices
    except AttributeError:
        user.devices = []

    useradmm = ApiClient(useradm.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    invd = ApiClient(inventory.URL_DEV)

    utoken = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)).text
    assert utoken != ""
    user.api_token = utoken

    for inv in dev_inventories:
        device = make_accepted_device(devauthd, devauthm, utoken)
        user.devices.append(device)

        attrs = dict_to_inventoryattrs(inv)
        rsp = invd.with_auth(device.token).call(
            "PATCH", inventory.URL_DEVICE_ATTRIBUTES, body=attrs
        )
        assert rsp.status_code == 200
        device.inventory = inv

    return user


def maybe_list(v):
    return v if type(v) == list else [v]


@pytest.fixture(scope="function")
def user(clean_mongo):
    yield create_user("user-foo@acme.com", "correcthorse")


@pytest.fixture(scope="function")
def user_reporting(user):
    add_devices_to_user(
        user,
        [
            {"artifact": "v1", "py3": "3.3", "py2": "2.7", "idx": 0},
            {"artifact": ["v1", "v2"], "py3": "3.5", "py2": "2.7", "idx": 1},
            {"artifact": ["v1", "v2"], "py2": "2.6", "idx": 2},
            {"artifact": ["v1", "v2"], "py2": "2.7", "idx": 3},
            {"artifact": "v2", "py3": "3.5", "py2": "2.7", "idx": 4},
            {"artifact": "v2", "py3": "3.6", "py2": "2.7", "idx": 5},
            {"artifact": ["v2", "v3"], "py3": "3.6", "idx": 6},
            {"artifact": ["v2", "v3"], "py3": "3.7", "idx": 7},
            {"artifact": ["v2", "v3"], "py3": "3.7", "idx": 8},
            {"artifact": ["v1", "v2", "v3"], "py3": "3.8", "idx": 9},
        ],
    )
    # sleep a few seconds waiting for the data propagation to the reporting service
    # and the Elasticsearch indexing to complete
    time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)
    return user


@pytest.fixture(scope="function")
def tenant_ent(clean_mongo):
    # Initialize tenants and devices
    uuidv4 = str(uuid.uuid4())
    tenant, username, password = (
        "test.mender.io-" + uuidv4,
        "some.user+" + uuidv4 + "@example.com",
        "secretsecret",
    )
    tenant_ent = create_org(tenant, username, password, "enterprise", force=True)
    add_devices_to_tenant(
        tenant_ent,
        [
            {"artifact": "v1", "py3": "3.3", "py2": "2.7", "idx": 0},
            {"artifact": ["v1", "v2"], "py3": "3.5", "py2": "2.7", "idx": 1},
            {"artifact": ["v1", "v2"], "py2": "2.6", "idx": 2},
            {"artifact": ["v1", "v2"], "py2": "2.7", "idx": 3},
            {"artifact": "v2", "py3": "3.5", "py2": "2.7", "idx": 4},
            {"artifact": "v2", "py3": "3.6", "py2": "2.7", "idx": 5},
            {"artifact": ["v2", "v3"], "py3": "3.6", "idx": 6},
            {"artifact": ["v2", "v3"], "py3": "3.7", "idx": 7},
            {"artifact": ["v2", "v3"], "py3": "3.7", "idx": 8},
            {"artifact": ["v1", "v2", "v3"], "py3": "3.8", "idx": 9},
        ],
    )
    # sleep a few seconds waiting for the data propagation to the reporting service
    # and the Elasticsearch indexing to complete
    time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)
    return tenant_ent


@pytest.fixture(scope="function")
def tenant_pro(clean_mongo):
    uuidv4 = str(uuid.uuid4())
    tenant, username, password = (
        "test.mender.io-" + uuidv4,
        "some.user+" + uuidv4 + "@example.com",
        "secretsecret",
    )
    tenant_pro = create_org(tenant, username, password, "professional", force=True)
    add_devices_to_tenant(
        tenant_pro,
        [
            {"artifact": "v2", "idx": 0},
            {"artifact": "v2", "idx": 1},
            {"artifact": "v2", "idx": 2},
            {"artifact": "v2", "idx": 3},
            {"artifact": "v2", "idx": 4},
            {"artifact": "v2", "idx": 5},
            {"artifact": ["v2", "v3"], "idx": 6},
            {"artifact": ["v2", "v3"], "idx": 7},
            {"artifact": ["v2", "v3"], "idx": 8},
        ],
    )
    # sleep a few seconds waiting for the data propagation to the reporting service
    # and the Elasticsearch indexing to complete
    time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)
    return tenant_pro


@pytest.fixture(scope="function")
def tenant_os(clean_mongo):
    uuidv4 = str(uuid.uuid4())
    tenant, username, password = (
        "test.mender.io-" + uuidv4,
        "some.user+" + uuidv4 + "@example.com",
        "secretsecret",
    )
    tenant_os = create_org(tenant, username, password, "os", force=True)
    add_devices_to_tenant(
        tenant_os,
        [
            {"artifact": "v1", "idx": 0},
            {"artifact": "v1", "idx": 1},
            {"artifact": "v1", "idx": 2},
        ],
    )
    # sleep a few seconds waiting for the data propagation to the reporting service
    # and the Elasticsearch indexing to complete
    time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)
    return tenant_os


@pytest.mark.skipif(
    isK8S(),
    reason="reporting service not deployed to staging or production environment",
)
class TestReportingSearchEnterprise:
    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger

    @pytest.mark.parametrize(
        "test_case",
        [
            # test_case0
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
                "response": lambda tenant_ent: [
                    {
                        "id": str(tenant_ent.devices[1].id),
                        "attributes": dict_to_inventoryattrs(
                            tenant_ent.devices[1].inventory, scope="inventory"
                        ),
                    }
                ],
            },
            # test_case1
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
                "response": lambda _: [],
            },
            # test_case2
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
                "response": lambda tenant_ent: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in filter(
                        lambda dev: dev.inventory["idx"] < 5
                        and dev.inventory["idx"] >= 1,
                        tenant_ent.devices,
                    )
                ],
            },
            # test_case3
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
                "response": lambda tenant_ent: [
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
                                    for ver in maybe_list(dev.inventory["artifact"])
                                ]
                            ),
                            tenant_ent.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case4
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
                "response": lambda tenant_ent: [
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
                            lambda dev: "v3"
                            not in maybe_list(dev.inventory["artifact"]),
                            tenant_ent.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case5
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
            # test_case6
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
        ],
    )
    def test_reporting_search(self, tenant_ent, test_case):
        reporting_client = ApiClient(reporting.URL_MGMT)
        rsp = reporting_client.with_auth(tenant_ent.api_token).call(
            "POST", reporting.URL_MGMT_DEVICES_SEARCH, test_case["request"]
        )
        assert rsp.status_code == test_case["status_code"], (
            "Unexpected status code (%d) from /devices/search response: %s"
            % (rsp.status_code, rsp.text)
        )
        if rsp.status_code == 200 and "response" in test_case:
            body = rsp.json()
            if body is None:
                body = []
            test_case_response = test_case["response"](tenant_ent)
            self.logger.info("expected: %r", test_case_response)
            self.logger.info("received: %r", body)
            assert len(body) == len(test_case_response), (
                "Unexpected number of results: %s != %s"
                % (
                    [dev["id"] for dev in test_case_response],
                    [dev["id"] for dev in body],
                )
            )
            if len(test_case_response) > 0:
                if "sort" not in test_case["request"]:
                    body = sorted(body, key=lambda dev: dev["id"])
                    test_case_response = sorted(
                        test_case_response, key=lambda dev: dev["id"]
                    )
                for i, dev in enumerate(test_case_response):
                    assert dev["id"] == body[i]["id"], "Unexpected device in response"
                    assert_device_attributes(dev, body[i])

    @pytest.mark.parametrize(
        "test_case",
        [
            # test_case0
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
                "tenant": "os",
                "status_code": 200,
                "response": lambda tenant: [
                    {
                        "id": str(tenant.devices[0].id),
                        "attributes": dict_to_inventoryattrs(
                            tenant.devices[0].inventory, scope="inventory"
                        ),
                    }
                ],
            },
            # test_case1
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
                "tenant": "enterprise",
                "status_code": 200,
                "response": lambda _: [],
            },
            # test_case2
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
                "tenant": "professional",
                "status_code": 200,
                "response": lambda tenant: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in tenant.devices[1:5]
                ],
            },
            # test_case3
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
                "tenant": "enterprise",
                "response": lambda tenant: [
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
                            tenant.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case4
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
                "tenant": "professional",
                "status_code": 200,
                "response": lambda tenant: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in sorted(
                        filter(
                            lambda dev: "v1"
                            not in maybe_list(dev.inventory["artifact"]),
                            tenant.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case5
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
                "tenant": "os",
                "status_code": 200,
                "response": lambda tenant: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in tenant.devices[1:]
                ],
            },
            # test_case6
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
                "tenant": "enterprise",
                "status_code": 400,
            },
            # test_case7
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
                "tenant": "professional",
                "status_code": 400,
            },
        ],
    )
    def test_reporting_search_internal(
        self, tenant_os, tenant_pro, tenant_ent, test_case
    ):
        """
        Tests the internal /inventory/tenants/{tenant_id}/search endpoint.
        This test along with the former covers all allowed operation
        types.
        """
        tenant = {
            "os": tenant_os,
            "professional": tenant_pro,
            "enterprise": tenant_ent,
        }.get(test_case["tenant"])
        reporting_client = ApiClient(
            reporting.URL_INTERNAL, host=reporting.HOST, schema="http://"
        )
        rsp = reporting_client.call(
            "POST",
            reporting.URL_INTERNAL_DEVICES_SEARCH.format(tenant_id=tenant.id),
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
            test_case_response = test_case["response"](tenant)
            self.logger.info("expected: %r", test_case_response)
            self.logger.info("received: %r", body)
            assert len(body) == len(test_case_response), (
                "Unexpected number of results: %s != %s"
                % (
                    [dev["id"] for dev in test_case_response],
                    [dev["id"] for dev in body],
                )
            )
            if len(test_case_response) > 0:
                if "sort" not in test_case["request"]:
                    body = sorted(body, key=lambda dev: dev["id"])
                    test_case_response = sorted(
                        test_case_response, key=lambda dev: dev["id"]
                    )
                for i, dev in enumerate(test_case_response):
                    assert dev["id"] == body[i]["id"], "Unexpected device in response"
                    assert_device_attributes(dev, body[i])


class TestReportingSearch:
    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger

    @pytest.mark.parametrize(
        "test_case",
        [
            # test_case0
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
                "response": lambda user: [
                    {
                        "id": str(user.devices[1].id),
                        "attributes": dict_to_inventoryattrs(
                            user.devices[1].inventory, scope="inventory"
                        ),
                    }
                ],
            },
            # test_case1
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
                "response": lambda _: [],
            },
            # test_case2
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
                "response": lambda user: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in filter(
                        lambda dev: dev.inventory["idx"] < 5
                        and dev.inventory["idx"] >= 1,
                        user.devices,
                    )
                ],
            },
            # test_case3
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
                "response": lambda user: [
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
                                    for ver in maybe_list(dev.inventory["artifact"])
                                ]
                            ),
                            user.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case4
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
                "response": lambda user: [
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
                            lambda dev: "v3"
                            not in maybe_list(dev.inventory["artifact"]),
                            user.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case5
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
            # test_case6
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
        ],
    )
    def test_reporting_search(self, user_reporting, test_case):
        reporting_client = ApiClient(reporting.URL_MGMT)
        rsp = reporting_client.with_auth(user_reporting.api_token).call(
            "POST", reporting.URL_MGMT_DEVICES_SEARCH, test_case["request"]
        )
        assert rsp.status_code == test_case["status_code"], (
            "Unexpected status code (%d) from /devices/search response: %s"
            % (rsp.status_code, rsp.text)
        )
        if rsp.status_code == 200 and "response" in test_case:
            body = rsp.json()
            if body is None:
                body = []
            test_case_response = test_case["response"](user_reporting)
            self.logger.info("expected: %r", test_case_response)
            self.logger.info("received: %r", body)
            assert len(body) == len(test_case_response), (
                "Unexpected number of results: %s != %s"
                % (
                    [dev["id"] for dev in test_case_response],
                    [dev["id"] for dev in body],
                )
            )
            if len(test_case_response) > 0:
                if "sort" not in test_case["request"]:
                    body = sorted(body, key=lambda dev: dev["id"])
                    test_case_response = sorted(
                        test_case_response, key=lambda dev: dev["id"]
                    )
                for i, dev in enumerate(test_case_response):
                    assert dev["id"] == body[i]["id"], "Unexpected device in response"
                    assert_device_attributes(dev, body[i])

    @pytest.mark.parametrize(
        "test_case",
        [
            # test_case0
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
                "status_code": 200,
                "response": lambda user: [
                    {
                        "id": str(user.devices[0].id),
                        "attributes": dict_to_inventoryattrs(
                            user.devices[0].inventory, scope="inventory"
                        ),
                    }
                ],
            },
            # test_case1
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
                "response": lambda _: [],
            },
            # test_case2
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
                "response": lambda user: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in user.devices[1:5]
                ],
            },
            # test_case3
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
                "response": lambda user: [
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
                            user.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case4
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
                "status_code": 200,
                "response": lambda user: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in sorted(
                        filter(
                            lambda dev: "v1"
                            not in maybe_list(dev.inventory["artifact"]),
                            user.devices,
                        ),
                        key=lambda dev: dev.inventory["idx"],
                        reverse=True,
                    )
                ],
            },
            # test_case5
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
                "status_code": 200,
                "response": lambda user: [
                    {
                        "id": dev.id,
                        "attributes": dict_to_inventoryattrs(
                            dev.inventory, scope="inventory"
                        ),
                    }
                    for dev in user.devices[1:]
                ],
            },
            # test_case6
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
                "status_code": 400,
            },
            # test_case7
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
        ],
    )
    def test_reporting_search_internal(self, user_reporting, test_case):
        """
        Tests the internal /inventory/tenants/{tenant_id}/search endpoint.
        This test along with the former covers all allowed operation
        types.
        """
        reporting_client = ApiClient(
            reporting.URL_INTERNAL, host=reporting.HOST, schema="http://"
        )
        rsp = reporting_client.call(
            "POST",
            reporting.URL_INTERNAL_DEVICES_SEARCH.format(tenant_id=""),
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
            test_case_response = test_case["response"](user_reporting)
            self.logger.info("expected: %r", test_case_response)
            self.logger.info("received: %r", body)
            assert len(body) == len(test_case_response), (
                "Unexpected number of results: %s != %s"
                % (
                    [dev["id"] for dev in test_case_response],
                    [dev["id"] for dev in body],
                )
            )
            if len(test_case_response) > 0:
                if "sort" not in test_case["request"]:
                    body = sorted(body, key=lambda dev: dev["id"])
                    test_case_response = sorted(
                        test_case_response, key=lambda dev: dev["id"]
                    )
                for i, dev in enumerate(test_case_response):
                    assert dev["id"] == body[i]["id"], "Unexpected device in response"
                    assert_device_attributes(dev, body[i])
