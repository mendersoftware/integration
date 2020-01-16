import pytest
import multiprocessing as mp
import logging
import os
import requests
import random
import time
import testutils.util.crypto

from datetime import datetime, timedelta

import testutils.api.client
import testutils.api.deviceauth as deviceauth_v1
import testutils.api.deviceauth_v2 as deviceauth_v2
import testutils.api.useradm as useradm
import testutils.api.inventory as inventory
import testutils.api.deployments as deployments

from testutils.api.client import ApiClient
from testutils.common import (
    User,
    Device,
    Authset,
    Tenant,
    create_org,
    create_authset,
    change_authset_status,
    clean_mongo,
    mongo,
)


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


def create_tenant_test_setup(user_name, tenant_name, nr_deployments=3, nr_devices=100):
    """
    Creates a tenant, and a user belonging to the tenant
    with 'nr_deployments', and 'nr_devices'
    """
    api_mgmt_deploy = ApiClient(deployments.URL_MGMT)
    tenant = create_org(tenant_name, user_name, "correcthorse")
    user = tenant.users[0]
    r = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert r.status_code == 200
    user.utoken = r.text
    tenant.users = [user]
    upload_image("/tests/test-artifact.mender", user.utoken)
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
    assert len(resp.json()) == nr_deployments
    return tenant


@pytest.fixture(scope="function")
def setup_deployments_enterprise_test(
    clean_mongo, existing_deployments=3, nr_devices=100
):
    """
    Creates two tenants, with one user each, where each user has three deployments,
    and a hundred devices each.
    """
    tenant1 = create_tenant_test_setup("bugs@bunny.org", "acme")
    # Add a second tenant to make sure that the functionality does not interfere with other tenants
    tenant2 = create_tenant_test_setup("road@runner.org", "indiedev")
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
                "device_count": 100,
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
        # Store the second tenants user deployemnts, to verify that
        # it remains unchanged after the tests have run
        backup_tenant_user_deployments = resp.json()
        request_body, expected_response = test_case
        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
            "POST", "/deployments", body=request_body
        )
        assert resp.status_code == 201
        deployment_id = os.path.basename(resp.headers["Location"])
        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
            "GET", "/deployments"
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 4
        # Get the test deployment from the list
        reg_response_body_dict = None
        for deployment in resp.json():
            if deployment["name"] == expected_response["name"]:
                reg_response_body_dict = deployment
        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
            "GET", "/deployments/" + deployment_id
        )
        assert resp.status_code == 200
        id_response_body_dict = resp.json()
        assert reg_response_body_dict == id_response_body_dict
        TestDeploymentsEndpointEnterprise.compare_response_json(
            expected_response, id_response_body_dict
        )
        # Verify that the second tenant's deployemnts remain untouched
        resp = deploymentclient.with_auth(tenant2.users[0].utoken).call(
            "GET", "/deployments"
        )
        assert resp.status_code == 200
        assert backup_tenant_user_deployments == resp.json()

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


def setup_devices_and_management(nr_devices=100):
    """
    Sets up user and tenant and creates authorized devices.
    """
    tenant = create_org("acme", "bugs@bunny.org", "correcthorse")
    user = tenant.users[0]
    useradmm = ApiClient(useradm.URL_MGMT)
    devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
    invm = ApiClient(inventory.URL_MGMT)
    api_mgmt_deploy = ApiClient(deployments.URL_MGMT)
    # log in user
    r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert r.status_code == 200
    utoken = r.text
    # Upload a dummy artifact to the server
    upload_image("/tests/test-artifact.mender", utoken)
    # prepare accepted devices
    devs = make_accepted_devices(utoken, devauthd, nr_devices, tenant.tenant_token)
    # wait for devices to be provisioned
    time.sleep(3)

    # Check that the number of devices were created
    r = invm.with_auth(utoken).call(
        "GET", inventory.URL_DEVICES, qs_params={"per_page": nr_devices}
    )
    assert r.status_code == 200
    api_devs = r.json()
    assert len(api_devs) == nr_devices

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


class TestDeploymentsEnterprise(object):
    def test_regular_deployment(self, clean_mongo):
        user, tenant, utoken, devs = setup_devices_and_management()

        api_mgmt_dep = ApiClient(deployments.URL_MGMT)

        # Make deployment request
        deployment_req = {
            "name": "phased-deployment",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
        }
        api_mgmt_dep.with_auth(utoken).call(
            "POST", deployments.URL_DEPLOYMENTS, deployment_req
        )

        for dev in devs:
            status_code = try_update(dev)
            assert status_code == 200
            dev.artifact_name = deployment_req["artifact_name"]

        for dev in devs:
            # Deployment already finished
            status_code = try_update(dev)
            assert status_code == 204

        deployment_req["name"] = "really-old-update"
        api_mgmt_dep.with_auth(utoken).call(
            "POST", deployments.URL_DEPLOYMENTS, deployment_req
        )
        for dev in devs:
            # Already installed
            status_code = try_update(dev)
            assert status_code == 204


