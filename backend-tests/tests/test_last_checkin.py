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
import logging
from datetime import date
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
    make_pending_device,
    change_authset_status,
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

    user = tenant.users[0]
    utoken = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)).text
    assert utoken != ""
    tenant.api_token = utoken

    for inv in dev_inventories:
        device = make_pending_device(
            devauthd, devauthm, utoken, tenant_token=tenant.tenant_token
        )
        tenant.devices.append(device)

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

    utoken = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)).text
    assert utoken != ""
    user.api_token = utoken

    for inv in dev_inventories:
        device = make_pending_device(devauthd, devauthm, utoken)
        user.devices.append(device)
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
    tenant_ent = create_org(tenant, username, password, "enterprise")
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
    tenant_pro = create_org(tenant, username, password, "professional")
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
    tenant_os = create_org(tenant, username, password, "os")
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


search_query_template = {
    "page": 1,
    "per_page": 1,
    "filters": [
        {"scope": "identity", "attribute": "status", "type": "$eq", "value": "pending",}
    ],
    "attributes": [
        {"scope": "identity", "attribute": "status"},
        {"scope": "inventory", "attribute": "artifact_name"},
        {"scope": "inventory", "attribute": "device_type"},
        {"scope": "inventory", "attribute": "mender_is_gateway"},
        {"scope": "inventory", "attribute": "mender_gateway_system_id"},
        {"scope": "inventory", "attribute": "rootfs-image.version"},
        {"scope": "monitor", "attribute": "alerts"},
        {"scope": "system", "attribute": "created_ts"},
        {"scope": "system", "attribute": "updated_ts"},
        {"scope": "system", "attribute": "group"},
        {"scope": "tags", "attribute": "name"},
    ],
}


@pytest.mark.skipif(
    useExistingTenant(), reason="not feasible to test with existing tenant",
)
@pytest.mark.skipif(
    isK8S(),
    reason="reporting service not deployed to staging or production environment",
)
class TestLastCheckInEnterprise:
    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger

    def test_reporting_search(self, tenant_ent):
        global search_query_template
        reporting_client = ApiClient(reporting.URL_MGMT)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        for d in tenant_ent.devices:
            d.send_auth_request()

        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        search_query = search_query_template
        search_query["per_page"] = len(tenant_ent.devices)
        search_query["filters"][0]["value"] = "pending"
        rsp = reporting_client.with_auth(tenant_ent.api_token).call(
            "POST", reporting.URL_MGMT_DEVICES_SEARCH, search_query
        )
        assert len(rsp.json()) == len(tenant_ent.devices)
        device_check_in_key = "check_in_time"
        for j in rsp.json():
            assert not device_check_in_key in j

        today = date.today()
        for d in tenant_ent.devices:
            aset_id = d.authsets[0].id
            change_authset_status(
                devauthm, d.id, aset_id, "accepted", tenant_ent.api_token
            )
            d.send_auth_request()

        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)
        search_query = search_query_template
        search_query["per_page"] = len(tenant_ent.devices)
        search_query["filters"][0]["value"] = "accepted"
        rsp = reporting_client.with_auth(tenant_ent.api_token).call(
            "POST", reporting.URL_MGMT_DEVICES_SEARCH, search_query
        )
        assert len(rsp.json()) == len(tenant_ent.devices)
        device_check_in_key = "check_in_time"
        date_string = today.strftime("%Y-%m-%d")
        for j in rsp.json():
            assert device_check_in_key in j
            assert j[device_check_in_key] == f"{date_string}T00:00:00Z"


class TestLastCheckIn:
    @property
    def logger(self):
        try:
            return self._logger
        except AttributeError:
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger

    def test_reporting_search(self, user_reporting):
        global search_query_template
        reporting_client = ApiClient(reporting.URL_MGMT)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        for d in user_reporting.devices:
            d.send_auth_request()

        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)
        search_query = search_query_template
        search_query["per_page"] = len(user_reporting.devices)
        search_query["filters"][0]["value"] = "pending"
        rsp = reporting_client.with_auth(user_reporting.api_token).call(
            "POST", reporting.URL_MGMT_DEVICES_SEARCH, search_query
        )
        assert len(rsp.json()) == len(user_reporting.devices)
        device_check_in_key = "check_in_time"
        for j in rsp.json():
            assert not device_check_in_key in j

        today = date.today()
        for d in user_reporting.devices:
            aset_id = d.authsets[0].id
            change_authset_status(
                devauthm, d.id, aset_id, "accepted", user_reporting.api_token
            )
            d.send_auth_request()

        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)
        search_query = search_query_template
        search_query["per_page"] = len(user_reporting.devices)
        search_query["filters"][0]["value"] = "accepted"
        rsp = reporting_client.with_auth(user_reporting.api_token).call(
            "POST", reporting.URL_MGMT_DEVICES_SEARCH, search_query
        )
        assert len(rsp.json()) == len(user_reporting.devices)
        device_check_in_key = "check_in_time"
        date_string = today.strftime("%Y-%m-%d")
        for j in rsp.json():
            assert device_check_in_key in j
            assert j[device_check_in_key] == f"{date_string}T00:00:00Z"
