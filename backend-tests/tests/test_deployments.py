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
import pytest
import multiprocessing as mp
import os
import random
import time
import uuid

from datetime import datetime, timedelta

import testutils.api.deviceauth as deviceauth
import testutils.api.useradm as useradm
import testutils.api.inventory as inventory
import testutils.api.inventory_v2 as inventory_v2
import testutils.api.deployments as deployments
import testutils.api.deployments_v2 as deployments_v2
import testutils.api.reporting as reporting

from testutils.api.client import ApiClient
from testutils.common import (
    create_org,
    create_user,
    clean_mongo,
    mongo_cleanup,
    mongo,
    get_mender_artifact,
    make_accepted_device,
    make_accepted_devices,
    make_device_with_inventory,
    submit_inventory,
    useExistingTenant,
    Tenant,
)
from testutils.infra.container_manager.kubernetes_manager import isK8S


WAITING_MULTIPLIER = 8 if isK8S() else 1
WAITING_TIME_K8S = 5.0


def upload_image(filename, auth_token, description="abc"):
    api_client = ApiClient(deployments.URL_MGMT)
    api_client.headers = {}
    r = api_client.with_auth(auth_token).call(
        "POST",
        deployments.URL_DEPLOYMENTS_ARTIFACTS,
        files=(
            ("description", (None, description)),
            ("size", (None, str(os.path.getsize(filename)))),
            ("artifact", (filename, open(filename, "rb"), "application/octet-stream")),
        ),
    )
    assert r.status_code == 201


def create_tenant_test_setup(
    user_name, tenant_name, nr_deployments=3, nr_devices=100, plan="os"
):
    """
    Creates a tenant, and a user belonging to the tenant
    with 'nr_deployments', and 'nr_devices'
    """
    api_mgmt_deploy = ApiClient(deployments.URL_MGMT)
    tenant = create_org(tenant_name, user_name, "correcthorse", plan=plan)
    user = tenant.users[0]
    r = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert r.status_code == 200
    user.utoken = r.text
    tenant.users = [user]
    upload_image("/tests/test-artifact.mender", user.utoken)

    # count deployments
    resp = api_mgmt_deploy.with_auth(user.utoken).call("GET", "/deployments")
    assert resp.status_code == 200
    count = int(resp.headers["X-Total-Count"])

    # Create three deployments for the user
    for i in range(nr_deployments):
        request_body = {
            "name": str(i) + "st-dummy-deployment",
            "artifact_name": "deployments-phase-testing",
            "devices": ["uuid not needed" + str(i) for i in range(nr_devices)],
        }
        resp = api_mgmt_deploy.with_auth(user.utoken).call(
            "POST", "/deployments", body=request_body
        )
        assert resp.status_code == 201

    # Verify that the 'nr_deployments' expected deployments have been created
    resp = api_mgmt_deploy.with_auth(user.utoken).call("GET", "/deployments")
    assert resp.status_code == 200
    new_count = int(resp.headers["X-Total-Count"])
    assert new_count == count + nr_deployments

    return tenant


@pytest.fixture(scope="function")
def setup_deployments_enterprise_test(
    clean_mongo, existing_deployments=3, nr_devices=100, plan="enterprise"
):
    """
    Creates two tenants, with one user each, where each user has three deployments,
    and a hundred devices each.
    """

    uuidv4 = str(uuid.uuid4())
    tenant1 = create_tenant_test_setup(
        "some.user+" + uuidv4 + "@example.com", "test.mender.io-" + uuidv4, plan=plan
    )
    # Add a second tenant to make sure that the functionality does not interfere with other tenants
    uuidv4 = str(uuid.uuid4())
    tenant2 = create_tenant_test_setup(
        "some.user+" + uuidv4 + "@example.com", "test.mender.io-" + uuidv4, plan=plan
    )
    # Create 'existing_deployments' predefined deployments to act as noise for the server to handle
    # for both users
    return tenant1, tenant2