class TestPhasedRolloutDeploymentsEnterprise:
    def try_phased_updates(
        self, deployment, devices, user_token, expected_update_status=200
    ):
        ### Static helper function ###
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
                wait_time = start_ts - now

                # While phase in progress
                # NOTE: add a half a second buffer time, as a just-in-time
                #       request will break the remainder of the test
                while now < (start_ts - timedelta(milliseconds=500)):
                    # Spam update requests from random non-updated devices
                    dev = random.choice(devices)
                    status_code = try_update(dev)
                    assert status_code == 204
                    now = datetime.utcnow()
                # Sleep the last 500ms to let the next phase start
                time.sleep(0.5)
            else:
                raise ValueError(
                    "Invalid phased deployment request, "
                    "missing `start_ts` for phase %d" % i
                )

            ### Test for all devices in the deployment ###
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
        user, tenant, utoken, devs = setup_devices_and_management()

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
        user, tenant, utoken, devs = setup_devices_and_management()

        deployment_req = {
            "name": "phased-delayed-deployment",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=15)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                }
            ],
        }
        self.try_phased_updates(deployment_req, devs, utoken)

    def test_two_phases_full_spec(self, clean_mongo):
        """
        Two phases, with batch_size and start_ts specified for both phases.
        """
        user, tenant, utoken, devs = setup_devices_and_management()
        deployment_req = {
            "name": "two-fully-spec-deployments",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {
                    "batch_size": 10,
                    "start_ts": (datetime.utcnow() + timedelta(seconds=15)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                },
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=30)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "batch_size": 90,
                },
            ],
        }
        self.try_phased_updates(deployment_req, devs, utoken)

    def test_three_phased_deployments(self, clean_mongo):
        """
        Three phases; with no start_ts in first and no batch_size in third.
        """
        user, tenant, utoken, devs = setup_devices_and_management(nr_devices=101)

        deployment_req = {
            "name": "three-phased-deployments",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {"batch_size": 13},
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=15)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "batch_size": 17,
                },
                {
                    "batch_size": 29,
                    "start_ts": (datetime.utcnow() + timedelta(seconds=30)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                },
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=45)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                },
            ],
        }
        self.try_phased_updates(deployment_req, devs, utoken)

    def test_disallow_empty_phase(self, clean_mongo):
        """
        Test that in the case a batch is empty due to rounding errors,
        the server returns 400, with an appropriate error message.
        """

        user, tenant, utoken, devs = setup_devices_and_management(nr_devices=101)

        deployment_req = {
            "name": "empty-batch-test",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs[:11]],
            "phases": [
                {"batch_size": 10},
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=15)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "batch_size": 20,
                },
                {
                    "batch_size": 5,
                    "start_ts": (datetime.utcnow() + timedelta(seconds=30)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                },
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=45)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
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
        user, tenant, utoken, devs = setup_devices_and_management(nr_devices=101)

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
                    "start_ts": (datetime.utcnow() + timedelta(seconds=15)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                },
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=30)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
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
        ### Static helper function ###
        # Setup Deployment APIs
        api_mgmt_deploy = ApiClient(deployments.URL_MGMT)
        status_codes = []

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
                wait_time = start_ts - now

                # While phase in progress:
                # Spam update requests from random batches of devices
                # concurrently by creating a pool of minimum 4 processes
                # that send requests in parallel.
                with mp.Pool(max(4, mp.cpu_count())) as pool:
                    while now <= (start_ts - timedelta(milliseconds=500)):
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
                        for s in [200, 204, 400, 404, 500]:
                            status_code_map[s] = sum(
                                (map(lambda sc: sc == s, status_codes))
                            )
                        # Check that all requests received an empty response
                        assert (
                            status_code_map[204] == len(status_codes),
                            "Expected empty response (204) during inactive "
                            + "phase, but received the following status "
                            + "code frequencies: %s" % status_code_map,
                        )
                        now = datetime.utcnow()
                # Sleep the last 500ms to let the next phase start
                time.sleep(0.5)
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
        user, tenant, utoken, devs = setup_devices_and_management()
        deployment_req = {
            "name": "two-fully-spec-deployments",
            "artifact_name": "deployments-phase-testing",
            "devices": [dev.id for dev in devs],
            "phases": [
                {"batch_size": 10},
                {
                    "start_ts": (datetime.utcnow() + timedelta(seconds=15)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "batch_size": 90,
                },
            ],
        }
        self.try_concurrent_phased_updates(deployment_req, devs, utoken)
