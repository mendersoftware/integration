import pytest
from datetime import datetime, timedelta
import time
import os
import requests
import json

import api.client
from api.client import ApiClient
import api.deviceauth as deviceauth_v1
import api.useradm as useradm
import api.inventory as inventory
from common import User, Device, Authset, Tenant, \
        create_tenant, create_tenant_user, \
        clean_mongo, mongo


# Global APIClients
deploymentclient = ApiClient(
    api.client.GATEWAY_URL + "/api/management/v1/deployments")
useradmm = ApiClient(useradm.URL_MGMT)


def upload_image(filename, auth_token, description="abc"):
    image_path_url = api.client.GATEWAY_URL + "/api/management/v1/deployments/artifacts"
    r = requests.post(
        image_path_url,
        verify=False,
        headers={"Authorization": "Bearer " + auth_token},
        files=(("description", (None, description)),
               ("size", (None, str(os.path.getsize(filename)))),
               ("artifact", (filename, open(filename, 'rb'),
                             "application/octet-stream"))))
    assert r.status_code == 201

def create_tenant_test_setup(user_name, tenant_name, nr_deployments=3, nr_devices=100):
    """
    Creates a tenant, and a user belonging to the tenant belonging to the user
    with 'nr_deployments', and 'nr_devices'
    """
    tenant = create_tenant(tenant_name)
    user = create_tenant_user(user_name, tenant)
    r = ApiClient(useradm.URL_MGMT).call(
        'POST', useradm.URL_LOGIN, auth=(user.name, user.pwd))
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
        resp = deploymentclient.with_auth(user.utoken).call(
            'POST',
            '/deployments',
            body=request_body,
        )
        assert resp.status_code == 201
    # Verify that the 'nr_deployments' expected deployments have been created
    resp = deploymentclient.with_auth(user.utoken).call('GET', '/deployments')
    assert resp.status_code == 200
    assert len(resp.json()) == nr_deployments
    return tenant


@pytest.fixture(scope='function')
def setup_deployments_enterprise_test(clean_mongo,
                                      existing_deployments=3,
                                      nr_devices=100):
    """
    Creates two tenants, with one user each, where each user has three deployments,
    and a hundred devices each.
    """
    tenant1 = create_tenant_test_setup('bugs-bunny', 'acme')
    # Add a second tenant to make sure that the functionality does not interfere with other tenants
    tenant2 = create_tenant_test_setup('road-runner', 'indiedev')
    # Create 'existing_deployments' predefined deployments to act as noise for the server to handle
    # for both users
    return tenant1, tenant2