class TestDeploymentsEndpointEnterprise(object):
    #
    # The test_cases array consists of test tuples of the form:
    # (request, expected_response)
    #
    test_cases = [
        # One phase:
        #     + start_time
        #     + batch_size
        (
            {
                "name": "One phase, with start time, and full batch size",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 100,
                    }
                ],
            },
            {
                "name": "One phase, with start time, and full batch size",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [{"batch_size": 100}],
            },
        ),
        # One phase:
        #     + start_time
        #     - batch_size
        (
            {
                "name": "One phase, with start time",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z"
                    }
                ],
            },
            {
                "name": "One phase, with start time",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
            },
        ),
        # One phase:
        #     - start_time
        #     + batch_size
        (
            {
                "name": "One phase, with no start time, and full batch size",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [{"batch_size": 100}],
            },
            {
                "name": "One phase, with no start time, and full batch size",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [{"batch_size": 100}],
            },
        ),
        # Two phases:
        #   first:
        #     + start_time
        #     + batch_size
        #   last:
        #     + start_time
        #     + batch_size
        (
            {
                "name": "Two phases, with start time and batch, last with start time and batch size",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 10,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 90,
                    },
                ],
            },
            {
                "name": "Two phases, with start time and batch, last with start time and batch size",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [{"batch_size": 10}, {"batch_size": 90}],
            },
        ),
        # Two phases:
        #   first:
        #     - start_time
        #     + batch_size
        #   last:
        #     + start_time
        #     + batch_size
        (
            {
                "name": "Two phases, with no start time and batch, last with start time and batch size",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {"batch_size": 10},
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 90,
                    },
                ],
            },
            {
                "name": "Two phases, with no start time and batch, last with start time and batch size",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [{"batch_size": 10}, {"batch_size": 90}],
            },
        ),
        # Two phases:
        #   first:
        #     - start_time
        #     + batch_size
        #   last:
        #     + start_time
        #     - batch_size
        (
            {
                "name": "Two phases, with no start time and batch, last with start time",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {"batch_size": 10},
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z"
                    },
                ],
            },
            {
                "name": "Two phases, with no start time and batch, last with start time",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [{"batch_size": 10}, {"batch_size": 90}],
            },
        ),
        # Three phases:
        #   first phase:
        #     + start_time
        #     + batch_size
        #   last phase:
        #     + start_time
        #     + batch_size
        (
            {
                "name": "Three phases, first start and batch, last start and batch",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {
                        "start_time": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 10,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 45,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=2)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 45,
                    },
                ],
            },
            {
                "name": "Three phases, first start and batch, last start and batch",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [
                    {
                        "batch_size": 10,
                        # The nr of devices that asked for an update within the phase, in this case 0
                        "device_count": 0,
                    },
                    {"batch_size": 45, "device_count": 0},
                    {"batch_size": 45, "device_count": 0},
                ],
            },
        ),
        # Three phases:
        #   first phase:
        #     - start_time
        #     + batch_size
        #   last phase:
        #     + start_time
        #     + batch_size
        (
            {
                "name": "Three phases, first batch, last start and batch",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {"batch_size": 10},
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 45,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=2)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 45,
                    },
                ],
            },
            {
                "name": "Three phases, first batch, last start and batch",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [
                    {"batch_size": 10, "device_count": 0},
                    {"batch_size": 45, "device_count": 0},
                    {"batch_size": 45, "device_count": 0},
                ],
            },
        ),
        # Three phases:
        #   first phase:
        #     - start_time
        #     + batch_size
        #   last phase:
        #     + start_time
        #     - batch_size
        (
            {
                "name": "Three phases, first batch, last start",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {"batch_size": 10},
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 45,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=2)).isoformat("T")
                        )
                        + "Z",
                        # Batch size is optional in the last stage (ie, it is the remaining devices)
                    },
                ],
            },
            {
                "name": "Three phases, first batch, last start",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [
                    {
                        "batch_size": 10,
                        # The nr of devices that asked for an update within the phase, in this case 0
                        "device_count": 0,
                    },
                    {"batch_size": 45, "device_count": 0},
                    {"batch_size": 45, "device_count": 0},
                ],
            },
        ),
        # Phase, Five batches, just make sure it works. Should behave like all other > 1 cases
        (
            {
                "name": "Five phases, first no start time, last start time, no batch size",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {
                        # Start time is optional in the first stage (default to now)
                        "batch_size": 10
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 10,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 10,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=1)).isoformat("T")
                        )
                        + "Z",
                        "batch_size": 10,
                    },
                    {
                        "start_ts": str(
                            (datetime.utcnow() + timedelta(days=2)).isoformat("T")
                        )
                        + "Z",
                        # Batch size is optional in the last stage (ie, it is the remaining devices)
                    },
                ],
            },
            {
                "name": "Five phases, first no start time, last start time, no batch size",
                "artifact_name": "deployments-phase-testing",
                "device_count": 0,
                "max_devices": 100,
                "phases": [
                    {"batch_size": 10, "device_count": 0},
                    {"batch_size": 10, "device_count": 0},
                    {"batch_size": 10, "device_count": 0},
                    {"batch_size": 10, "device_count": 0},
                    {"batch_size": 60, "device_count": 0},
                ],
            },
        ),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_phased_deployments_success(
        self, test_case, setup_deployments_enterprise_test
    ):

        deploymentclient = ApiClient(deployments.URL_MGMT)
        tenant1, tenant2 = setup_deployments_enterprise_test
        resp = deploymentclient.with_auth(tenant2.users[0].utoken).call(
            "GET", "/deployments"
        )
        assert resp.status_code == 200
        second_tenant_deployments_count = resp.headers["X-Total-Count"]
        # Store the second tenants user deployments, to verify that
        # it remains unchanged after the tests have run
        backup_tenant_user_deployments = resp.json()
        request_body, expected_response = test_case
        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
            "POST", "/deployments", body=request_body
        )
        assert resp.status_code == 201
        deployment_id = os.path.basename(resp.headers["Location"])
        if not useExistingTenant():
            resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
                "GET", "/deployments"
            )
            assert resp.status_code == 200
            assert len(resp.json()) == 4

        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
            "GET", "/deployments/" + deployment_id
        )
        assert resp.status_code == 200
        id_response_body_dict = resp.json()
        TestDeploymentsEndpointEnterprise.compare_response_json(
            expected_response, id_response_body_dict
        )
        # Verify that the second tenant's deployemnts remain untouched
        resp = deploymentclient.with_auth(tenant2.users[0].utoken).call(
            "GET", "/deployments"
        )
        assert resp.status_code == 200
        second_tenant_deployments_count_new = resp.headers["X-Total-Count"]
        assert second_tenant_deployments_count_new == second_tenant_deployments_count

    def compare_response_json(expected_response, response_body_json):
        """Compare the keys that are present in the expected json dict with the matching response keys.
        Ignore those response keys which are not present in the expected dictionary"""
        for key in expected_response.keys() & response_body_json.keys():
            if key == "phases":
                TestDeploymentsEndpointEnterprise.compare_phases_json(
                    expected_response["phases"], response_body_json["phases"]
                )
            else:
                assert expected_response[key] == response_body_json[key]

    def compare_phases_json(expected, response):
        """phases is a list of phases json objects. Compare them"""
        assert len(expected) == len(response)
        # The phases are a list of phase objects. Compare them on matching keys
        for exp, rsp in zip(expected, response):
            for k in exp.keys() & rsp.keys():
                assert exp[k] == rsp[k]