class TestDeploymentsEndpointEnterprise(object):
    test_cases = [
        # One phase:
        #     + start_time
        #     + batch_size
        (
            {
                "name": "One phase, with start time, and full batch size",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [{
                    "start_ts": str((datetime.utcnow() +
                         timedelta(seconds=60)).isoformat("T")) + "Z",
                    "batch_size": 100,
                }],
            },
            {
                "name": "One phase, with start time, and full batch size",
                "artifact_name": "deployments-phase-testing",
                "device_count": 100,
                "phases": [{
                    "batch_size": 100
                }],
            }),
        # One phase:
        #     + start_time
        #     - batch_size
        (
            {
                "name": "One phase, with start time",
                "artifact_name": "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [{
                    "start_ts":
                    str((datetime.utcnow() +
                         timedelta(seconds=60)).isoformat("T")) + "Z",
                }],
            },
            {
                "name": "One phase, with start time",
                "artifact_name": "deployments-phase-testing",
                "device_count": 100,
            }),
        # One phase:
        #     - start_time
        #     + batch_size
        ({
            "name": "One phase, with no start time, and full batch size",
            "artifact_name": "deployments-phase-testing",
            "devices": ["dummyuuid" + str(i) for i in range(100)],
            "phases": [{
                "start_ts":
                str((datetime.utcnow() + timedelta(seconds=60)).isoformat("T")) + "Z",
                "batch_size": 100,
            }],
        }, {
            "name": "One phase, with no start time, and full batch size",
            "artifact_name": "deployments-phase-testing",
            "device_count": 100,
            "phases": [{
                "batch_size": 100
            }],
        }),
        # Two phases:
        #   first:
        #     + start_time
        #     + batch_size
        #   last:
        #     + start_time
        #     + batch_size
        ({
            "name": "Two phases, with start time and batch, last with start time and batch size",
            "artifact_name": "deployments-phase-testing",
            "devices": ["dummyuuid" + str(i) for i in range(100)],
            "phases": [{
                "start_ts":
                str((datetime.utcnow() + timedelta(seconds=60)).isoformat("T"))
                + "Z",
                "batch_size": 10,
            }, {
                "start_ts":
                str((datetime.utcnow() + timedelta(days=1)).isoformat("T")) + "Z",
                "batch_size": 90,
            }],
        }, {
            "name": "Two phases, with start time and batch, last with start time and batch size",
            "artifact_name": "deployments-phase-testing",
            "device_count": 100,
            "phases": [{
                "batch_size": 10
            }, {
                "batch_size": 90
            }],
        }),
        # Two phases:
        #   first:
        #     - start_time
        #     + batch_size
        #   last:
        #     + start_time
        #     + batch_size
        ({
            "name": "Two phases, with no start time and batch, last with start time and batch size",
            "artifact_name": "deployments-phase-testing",
            "devices": ["dummyuuid" + str(i) for i in range(100)],
            "phases": [{
                "batch_size": 10,
            }, {
                "start_ts":
                str((datetime.utcnow() + timedelta(days=1)).isoformat("T")) + "Z",
                "batch_size": 90,
            }],
        }, {
            "name": "Two phases, with no start time and batch, last with start time and batch size",
            "artifact_name": "deployments-phase-testing",
            "device_count": 100,
            "phases": [{
                "batch_size": 10
            }, {
                "batch_size": 90
            }],
        }),
        # Two phases:
        #   first:
        #     - start_time
        #     + batch_size
        #   last:
        #     + start_time
        #     - batch_size
        ({
            "name": "Two phases, with no start time and batch, last with start time",
            "artifact_name": "deployments-phase-testing",
            "devices": ["dummyuuid" + str(i) for i in range(100)],
            "phases": [{
                "batch_size": 10,
            }, {
                "start_ts":
                str((datetime.utcnow() + timedelta(days=1)).isoformat("T")) +
                "Z",
            }],
        }, {
            "name": "Two phases, with no start time and batch, last with start time",
            "artifact_name": "deployments-phase-testing",
            "device_count": 100,
            "phases": [{
                "batch_size": 10
            }, {
                "batch_size": 90
            }],
        }),
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
                        "start_time":
                        str((datetime.utcnow() +
                             timedelta(days=1)).isoformat("T")) + "Z",
                        "batch_size": 10,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=1)).isoformat("T")) + "Z",
                        "batch_size": 45,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=2)).isoformat("T")) + "Z",
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
                    {
                        "batch_size": 45,
                        "device_count": 0,
                    },
                    {
                        "batch_size": 45,
                        "device_count": 0,
                    }
                ],
            }),
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
                    {
                        "batch_size": 10,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=1)).isoformat("T")) + "Z",
                        "batch_size":
                        45,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=2)).isoformat("T")) + "Z",
                        "batch_size":
                        45,
                    },
                ],
            },
            {
                "name": "Three phases, first batch, last start and batch",
                "artifact_name": "deployments-phase-testing",
                "device_count": 100,
                "phases": [
                    {
                        "batch_size": 10,
                        "device_count": 0,
                    },
                    {
                        "batch_size": 45,
                        "device_count": 0,
                    },
                    {
                        "batch_size": 45,
                        "device_count": 0,
                    }
                ],
            }),
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
                    {
                        "batch_size": 10,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=1)).isoformat("T")) + "Z",
                        "batch_size":
                        45,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=2)).isoformat("T")) + "Z",
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
                    {
                        "batch_size": 45,
                        "device_count": 0,
                    },
                    {
                        "batch_size": 45,
                        "device_count": 0,
                    }
                ],
            }),
        # Phase, Five batches, just make sure it works. Should behave like all other > 1 cases
        (
            {
                "name":
                "Five phases, first no start time, last start time, no batch size",
                "artifact_name":
                "deployments-phase-testing",
                "devices": ["dummyuuid" + str(i) for i in range(100)],
                "phases": [
                    {
                        # Start time is optional in the first stage (default to now)
                        "batch_size": 10,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=1)).isoformat("T")) + "Z",
                        "batch_size":
                        10,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=1)).isoformat("T")) + "Z",
                        "batch_size":
                        10,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=1)).isoformat("T")) + "Z",
                        "batch_size":
                        10,
                    },
                    {
                        "start_ts":
                        str((datetime.utcnow() +
                             timedelta(days=2)).isoformat("T")) + "Z",
                        # Batch size is optional in the last stage (ie, it is the remaining devices)
                    },
                ],
            },
            {
                "name":
                "Five phases, first no start time, last start time, no batch size",
                "artifact_name":
                "deployments-phase-testing",
                "device_count":
                100,
                "phases": [{
                    "batch_size": 10,
                    "device_count": 0,
                }, {
                    "batch_size": 10,
                    "device_count": 0,
                }, {
                    "batch_size": 10,
                    "device_count": 0,
                }, {
                    "batch_size": 10,
                    "device_count": 0,
                }, {
                    "batch_size": 60,
                    "device_count": 0,
                }],
            }),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_phased_deployments_success(self, test_case,
                                        setup_deployments_enterprise_test):

        tenant1, tenant2 = setup_deployments_enterprise_test
        resp = deploymentclient.with_auth(tenant2.users[0].utoken).call('GET', '/deployments')
        assert resp.status_code == 200
        # Store the second tenants user deployemnts, to verify that
        # it remains unchanged after the tests have run
        backup_tenant_user_deployments = resp.json()
        request_body, expected_response = test_case
        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
            'POST',
            '/deployments',
            body=request_body,
        )
        assert resp.status_code == 201
        deployment_id = os.path.basename(resp.headers['Location'])
        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call('GET', '/deployments')
        assert resp.status_code == 200
        assert len(resp.json()) == 4
        # Get the test deployment from the list
        reg_response_body_dict = None
        for deployment in resp.json():
            if deployment["name"] == expected_response["name"]:
                reg_response_body_dict = deployment
        resp = deploymentclient.with_auth(tenant1.users[0].utoken).call(
            'GET', '/deployments/' + deployment_id)
        assert resp.status_code == 200
        id_response_body_dict = resp.json()
        assert reg_response_body_dict == id_response_body_dict
        TestDeploymentsEndpointEnterprise.compare_response_json(
            expected_response, id_response_body_dict)
        # Verify that the second tenant's deployemnts remain untouched
        resp = deploymentclient.with_auth(tenant2.users[0].utoken).call('GET', '/deployments')
        assert resp.status_code == 200
        assert backup_tenant_user_deployments == resp.json()


    def compare_response_json(expected_response, response_body_json):
        """Compare the keys that are present in the expected json dict with the matching response keys.
        Ignore those response keys which are not present in the expected dictionary"""
        for key in expected_response.keys() & response_body_json.keys():
            if key == "phases":
                TestDeploymentsEndpointEnterprise.compare_phases_json(
                    expected_response["phases"], response_body_json["phases"])
            else:
                assert expected_response[key] == response_body_json[key]

    def compare_phases_json(expected, response):
        """phases is a list of phases json objects. Compare them"""
        assert len(expected) == len(response)
        # The phases are a list of phase objects. Compare them on matching keys
        for exp, rsp in zip(expected, response):
            for k in exp.keys() & rsp.keys():
                assert exp[k] == rsp[k]