def setup_devices_and_management_st(nr_devices=100, deploy_to_group=None):
    """
    Sets up user creates authorized devices.
    """
    uuidv4 = str(uuid.uuid4())
    user = create_user("some.user+" + uuidv4 + "@example.com", "secretsecret")
    useradmm = ApiClient(useradm.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    invm = ApiClient(inventory.URL_MGMT)
    # log in user
    r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert r.status_code == 200
    utoken = r.text
    # Upload a dummy artifact to the server
    upload_image("/tests/test-artifact.mender", utoken)
    # count existing devices
    r = invm.with_auth(utoken).call(
        "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
    )
    assert r.status_code == 200
    count = int(r.headers["X-Total-Count"])
    # prepare accepted devices
    devs = make_accepted_devices(devauthd, devauthm, utoken, "", nr_devices)
    # wait for devices to be provisioned
    time.sleep(3)
    if deploy_to_group:
        for device in devs[:-1]:
            r = invm.with_auth(utoken).call(
                "PUT",
                inventory.URL_DEVICE_GROUP.format(id=device.id),
                body={"group": deploy_to_group},
            )
            assert r.status_code == 204

    r = invm.with_auth(utoken).call(
        "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
    )
    assert r.status_code == 200
    new_count = int(r.headers["X-Total-Count"])
    assert new_count == count + nr_devices

    return user, utoken, devs


def setup_devices_and_management_mt(nr_devices=100, deploy_to_group=None):
    """
    Sets up user and tenant and creates authorized devices.
    """
    uuidv4 = str(uuid.uuid4())
    tenant = create_org(
        "test.mender.io-" + uuidv4,
        "some.user+" + uuidv4 + "@example.com",
        "correcthorse",
        plan="enterprise",
    )
    user = tenant.users[0]
    useradmm = ApiClient(useradm.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    invm = ApiClient(inventory.URL_MGMT)
    # log in user
    r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert r.status_code == 200
    utoken = r.text
    # Upload a dummy artifact to the server
    upload_image("/tests/test-artifact.mender", utoken)
    # count existing devices
    r = invm.with_auth(utoken).call(
        "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
    )
    assert r.status_code == 200
    count = int(r.headers["X-Total-Count"])
    # prepare accepted devices
    devs = make_accepted_devices(
        devauthd, devauthm, utoken, tenant.tenant_token, nr_devices
    )
    # wait for devices to be provisioned
    time.sleep(3)
    if deploy_to_group:
        for device in devs[:-1]:
            r = invm.with_auth(utoken).call(
                "PUT",
                inventory.URL_DEVICE_GROUP.format(id=device.id),
                body={"group": deploy_to_group},
            )
            assert r.status_code == 204

    # Check that the number of devices were created
    r = invm.with_auth(utoken).call(
        "GET", inventory.URL_DEVICES, qs_params={"per_page": 1}
    )
    assert r.status_code == 200
    new_count = int(r.headers["X-Total-Count"])
    assert new_count == count + nr_devices

    return user, tenant, utoken, devs


def try_update(
    device, default_artifact_name="bugs-bunny", default_device_type="qemux86-64"
):
    """
    Try to make an update with a device
    :param devices:               list of devices
    :param expected_status_code:  expected status code
    :param default_artifact_name: default artifact name of the
                                  artifact used in the request

    NOTE: You can override the device type and artifact name
          by creating a device_type/artifact_name member of the
          Device object.
    """
    api_dev_deploy = ApiClient(deployments.URL_DEVICES)
    # Try to retrieve next update and assert expected status code
    resp = api_dev_deploy.with_auth(device.token).call(
        "GET",
        deployments.URL_NEXT,
        qs_params={
            "artifact_name": getattr(device, "artifact_name", default_artifact_name),
            "device_type": getattr(device, "device_type", default_device_type),
        },
    )
    if resp.status_code == 200:
        # Update device status upon successful request
        api_dev_deploy.with_auth(device.token).call(
            "PUT",
            deployments.URL_STATUS.format(id=resp.json()["id"]),
            body={"status": "success"},
        )
    return resp.status_code


class TestDeploymentsBase(object):
    def do_test_regular_deployment(self, clean_mongo, user_token, devs):
        api_mgmt_dep = ApiClient(deployments.URL_MGMT)

        # Make deployment request
        deployment_req = {
            "name": "phased-deployment",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
        }
        api_mgmt_dep.with_auth(user_token).call(
            "POST", deployments.URL_DEPLOYMENTS, deployment_req
        )

        for dev in devs:
            status_code = try_update(dev)
            assert status_code == 200
            dev.artifact_name = deployment_req["artifact_name"]

        # when running against staging, wait 5 seconds to avoid hitting
        # the rate limits for the devices (one inventory update / 5 seconds)
        isK8S() and time.sleep(5.0)

        for dev in devs:
            # Deployment already finished
            status_code = try_update(dev)
            assert status_code == 204

        # when running against staging, wait 5 seconds to avoid hitting
        # the rate limits for the devices (one inventory update / 5 seconds)
        isK8S() and time.sleep(5.0)

        deployment_req["name"] = "really-old-update"
        api_mgmt_dep.with_auth(user_token).call(
            "POST", deployments.URL_DEPLOYMENTS, deployment_req
        )
        for dev in devs:
            # Already installed
            status_code = try_update(dev)
            assert status_code == 204


class TestDeploymentOpenSource(TestDeploymentsBase):
    def test_regular_deployment(self, clean_mongo):
        _user, user_token, devs = setup_devices_and_management_st(5)
        self.do_test_regular_deployment(clean_mongo, user_token, devs)


class TestDeploymentEnterprise(TestDeploymentsBase):
    def test_regular_deployment(self, clean_mongo):
        _user, _tenant, user_token, devs = setup_devices_and_management_mt(5)
        self.do_test_regular_deployment(clean_mongo, user_token, devs)


class TestPhasedRolloutDeploymentsEnterprise:
    def try_phased_updates(
        self, deployment, devices, user_token, expected_update_status=200
    ):
        # Static helper function
        # Setup Deployment APIs
        api_mgmt_deploy = ApiClient(deployments.URL_MGMT)

        devices_updated = 0
        num_phases = len(deployment["phases"])
        batch_sizes = [
            int((deployment["phases"][i]["batch_size"] / 100.0) * len(devices))
            for i in range(num_phases - 1)
        ]
        # Final batch_size might not be specified
        batch_sizes.append(len(devices) - sum(batch_sizes))

        # POST deployment
        resp = api_mgmt_deploy.with_auth(user_token).call(
            "POST", deployments.URL_DEPLOYMENTS, body=deployment
        )
        assert resp.status_code == 201

        # Store the location from the GET /deployments/{id} request
        deployment_id = os.path.basename(resp.headers["Location"])

        for i in range(num_phases):
            if i == 0 and "start_ts" not in deployment["phases"][i]:
                # First phase don't need to specify `start_ts`
                pass
            elif "start_ts" in deployment["phases"][i]:
                # Sleep until next phase starts
                start_ts = datetime.strptime(
                    deployment["phases"][i]["start_ts"], "%Y-%m-%dT%H:%M:%SZ"
                )
                now = datetime.utcnow()

                # While phase in progress
                # NOTE: add a half a second buffer time, as a just-in-time
                #       request will break the remainder of the test
                while now < (
                    start_ts - timedelta(milliseconds=500 * WAITING_MULTIPLIER)
                ):
                    # Spam update requests from random non-updated devices
                    dev = random.choice(devices)
                    status_code = try_update(dev)
                    assert status_code == 204 or status_code == 429
                    now = datetime.utcnow()
                # Sleep the last 500ms to let the next phase start
                time.sleep(0.5 * WAITING_MULTIPLIER)
            else:
                raise ValueError(
                    "Invalid phased deployment request, "
                    "missing `start_ts` for phase %d" % i
                )

            # Test for all devices in the deployment
            if devices_updated > 0:
                # Allready updated
                for device in devices[:devices_updated]:
                    status_code = try_update(device)
                    assert status_code == 204

            # Check phase count has not been incremented by the above requests
            resp = api_mgmt_deploy.with_auth(user_token).call(
                "GET", deployments.URL_DEPLOYMENTS_ID.format(id=deployment_id)
            )
            phase = resp.json()["phases"][i]
            assert phase["device_count"] == 0

            # Devices that should update
            for n, device in enumerate(
                devices[devices_updated : (devices_updated + batch_sizes[i])], 1
            ):
                status_code = try_update(device)
                assert status_code == expected_update_status
                if expected_update_status == 200:
                    # Make sure to override artifact_name property
                    device.artifact_name = deployment["artifact_name"]
                # Check phase count is incremented correctly
                resp = api_mgmt_deploy.with_auth(user_token).call(
                    "GET", os.path.join("/deployments", deployment_id)
                )
                phase = resp.json()["phases"][i]
                assert phase["device_count"] == n

            if i < num_phases - 1:
                # Capacity exceeded
                for device in devices[(devices_updated + batch_sizes[i]) :]:
                    status_code = try_update(device)
                    assert status_code == 204

            devices_updated += batch_sizes[i]

            # Check phase count equals batch size
            resp = api_mgmt_deploy.with_auth(user_token).call(
                "GET", os.path.join("/deployments", deployment_id)
            )
            phases = resp.json()["phases"]
            for p in range(i + 1):
                assert phases[p]["device_count"] == batch_sizes[p]
            for p in range(i + 1, len(phases)):
                assert phases[p]["device_count"] == 0

        # Finally confirm that deployment is finished
        assert resp.json()["status"] == "finished"

    def test_phased_regular_deployment(self, clean_mongo):
        """
        Phased equivalent of a regular deployment.
        """
        user, tenant, utoken, devs = setup_devices_and_management_mt()

        deployment_req = {
            "name": "phased-regular-deployment",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [{}],
        }
        self.try_phased_updates(deployment_req, devs, utoken)

    def test_delayed_deployment(self, clean_mongo):
        """
        Uses a single phase with a delayed start-time.
        """
        user, tenant, utoken, devs = setup_devices_and_management_mt()

        deployment_req = {
            "name": "phased-delayed-deployment",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {
                    "start_ts": (
                        datetime.utcnow() + timedelta(seconds=15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                }
            ],
        }
        self.try_phased_updates(deployment_req, devs, utoken)

    def test_two_phases_full_spec(self, clean_mongo):
        """
        Two phases, with batch_size and start_ts specified for both phases.
        """
        user, tenant, utoken, devs = setup_devices_and_management_mt()
        deployment_req = {
            "name": "two-fully-spec-deployments",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {
                    "batch_size": 10,
                    "start_ts": (
                        datetime.utcnow() + timedelta(seconds=15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                {
                    "start_ts": (
                        datetime.utcnow()
                        + timedelta(seconds=2 * 15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "batch_size": 90,
                },
            ],
        }
        self.try_phased_updates(deployment_req, devs, utoken)

    def test_three_phased_deployments(self, clean_mongo):
        """
        Three phases; with no start_ts in first and no batch_size in third.
        """
        user, tenant, utoken, devs = setup_devices_and_management_mt(nr_devices=101)

        deployment_req = {
            "name": "three-phased-deployments",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {"batch_size": 13},
                {
                    "start_ts": (
                        datetime.utcnow() + timedelta(seconds=15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "batch_size": 17,
                },
                {
                    "batch_size": 29,
                    "start_ts": (
                        datetime.utcnow()
                        + timedelta(seconds=2 * 15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                {
                    "start_ts": (
                        datetime.utcnow()
                        + timedelta(seconds=3 * 15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                },
            ],
        }
        self.try_phased_updates(deployment_req, devs, utoken)

    def test_disallow_empty_phase(self, clean_mongo):
        """
        Test that in the case a batch is empty due to rounding errors,
        the server returns 400, with an appropriate error message.
        """

        user, tenant, utoken, devs = setup_devices_and_management_mt(nr_devices=101)

        deployment_req = {
            "name": "empty-batch-test",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs[:11]],
            "phases": [
                {"batch_size": 10},
                {
                    "start_ts": (
                        datetime.utcnow() + timedelta(seconds=15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "batch_size": 20,
                },
                {
                    "batch_size": 5,
                    "start_ts": (
                        datetime.utcnow()
                        + timedelta(seconds=2 * 15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                {
                    "start_ts": (
                        datetime.utcnow()
                        + timedelta(seconds=3 * 15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                },
            ],
        }

        resp = (
            ApiClient(deployments.URL_MGMT)
            .with_auth(utoken)
            .call("POST", deployments.URL_DEPLOYMENTS, body=deployment_req)
        )
        assert resp.status_code == 400
        assert "Attempt to create a batch with zero devices not allowed" in resp.text
        assert "Batch: (3) will be empty" in resp.text

    def test_no_artifact_for_devices(self, clean_mongo):
        """
        Tests that phase counts and statistics are updated correctly
        when there are no applicable artifact for the devices.
        """
        user, tenant, utoken, devs = setup_devices_and_management_mt(nr_devices=101)

        for dev in devs:
            dev.device_type = "pranked_exclamation-mark"

        deployment_req = {
            "name": "three-phased-deployments",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {"batch_size": 13},
                {
                    "batch_size": 29,
                    "start_ts": (
                        datetime.utcnow() + timedelta(seconds=15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                {
                    "start_ts": (
                        datetime.utcnow()
                        + timedelta(seconds=2 * 15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                },
            ],
        }
        self.try_phased_updates(
            deployment_req, devs, utoken, expected_update_status=204
        )


def calculate_phase_sizes(deployment_request):
    batch_sizes = []
    devices_in_phases = 0
    device_count = len(deployment_request["devices"])
    last_phase_idx = len(deployment_request["phases"]) - 1

    for i, phase in enumerate(deployment_request["phases"]):
        if i != last_phase_idx:
            batch_sizes.append(int((phase["batch_size"] / 100.0) * device_count))
        else:
            batch_sizes.append(device_count - devices_in_phases)
        devices_in_phases += batch_sizes[i]
    return batch_sizes


class TestPhasedRolloutConcurrencyEnterprise:
    def try_concurrent_phased_updates(
        self, deployment, devices, user_token, expected_update_status=200
    ):
        # Static helper function
        # Setup Deployment APIs
        api_mgmt_deploy = ApiClient(deployments.URL_MGMT)
        status_codes = []

        num_phases = len(deployment["phases"])
        batch_sizes = [
            int((deployment["phases"][i]["batch_size"] / 100.0) * len(devices))
            for i in range(num_phases - 1)
        ]
        # Final batch_size might not be specified
        batch_sizes.append(len(devices) - sum(batch_sizes))

        # POST deployment
        resp = api_mgmt_deploy.with_auth(user_token).call(
            "POST", deployments.URL_DEPLOYMENTS, body=deployment
        )
        assert resp.status_code == 201

        # Store the location from the GET /deployments/{id} request
        deployment_id = os.path.basename(resp.headers["Location"])

        for i in range(num_phases):
            if i == 0 and "start_ts" not in deployment["phases"][i]:
                # First phase don't need to specify `start_ts`
                pass
            elif "start_ts" in deployment["phases"][i]:
                # Sleep until next phase starts
                start_ts = datetime.strptime(
                    deployment["phases"][i]["start_ts"], "%Y-%m-%dT%H:%M:%SZ"
                )
                now = datetime.utcnow()

                # While phase in progress:
                # Spam update requests from random batches of devices
                # concurrently by creating a pool of minimum 4 processes
                # that send requests in parallel.
                with mp.Pool(max(4, mp.cpu_count())) as pool:
                    while now <= (
                        start_ts - timedelta(milliseconds=500 * WAITING_MULTIPLIER)
                    ):
                        # NOTE: ^ add a half a second buffer time to
                        #       account for the delay in sending and
                        #       processing the request.

                        # Give the devices array a stirr
                        random.shuffle(devices)
                        # Concurrently process a batch of requests
                        device_batch = devices[: max(4, mp.cpu_count())]
                        status_codes = pool.map(try_update, device_batch)

                        # Create status code map for usefull debug
                        # message if we receive a non-empty response
                        status_code_map = {}
                        for s in [200, 204, 400, 404, 429, 500]:
                            status_code_map[s] = sum(
                                (map(lambda sc: sc == s, status_codes))
                            )
                        # Check that all requests received an empty response
                        assert (status_code_map[204] + status_code_map[429]) == len(
                            status_codes
                        ), (
                            "Expected empty response (204) during inactive "
                            + "phase, but received the following status "
                            + "code frequencies: %s" % status_code_map
                        )
                        now = datetime.utcnow()
                # Sleep the last 500ms to let the next phase start
                time.sleep(0.5 * WAITING_MULTIPLIER)
            else:
                raise ValueError(
                    "Invalid phased deployment request, "
                    "missing `start_ts` for phase %d" % i
                )

            # Make all devices attempt to update (in a concurrent manner)
            # and check that the number of successful responses equals
            # the number of devices in the batch.
            with mp.Pool(processes=max(4, mp.cpu_count())) as pool:
                status_codes = pool.map(try_update, devices)
                resp = api_mgmt_deploy.with_auth(user_token).call(
                    "GET", deployments.URL_DEPLOYMENTS_ID.format(id=deployment_id)
                )
                assert resp.status_code == 200
                phases = resp.json()["phases"]
                assert sum(map(lambda s: s == 200, status_codes)) == batch_sizes[i]

            for j in range(len(devices)):
                if status_codes[j] == 200:
                    devices[j].artifact_name = "deployments-phase-testing"

            # Check phase count equals batch size
            resp = api_mgmt_deploy.with_auth(user_token).call(
                "GET", deployments.URL_DEPLOYMENTS_ID.format(id=deployment_id)
            )
            assert resp.status_code == 200
            phases = resp.json()["phases"]
            for p in range(i + 1):
                assert phases[p]["device_count"] == batch_sizes[p]
            for p in range(i + 1, len(phases)):
                assert phases[p]["device_count"] == 0

        # Finally confirm that deployment is finished
        assert resp.json()["status"] == "finished"

    def test_two_phases_concurrent_devices(self, clean_mongo):
        """
        Two phases where devices perform requests in parallel to stress
        the backends capability of handling parallel requests.
        """
        user, tenant, utoken, devs = setup_devices_and_management_mt()
        deployment_req = {
            "name": "two-fully-spec-deployments",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {"batch_size": 10},
                {
                    "start_ts": (
                        datetime.utcnow() + timedelta(seconds=15 * WAITING_MULTIPLIER)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "batch_size": 90,
                },
            ],
        }
        self.try_concurrent_phased_updates(deployment_req, devs, utoken)


# test status update


class StatusVerifier:
    def __init__(self, deploymentsm, deploymentsd):
        self.deploymentsm = deploymentsm
        self.deploymentsd = deploymentsd

    def status_update_and_verify(
        self,
        device_id,
        device_token,
        deployment_id,
        user_token,
        status_update,
        device_deployment_status,
        deployment_status,
        status_update_error_code=204,
        substate_update="",
        substate="",
    ):

        body = {"status": status_update}
        if substate_update != "":
            body = {"status": status_update, "substate": substate_update}

        # Update device status upon successful request
        resp = self.deploymentsd.with_auth(device_token).call(
            "PUT", deployments.URL_STATUS.format(id=deployment_id), body=body,
        )
        assert resp.status_code == status_update_error_code

        self.status_verify(
            deployment_id=deployment_id,
            user_token=user_token,
            device_id=device_id,
            device_deployment_status=device_deployment_status,
            deployment_status=deployment_status,
            substate=substate,
        )

    def status_verify(
        self,
        deployment_id,
        user_token,
        device_id="",
        device_deployment_status="",
        deployment_status="",
        substate="",
    ):

        if device_deployment_status != "":
            resp = self.deploymentsm.with_auth(user_token).call(
                "GET", deployments.URL_DEPLOYMENTS_DEVICES.format(id=deployment_id)
            )
            resp.status_code == 200

            devices = resp.json()

            for device in devices:
                if device["id"] == device_id:
                    assert device["status"] == device_deployment_status

                    if substate != "":
                        assert device["substate"] == substate

        if deployment_status != "":
            resp = self.deploymentsm.with_auth(user_token).call(
                "GET", deployments.URL_DEPLOYMENTS.format(id=deployment_id)
            )
            resp.status_code == 200
            assert resp.json()[0]["status"] == deployment_status


class TestDeploymentsStatusUpdateBase:
    def do_test_deployment_status_update(
        self, clean_mongo, user_token, devs, deploy_to_group=None
    ):
        """
        deployment with four devices
        requires five devices (last one won't be part of the deployment
        """
        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        deploymentsm = ApiClient(deployments.URL_MGMT)
        deploymentsd = ApiClient(deployments.URL_DEVICES)

        status_verifier = StatusVerifier(deploymentsm, deploymentsd)

        # Make deployment request
        deployment_req = {
            "name": "phased-deployment",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs[:-1]],
        }
        if deploy_to_group:
            deployment_req = {
                "name": "phased-deployment",
                "artifact_name": "deployments-phase-testing",
                "devices": [],
                "group": deploy_to_group,
                "retries": 0,
            }

        resp = deploymentsm.with_auth(user_token).call(
            "POST", deployments.URL_DEPLOYMENTS, deployment_req
        )
        if deploy_to_group:
            resp = deploymentsm.with_auth(user_token).call(
                "POST",
                deployments.URL_DEPLOYMENTS + "/group/" + deploy_to_group,
                deployment_req,
            )

        assert resp.status_code == 201

        # Store the location from the GET /deployments/{id} request
        deployment_id = os.path.basename(resp.headers["Location"])

        # Verify that the deployment is in "pending" state
        status_verifier.status_verify(
            deployment_id=deployment_id,
            user_token=user_token,
            deployment_status="pending",
        )

        default_artifact_name = "bugs-bunny"
        default_device_type = "qemux86-64"

        # Try to retrieve next update and assert expected status code
        resp = deploymentsd.with_auth(devs[0].token).call(
            "GET",
            deployments.URL_NEXT,
            qs_params={
                "artifact_name": getattr(
                    devs[0], "artifact_name", default_artifact_name
                ),
                "device_type": getattr(devs[0], "device_type", default_device_type),
            },
        )
        assert resp.status_code == 200

        # Try to retrieve next update for the device that already has the artifact
        resp = deploymentsd.with_auth(devs[1].token).call(
            "GET",
            deployments.URL_NEXT,
            qs_params={
                "artifact_name": "deployments-phase-testing",
                "device_type": getattr(devs[1], "device_type", default_device_type),
            },
        )
        assert resp.status_code == 204
        status_verifier.status_verify(
            deployment_id=deployment_id,
            user_token=user_token,
            device_id=devs[1].id,
            device_deployment_status="already-installed",
            deployment_status="inprogress",
        )

        # Try to retrieve next update for the device with incompatible device type
        resp = deploymentsd.with_auth(devs[2].token).call(
            "GET",
            deployments.URL_NEXT,
            qs_params={
                "artifact_name": getattr(
                    devs[2], "artifact_name", default_artifact_name
                ),
                "device_type": "foo",
            },
        )
        assert resp.status_code == 204
        status_verifier.status_verify(
            deployment_id=deployment_id,
            user_token=user_token,
            device_id=devs[2].id,
            device_deployment_status="noartifact",
            deployment_status="inprogress",
        )

        # device not part of the deployment
        status_verifier.status_update_and_verify(
            device_id=devs[4].id,
            device_token=devs[4].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="installing",
            device_deployment_status="does-not-matter",
            deployment_status="inprogress",
            status_update_error_code=404,
        )

        # wrong status
        status_verifier.status_update_and_verify(
            device_id=devs[0].id,
            device_token=devs[0].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="foo",
            device_deployment_status="pending",
            deployment_status="inprogress",
            status_update_error_code=400,
        )
        # device deployment: pending -> downloading
        status_verifier.status_update_and_verify(
            device_id=devs[0].id,
            device_token=devs[0].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="downloading",
            device_deployment_status="downloading",
            deployment_status="inprogress",
        )
        # devs[0] deployment: downloading -> installing
        # substate: "" -> "foo"
        status_verifier.status_update_and_verify(
            device_id=devs[0].id,
            device_token=devs[0].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="installing",
            device_deployment_status="installing",
            deployment_status="inprogress",
            substate_update="foo",
            substate="foo",
        )
        # devs[0] deployment: installing -> downloading
        """
        note that until the device deployment is finished
        transition to any of valid statuses is correct
        """
        status_verifier.status_update_and_verify(
            device_id=devs[0].id,
            device_token=devs[0].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="downloading",
            device_deployment_status="downloading",
            deployment_status="inprogress",
            substate="foo",
        )
        # devs[0] deployment: downloading -> rebooting
        # substate: "foo" -> "bar"
        status_verifier.status_update_and_verify(
            device_id=devs[0].id,
            device_token=devs[0].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="rebooting",
            device_deployment_status="rebooting",
            deployment_status="inprogress",
            substate_update="bar",
            substate="bar",
        )
        # devs[0] deployment: rebooting -> success
        status_verifier.status_update_and_verify(
            device_id=devs[0].id,
            device_token=devs[0].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="success",
            device_deployment_status="success",
            deployment_status="inprogress",
            substate="bar",
        )
        # devs[0] deployment already finished
        status_verifier.status_update_and_verify(
            device_id=devs[0].id,
            device_token=devs[0].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="pending",
            device_deployment_status="success",
            deployment_status="inprogress",
            status_update_error_code=400,
            substate="bar",
        )

        # Try to retrieve next update and assert expected status code
        resp = deploymentsd.with_auth(devs[3].token).call(
            "GET",
            deployments.URL_NEXT,
            qs_params={
                "artifact_name": getattr(
                    devs[3], "artifact_name", default_artifact_name
                ),
                "device_type": getattr(devs[3], "device_type", default_device_type),
            },
        )
        assert resp.status_code == 200

        # device deployment: pending -> failure
        # deployment: inprogress -> finished
        status_verifier.status_update_and_verify(
            device_id=devs[3].id,
            device_token=devs[3].token,
            deployment_id=deployment_id,
            user_token=user_token,
            status_update="failure",
            device_deployment_status="failure",
            deployment_status="finished",
        )


class TestDeploymentsStatusUpdate(TestDeploymentsStatusUpdateBase):
    def test_deployment_status_update(self, clean_mongo):
        _user, user_token, devs = setup_devices_and_management_st(5)
        self.do_test_deployment_status_update(clean_mongo, user_token, devs)


class TestDeploymentsStatusUpdateEnterprise(TestDeploymentsStatusUpdateBase):
    def test_deployment_status_update(self, clean_mongo):
        _user, _tenant, user_token, devs = setup_devices_and_management_mt(5)
        self.do_test_deployment_status_update(clean_mongo, user_token, devs)


class TestDeploymentsToGroupStatusUpdate(TestDeploymentsStatusUpdateBase):
    def test_deployment_status_update(self, clean_mongo):
        _user, user_token, devs = setup_devices_and_management_st(
            5, deploy_to_group="g0"
        )
        self.do_test_deployment_status_update(
            clean_mongo, user_token, devs, deploy_to_group="g0"
        )


class TestDeploymentsToGroupStatusUpdateEnterprise(TestDeploymentsStatusUpdateBase):
    def test_deployment_status_update(self, clean_mongo):
        _user, _tenant, user_token, devs = setup_devices_and_management_mt(
            5, deploy_to_group="g0"
        )
        self.do_test_deployment_status_update(
            clean_mongo, user_token, devs, deploy_to_group="g0"
        )


def create_tenant(name, username, plan):
    tenant = create_org(name, username, "correcthorse", plan=plan)
    user = tenant.users[0]
    r = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert r.status_code == 200
    user.utoken = r.text

    return tenant


@pytest.fixture(scope="function")
def setup_tenant(clean_mongo):
    uuidv4 = str(uuid.uuid4())
    tenant = create_tenant(
        "test.mender.io-" + uuidv4, "some.user+" + uuidv4 + "@example.com", "enterprise"
    )
    # give workflows time to finish provisioning
    time.sleep(10)
    return tenant


@pytest.fixture(scope="function")
def clean_mongo_client(mongo):
    """Fixture setting up a clean (i.e. empty database). Yields
    common.MongoClient connected to the DB.

    Useful for tests with multiple testcases:
    - protects the whole test func as usual
    - but also allows calling MongoClient.cleanup() between cases
    """
    mongo_cleanup(mongo)
    yield mongo
    mongo_cleanup(mongo)


def predicate(attr, scope, t, val):
    return {"attribute": attr, "scope": scope, "type": t, "value": val}


def create_filter(name, predicates, utoken):
    f = {"name": name, "terms": predicates}

    r = (
        ApiClient(inventory_v2.URL_MGMT)
        .with_auth(utoken)
        .call("POST", inventory_v2.URL_FILTERS, f)
    )
    assert r.status_code == 201

    f["id"] = r.headers["Location"].split("/")[1]
    return f


def create_dynamic_deployment(
    name, predicates, utoken, max_devices=None, phases=None, status_code=201
):
    f = create_filter(name, predicates, utoken)

    api_dep_v2 = ApiClient(deployments_v2.URL_MGMT)

    depid = None
    with get_mender_artifact(name) as filename:

        upload_image(filename, utoken)

        deployment_req = {
            "name": name,
            "artifact_name": name,
            "filter_id": f["id"],
        }

        if max_devices is not None:
            deployment_req["max_devices"] = max_devices

        if phases is not None:
            deployment_req["phases"] = phases

        res = api_dep_v2.with_auth(utoken).call(
            "POST", deployments_v2.URL_DEPLOYMENTS, deployment_req
        )

        assert res.status_code == status_code
        if status_code != 201:
            return None

        depid = res.headers["Location"].split("/")[5]

    newdep = get_deployment(depid, utoken)

    assert newdep["name"] == name
    assert newdep["filter"]["id"] == f["id"]
    assert newdep["filter"]["terms"] == predicates
    assert newdep["status"] == "pending"
    assert newdep["dynamic"]

    return newdep


def get_deployment(depid, utoken):
    api_dep_v1 = ApiClient(deployments.URL_MGMT)
    res = api_dep_v1.with_auth(utoken).call(
        "GET", deployments.URL_DEPLOYMENTS_ID, path_params={"id": depid}
    )
    assert res.status_code == 200
    return res.json()


def update_deployment_status(deployment_id, status, token):
    api_dev_deploy = ApiClient(deployments.URL_DEVICES)

    body = {"status": status}

    resp = api_dev_deploy.with_auth(token).call(
        "PUT", deployments.URL_STATUS.format(id=deployment_id), body=body,
    )
    assert resp.status_code == 204


def assert_get_next(code, dtoken, artifact_name=None):
    api_dev_deploy = ApiClient(deployments.URL_DEVICES)

    resp = api_dev_deploy.with_auth(dtoken).call(
        "GET",
        deployments.URL_NEXT,
        qs_params={"artifact_name": "dontcare", "device_type": "arm1"},
    )

    assert resp.status_code == code
    if code == 200:
        assert resp.json()["artifact"]["artifact_name"] == artifact_name


def set_status(depid, status, dtoken):
    api_dev_deploy = ApiClient(deployments.URL_DEVICES)

    res = api_dev_deploy.with_auth(dtoken).call(
        "PUT", deployments.URL_STATUS.format(id=depid), body={"status": status},
    )

    assert res.status_code == 204


def get_stats(depid, token):
    api_dev_deploy = ApiClient(deployments.URL_MGMT)

    res = api_dev_deploy.with_auth(token).call(
        "GET", deployments.URL_DEPLOYMENTS_STATISTICS.format(id=depid),
    )

    assert res.status_code == 200
    return res.json()


def verify_stats(stats, expected):
    for k, v in stats.items():
        if k in expected:
            assert stats[k] == expected[k]
        else:
            assert stats[k] == 0


class TestDynamicDeploymentsEnterprise:
    @pytest.mark.parametrize(
        "tc",
        [
            # single predicate, $eq
            {
                "name": "single predicate, $eq",
                "predicates": [predicate("foo", "inventory", "$eq", "123")],
                "matches": [
                    [{"name": "foo", "value": "123"}],
                    [{"name": "foo", "value": "123"}, {"name": "bar", "value": "1"}],
                    [
                        {"name": "foo", "value": ["123", "qwerty"]},
                        {"name": "bar", "value": "1"},
                    ],
                ],
                "nonmatches": [
                    [{"name": "foo", "value": "1"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": 1}, {"name": "bar", "value": 123}],
                    [{"name": "baz", "value": "baz"}],
                ],
            },
            # single predicate, $ne
            {
                "name": "single predicate, $ne",
                "predicates": [predicate("foo", "inventory", "$ne", "123")],
                "matches": [
                    [{"name": "foo", "value": "1"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": 1}, {"name": "bar", "value": 123}],
                    [{"name": "baz", "value": "baz"}],
                ],
                "nonmatches": [
                    [{"name": "foo", "value": "123"}],
                    [{"name": "foo", "value": "123"}, {"name": "bar", "value": "1"}],
                    [
                        {"name": "foo", "value": ["123", "qwerty"]},
                        {"name": "bar", "value": "1"},
                    ],
                ],
            },
            # single predicate, $in
            {
                "name": "single predicate, $in",
                "predicates": [predicate("foo", "inventory", "$in", ["1", "2", "3"])],
                "matches": [
                    [{"name": "foo", "value": "1"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": "2"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": "3"}, {"name": "bar", "value": "123"}],
                ],
                "nonmatches": [
                    [{"name": "foo", "value": "4"}, {"name": "bar", "value": 123}],
                    [{"name": "foo", "value": 1}, {"name": "bar", "value": 123}],
                    [{"name": "bar", "value": "1"}],
                ],
            },
            # single predicate, $gt
            {
                "name": "single predicate, $gt",
                "predicates": [predicate("foo", "inventory", "$gt", "abc")],
                "matches": [
                    [{"name": "foo", "value": "cde"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": "def"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": "fgh"}, {"name": "bar", "value": "123"}],
                ],
                "nonmatches": [
                    [{"name": "foo", "value": "aaa"}, {"name": "bar", "value": 123}],
                    [{"name": "foo", "value": "aab"}, {"name": "bar", "value": 123}],
                    [{"name": "bar", "value": "abb"}],
                ],
            },
            # single predicate, $exists
            {
                "name": "single predicate, $exists",
                "predicates": [predicate("foo", "inventory", "$exists", True)],
                "matches": [
                    [{"name": "foo", "value": "cde"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": "def"}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": "fgh"}, {"name": "bar", "value": "123"}],
                ],
                "nonmatches": [
                    [{"name": "bar", "value": 123}],
                    [{"name": "bar", "value": 456}],
                ],
            },
            # combined predicates on single attr
            {
                "name": "combined predicates on single attr",
                "predicates": [
                    predicate("foo", "inventory", "$gte", 100),
                    predicate("foo", "inventory", "$lte", 200),
                ],
                "matches": [
                    [{"name": "foo", "value": 100}],
                    [{"name": "foo", "value": 200}, {"name": "bar", "value": "1"}],
                    [{"name": "foo", "value": 150}, {"name": "bar", "value": "1"}],
                ],
                "nonmatches": [
                    [{"name": "foo", "value": 99}, {"name": "bar", "value": "123"}],
                    [{"name": "foo", "value": 201}, {"name": "bar", "value": 123}],
                ],
            },
            # combined predicates on many attrs
            {
                "name": "combined predicates on many attrs",
                "predicates": [
                    predicate("foo", "inventory", "$eq", "foo"),
                    predicate("bar", "inventory", "$in", ["bar1", "bar2", "bar3"]),
                ],
                "matches": [
                    [{"name": "foo", "value": "foo"}, {"name": "bar", "value": "bar1"}],
                    [{"name": "foo", "value": "foo"}, {"name": "bar", "value": "bar2"}],
                    [
                        {"name": "foo", "value": ["foo"]},
                        {"name": "bar", "value": "bar3"},
                    ],
                ],
                "nonmatches": [
                    [{"name": "foo", "value": "foo"}],
                    [{"name": "foo", "value": "foo"}],
                    [{"name": "foo", "value": "bar1"}],
                ],
            },
        ],
    )
    def test_assignment_based_on_filters(self, clean_mongo_client, tc):
        """ Test basic dynamic deployments characteristic:
            - deployments match on inventory attributes via various filter predicates
        """
        uuidv4 = str(uuid.uuid4())
        tenant = create_tenant(
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "enterprise",
        )
        user = tenant.users[0]

        matching_devs = [
            make_device_with_inventory(attrs, user.utoken, tenant.tenant_token)
            for attrs in tc["matches"]
        ]
        nonmatching_devs = [
            make_device_with_inventory(attrs, user.utoken, tenant.tenant_token)
            for attrs in tc["nonmatches"]
        ]

        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        dep = create_dynamic_deployment("foo", tc["predicates"], user.utoken)
        if not useExistingTenant():
            assert dep["initial_device_count"] == len(matching_devs)

        for d in matching_devs:
            assert_get_next(200, d.token, "foo")

        for d in nonmatching_devs:
            assert_get_next(204, d.token)

    def test_unbounded_deployment_lifecycle(self, setup_tenant):
        """ Check how a dynamic deployment (no bounds) progresses through states
            based on device activity (status, statistics).
        """
        user = setup_tenant.users[0]

        dep = create_dynamic_deployment(
            "foo", [predicate("foo", "inventory", "$eq", "foo")], user.utoken
        )

        devs = [
            make_device_with_inventory(
                [{"name": "foo", "value": "foo"}],
                user.utoken,
                setup_tenant.tenant_token,
            )
            for i in range(10)
        ]

        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        for d in devs:
            assert_get_next(200, d.token, "foo")

        # just getting a 'next' deployment has no effect on overall status
        dep = get_deployment(dep["id"], user.utoken)
        assert dep["status"] == "pending"

        # when some devices start activity ('downloading', 'installing', 'rebooting'),
        # the deployment becomes 'inprogress'
        for d in devs:
            if devs.index(d) < 3:
                set_status(dep["id"], "downloading", d.token)
            elif devs.index(d) < 6:
                set_status(dep["id"], "installing", d.token)

        dep = get_deployment(dep["id"], user.utoken)
        assert dep["status"] == "inprogress"

        stats = get_stats(dep["id"], user.utoken)
        verify_stats(stats, {"downloading": 3, "installing": 3, "pending": 4})

        # when all devices finish, the deployment goes back to 'pending'
        for d in devs:
            if devs.index(d) < 5:
                set_status(dep["id"], "success", d.token)
            else:
                set_status(dep["id"], "failure", d.token)

        dep = get_deployment(dep["id"], user.utoken)
        assert dep["status"] == "inprogress"

        stats = get_stats(dep["id"], user.utoken)
        verify_stats(stats, {"success": 5, "failure": 5})

    def test_bounded_deployment_lifecycle(self, setup_tenant):
        """ Check how a dynamic deployment with max_devices progresses through states
            based on device activity (status, statistics).
        """
        user = setup_tenant.users[0]

        dep = create_dynamic_deployment(
            "foo",
            [predicate("foo", "inventory", "$eq", "foo")],
            user.utoken,
            max_devices=10,
        )

        devs = [
            make_device_with_inventory(
                [{"name": "foo", "value": "foo"}],
                user.utoken,
                setup_tenant.tenant_token,
            )
            for i in range(10)
        ]

        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        for d in devs:
            assert_get_next(200, d.token, "foo")

        # just getting a 'next' deployment has no effect on overall status
        dep = get_deployment(dep["id"], user.utoken)
        assert dep["status"] == "pending"

        # when devices start activity ('downloading', 'installing', 'rebooting'),
        # the deployment becomes 'inprogress'
        for d in devs:
            if devs.index(d) < 5:
                set_status(dep["id"], "downloading", d.token)
            else:
                set_status(dep["id"], "installing", d.token)

        dep = get_deployment(dep["id"], user.utoken)
        assert dep["status"] == "inprogress"

        stats = get_stats(dep["id"], user.utoken)
        verify_stats(stats, {"downloading": 5, "installing": 5})

        # all devices finish - and the deployment actually becomes 'finished'
        for d in devs:
            set_status(dep["id"], "success", d.token)

        dep = get_deployment(dep["id"], user.utoken)
        assert dep["status"] == "finished"

        stats = get_stats(dep["id"], user.utoken)
        verify_stats(stats, {"success": 10})

        # an extra dev won't get this deployment
        extra_dev = make_device_with_inventory(
            [{"name": "foo", "value": "foo"}], user.utoken, setup_tenant.tenant_token
        )
        assert_get_next(204, extra_dev.token, "foo")

        dep = get_deployment(dep["id"], user.utoken)
        assert dep["status"] == "finished"

        stats = get_stats(dep["id"], user.utoken)
        verify_stats(stats, {"success": 10})

    def test_deployment_ordering(self, setup_tenant):
        """ Check that devices only get dynamic deployments fresher than the
            latest one it finished.

            In other words, after updating its attributes the device won't accidentally
            fall into a deployment previous to what it tried already.
        """

        user = setup_tenant.users[0]

        create_dynamic_deployment(
            "foo1", [predicate("foo", "inventory", "$eq", "foo")], user.utoken
        )
        create_dynamic_deployment(
            "foo2", [predicate("foo", "inventory", "$eq", "foo")], user.utoken
        )
        depbar = create_dynamic_deployment(
            "bar", [predicate("foo", "inventory", "$eq", "bar")], user.utoken
        )

        # the device will ignore the 'foo' deployments, because of its inventory
        dev = make_device_with_inventory(
            [{"name": "foo", "value": "bar"}], user.utoken, setup_tenant.tenant_token
        )

        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        assert_get_next(200, dev.token, "bar")

        # when running against staging, wait 5 seconds to avoid hitting
        # the rate limits for the devices (one inventory update / 5 seconds)
        isK8S() and time.sleep(WAITING_TIME_K8S)

        # after finishing 'bar' - no other deployments qualify
        set_status(depbar["id"], "success", dev.token)
        assert_get_next(204, dev.token)

        # when running against staging, wait 5 seconds to avoid hitting
        # the rate limits for the devices (one inventory update / 5 seconds)
        isK8S() and time.sleep(WAITING_TIME_K8S)

        # after updating inventory, the device would qualify for both 'foo' deployments, but
        # the ordering mechanism will prevent it
        submit_inventory([{"name": "foo", "value": "foo"}], dev.token)

        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        assert_get_next(204, dev.token)

        # when running against staging, wait 5 seconds to avoid hitting
        # the rate limits for the devices (one inventory update / 5 seconds)
        isK8S() and time.sleep(WAITING_TIME_K8S)

        # it will however get a brand new 'foo3' deployment, because it's fresher than the finished 'bar'
        create_dynamic_deployment(
            "foo3", [predicate("foo", "inventory", "$eq", "foo")], user.utoken
        )
        create_dynamic_deployment(
            "foo4", [predicate("foo", "inventory", "$eq", "foo")], user.utoken
        )

        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        assert_get_next(200, dev.token, "foo3")

    @pytest.mark.parametrize(
        "tc",
        [
            # without max_devices
            {
                "name": "without max_devices",
                "phases": [{"batch_size": 20}, {"start_ts": None}],
                "max_devices": None,
            },
            # with max_devices
            {
                "name": "with max_devices",
                "phases": [{"batch_size": 20}, {"start_ts": None}],
                "max_devices": 10,
            },
        ],
    )
    def test_phased_rollout(self, clean_mongo_client, tc):
        """ Check phased rollouts with and without max_devices.
        """
        uuidv4 = str(uuid.uuid4())
        tenant = create_tenant(
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "enterprise",
        )
        user = tenant.users[0]

        # adjust phase start ts for previous test case duration
        # format for api consumption
        for phase in tc["phases"]:
            if "start_ts" in phase:
                phase["start_ts"] = datetime.utcnow() + timedelta(
                    seconds=15 * WAITING_MULTIPLIER
                )
                phase["start_ts"] = phase["start_ts"].strftime("%Y-%m-%dT%H:%M:%SZ")

        # a phased dynamic deployment must have an initial matching devices count
        # fails without devices
        create_dynamic_deployment(
            "foo",
            [predicate("foo", "inventory", "$eq", "foo")],
            user.utoken,
            phases=tc["phases"],
            max_devices=tc["max_devices"],
            status_code=400,
        )

        # a deployment with initial devs succeeds
        devs = [
            make_device_with_inventory(
                [{"name": "bar", "value": "bar"}], user.utoken, tenant.tenant_token,
            )
            for i in range(10)
        ]

        # sleep a few seconds waiting for the data propagation to the reporting service
        # and the Elasticsearch indexing to complete
        time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

        # adjust phase start ts for previous test case duration
        # format for api consumption
        for phase in tc["phases"]:
            if "start_ts" in phase:
                phase["start_ts"] = datetime.utcnow() + timedelta(
                    seconds=15 * WAITING_MULTIPLIER
                )
                phase["start_ts"] = phase["start_ts"].strftime("%Y-%m-%dT%H:%M:%SZ")

        dep = create_dynamic_deployment(
            "bar",
            [predicate("bar", "inventory", "$eq", "bar")],
            user.utoken,
            phases=tc["phases"],
            max_devices=tc["max_devices"],
        )
        assert dep["initial_device_count"] == 10
        assert len(dep["phases"]) == len(tc["phases"])

        # first phase is immediately on
        for d in devs[:2]:
            assert_get_next(200, d.token, "bar")
            set_status(dep["id"], "success", d.token)

        for d in devs[2:]:
            assert_get_next(204, d.token)

        # rough wait for phase 2
        time.sleep(15 * WAITING_MULTIPLIER + 1)

        for d in devs[2:]:
            assert_get_next(200, d.token, "bar")
            set_status(dep["id"], "success", d.token)

        dep = get_deployment(dep["id"], user.utoken)

        if tc["max_devices"] is None:
            # no max_devices = deployment remains in progress
            assert dep["status"] == "inprogress"
            extra_devs = [
                make_device_with_inventory(
                    [{"name": "bar", "value": "bar"}], user.utoken, tenant.tenant_token,
                )
                for i in range(10)
            ]

            # sleep a few seconds waiting for the data propagation to the reporting service
            # and the Elasticsearch indexing to complete
            time.sleep(reporting.REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS)

            for extra in extra_devs:
                assert_get_next(200, extra.token, "bar")
        else:
            # max_devices reached, so deployment is finished
            assert dep["status"] == "finished"
