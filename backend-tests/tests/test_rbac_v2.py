# Copyright 2024 Northern.tech AS
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
import uuid
import os

import testutils.api.deployments as deployments
import testutils.api.deployments_v2 as deployments_v2
import testutils.api.deviceauth as deviceauth
import testutils.api.inventory as inventory
import testutils.api.useradm as useradm
import testutils.api.deviceconfig as deviceconfig
from testutils.api import iot_manager

from testutils.common import (
    create_org,
    create_user,
    make_accepted_device,
    mongo,
    clean_mongo,
    update_tenant,
    setup_tenant_devices,
    get_mender_artifact,
)
from testutils.util.artifact import Artifact
from testutils.api.client import ApiClient


def login(user, use_personal_access_token: bool = False):
    """
    login authenticates the user and saves the user token
    within user object.
    in case of use_personal_access_token===True we first
    login with username and password, and then we request
    a personal access token which in turn is saved within
    the user object.
    """
    useradm_MGMT = ApiClient(useradm.URL_MGMT)
    rsp = useradm_MGMT.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert rsp.status_code == 200, "Failed to setup test environment"
    user.token = rsp.text

    if use_personal_access_token:
        pat_req = {"name": "my_token_0", "expires_in": 1024}
        rsp = useradm_MGMT.with_auth(user.token).call(
            "POST", useradm.URL_TOKENS, pat_req
        )
        assert (
            rsp.status_code == 200
        ), "Failed to setup test environment with personal token"
        user.token = rsp.text


def create_roles(token, roles, status_code=201):
    """
    Creates roles
    :param token: user JWT token
    :param roles:  the (list) of roles to create
    :return: None
    """
    useradm_MGMT = ApiClient(useradm.URL_MGMT_V2)
    for role in roles:
        rsp = useradm_MGMT.with_auth(token).call("POST", useradm.URL_ROLES, role)
        assert rsp.status_code == status_code


class TestRBACIoTManagerEnterprise:
    api_iot = ApiClient(base_url=iot_manager.URL_MGMT)

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC IoT manager events: RBAC_ROLE_PERMIT_ALL should be the only role to access webhook events",
                "use_personal_access_token": False,
                "user": {
                    "name": "admin-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_PERMIT_ALL"],
                },
                "roles": [],
                "status_code": 200,
            },
            {
                "name": "Test RBAC IoT manager events: RBAC_ROLE_DEPLOYMENTS_MANAGER should not be able to get webhook events",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_DEPLOYMENTS_MANAGER"],
                },
                "roles": [],
                "status_code": 403,
            },
        ],
    )
    def test_events_endpoint(self, clean_mongo, test_case):
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(tenant.users[0].token, test_case["roles"])
        test_case["user"]["name"] = test_case["user"]["name"].replace("UUID", uuidv4)
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])

        rsp = self.api_iot.with_auth(test_user.token).call(
            "GET", iot_manager.URL_EVENTS
        )
        assert rsp.status_code == test_case["status_code"]


class TestRBACv2DeploymentsEnterprise:
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC artifact download: RBAC_ROLE_DEPLOYMENTS_MANAGER should not be able to download artifact",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_DEPLOYMENTS_MANAGER"],
                },
                "roles": [],
                "status_code": 403,
            },
        ],
    )
    @pytest.mark.storage_test
    def test_download_artifact(self, clean_mongo, test_case):
        """Tests whether given role / custom role with permission sets can download an artifact."""
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(tenant.users[0].token, test_case["roles"])
        test_case["user"]["name"] = test_case["user"]["name"].replace("UUID", uuidv4)
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])

        # Create admin user so artifact can be uploaded
        admin_user_data = {
            "name": "admin-UUID@example.com",
            "pwd": "password",
            "roles": ["RBAC_ROLE_PERMIT_ALL"],
        }
        admin_user = create_user(tid=tenant.id, **admin_user_data)
        login(admin_user, test_case["use_personal_access_token"])

        # Upload a bogus artifact
        artifact = Artifact("tester", ["qemux86-64"], payload="bogus")

        dplmnt_MGMT = ApiClient(deployments.URL_MGMT)
        rsp = dplmnt_MGMT.with_auth(admin_user.token).call(
            "POST",
            deployments.URL_DEPLOYMENTS_ARTIFACTS,
            files=(
                (
                    "artifact",
                    ("artifact.mender", artifact.make(), "application/octet-stream"),
                ),
            ),
        )
        assert rsp.status_code == 201, rsp.text

        # Attempt to download artifact with test user
        artifact_id = rsp.headers["Location"].split("/")[-1]
        rsp = dplmnt_MGMT.with_auth(test_user.token).call(
            "GET", deployments.URL_DEPLOYMENTS_ARTIFACTS_DOWNLOAD.format(id=artifact_id)
        )
        assert rsp.status_code == test_case["status_code"], rsp.text
        self.logger.info("PASS: %s" % test_case["name"])

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC: single device deployment",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 1, "production": 3, "staging": 2},
                "deploy_groups": ["test"],
                "status_code": 201,
            },
            {
                "name": "Test RBAC: single device deployment with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 1, "production": 3, "staging": 2},
                "deploy_groups": ["test"],
                "status_code": 201,
            },
            {
                "name": "Test RBAC: single device deployment - forbidden",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 1, "production": 1, "staging": 1},
                "deploy_groups": ["production"],
                "status_code": 403,
            },
            {
                "name": "Test RBAC: single device deployment - forbidden with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 1, "production": 1, "staging": 1},
                "deploy_groups": ["production"],
                "status_code": 403,
            },
            {
                "name": "Test RBAC: deploy to list of devices - forbidden",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 30, "staging": 20},
                "deploy_groups": ["test"],
                "status_code": 403,
            },
            {
                "name": "Test RBAC: deploy to list of devices - forbidden with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 30, "staging": 20},
                "deploy_groups": ["test"],
                "status_code": 403,
            },
        ],
    )
    @pytest.mark.storage_test
    def test_deploy_to_devices(self, clean_mongo, test_case):
        """
        Tests adding group restriction to roles and checking that users
        are not allowed to deploy to devices by providing list of device IDs.
        The only exception is single device deployment.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(tenant.users[0].token, test_case["roles"])
        test_case["user"]["name"] = test_case["user"]["name"].replace("UUID", uuidv4)
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])

        # Initialize tenant's devices
        grouped_devices = setup_tenant_devices(tenant, test_case["device_groups"])

        # Create admin user so artifact can be uploaded
        admin_user_data = {
            "name": "admin-UUID@example.com",
            "pwd": "password",
            "roles": ["RBAC_ROLE_PERMIT_ALL"],
        }
        admin_user = create_user(tid=tenant.id, **admin_user_data)
        login(admin_user, test_case["use_personal_access_token"])

        # Upload a bogus artifact
        artifact = Artifact("tester", ["qemux86-64"], payload="bogus")

        dplmnt_MGMT = ApiClient(deployments.URL_MGMT)
        rsp = dplmnt_MGMT.with_auth(admin_user.token).call(
            "POST",
            deployments.URL_DEPLOYMENTS_ARTIFACTS,
            files=(
                (
                    "artifact",
                    ("artifact.mender", artifact.make(), "application/octet-stream"),
                ),
            ),
        )
        assert rsp.status_code == 201, rsp.text

        # Attempt to create deployment with test user
        devices = []
        for group in test_case["deploy_groups"]:
            for device in grouped_devices[group]:
                devices.append(device.id)

        rsp = dplmnt_MGMT.with_auth(test_user.token).call(
            "POST",
            deployments.URL_DEPLOYMENTS,
            body={"artifact_name": "tester", "name": "dplmnt", "devices": devices},
        )
        assert rsp.status_code == test_case["status_code"], rsp.text
        self.logger.info("PASS: %s" % test_case["name"])


class TestRBACv2DeploymentsToGroupEnterprise:
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC: deploy to group",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 3, "production": 3, "staging": 2},
                "deploy_group": "test",
                "status_code": 201,
            },
            {
                "name": "Test RBAC: deploy to group with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 3, "production": 3, "staging": 2},
                "deploy_group": "test",
                "status_code": 201,
            },
            {
                "name": "Test RBAC: deploy to group - forbidden",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 30, "staging": 20},
                "deploy_group": "production",
                "status_code": 403,
            },
            {
                "name": "Test RBAC: deploy to group - forbidden pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                            {"name": "ReadReleases",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 30, "staging": 20},
                "deploy_group": "production",
                "status_code": 403,
            },
        ],
    )
    @pytest.mark.storage_test
    def test_deploy_to_group(self, clean_mongo, test_case):
        """
        Tests adding group restriction to roles and checking that users
        are only allowed to deploy to their group.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(tenant.users[0].token, test_case["roles"])
        test_case["user"]["name"] = test_case["user"]["name"].replace("UUID", uuidv4)
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])

        # Initialize tenant's devices
        grouped_devices = setup_tenant_devices(tenant, test_case["device_groups"])

        # Upload a bogus artifact
        artifact = Artifact("tester", ["qemux86-64"], payload="bogus")

        dplmnt_MGMT = ApiClient(deployments.URL_MGMT)
        rsp = dplmnt_MGMT.with_auth(tenant.users[0].token).call(
            "POST",
            deployments.URL_DEPLOYMENTS_ARTIFACTS,
            files=(
                (
                    "artifact",
                    ("artifact.mender", artifact.make(), "application/octet-stream"),
                ),
            ),
        )
        assert rsp.status_code == 201, rsp.text

        # Attempt to create deployment with test user
        rsp = dplmnt_MGMT.with_auth(test_user.token).call(
            "POST",
            deployments.URL_DEPLOYMENTS_GROUP.format(name=test_case["deploy_group"]),
            body={"artifact_name": "tester", "name": "dplmnt"},
        )
        assert rsp.status_code == test_case["status_code"], rsp.text
        self.logger.info("PASS: %s" % test_case["name"])

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC deploy configuration to device belonging to a given group",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_PERMIT_ALL"],
                },
                "roles": [],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "test",
                "set_configuration_status_code": 204,
                "deploy_configuration_status_code": 200,
            },
            {
                "name": "Test RBAC deploy configuration to device belonging to a given group with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_PERMIT_ALL"],
                },
                "roles": [],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "test",
                "set_configuration_status_code": 204,
                "deploy_configuration_status_code": 200,
            },
            {
                "name": "Test RBAC configuration deployment forbidden",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"]},
                            }
                        ],
                    }
                ],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "test",
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
            },
            {
                "name": "Test RBAC configuration deployment forbidden for RBAC_ROLE_OBSERVER",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_OBSERVER"],
                },
                "roles": [],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "production",
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
            },
            {
                "name": "Test RBAC configuration deployment forbidden for ConfigureDevices permission set (different deploy group)",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ConfigureDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"]},
                            },
                        ],
                    }
                ],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "production",
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
            },
            {
                "name": "Test RBAC configuration deployment allowed for ConfigureDevices permission set (same deploy group)",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ConfigureDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"]},
                            },
                        ],
                    }
                ],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "test",
                "set_configuration_status_code": 204,
                "deploy_configuration_status_code": 200,
            },
            {
                "name": "Test RBAC configuration deployment forbidden pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"]},
                            },
                            {"name": "ManageTokens"},
                        ],
                    }
                ],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "production",
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
            },
            {
                "name": "Test RBAC configuration deployment forbidden",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"]},
                            }
                        ],
                    }
                ],
                "device_groups": {"test": 1, "production": 1},
                "deploy_group": "test",
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
            },
        ],
    )
    def test_set_and_deploy_configuration(self, clean_mongo, test_case):
        """
        Tests adding group restriction to roles and checking that users
        are not allowed to set and deploy configuration to devices outside the restricted
        groups.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")

        update_tenant(tenant.id, addons=["configure"])
        login(tenant.users[0], test_case["use_personal_access_token"])

        test_case["user"]["name"] = test_case["user"]["name"].replace("UUID", uuidv4)
        if test_case["roles"]:
            create_roles(tenant.users[0].token, test_case["roles"])
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])

        # Initialize tenant's devices
        grouped_devices = setup_tenant_devices(tenant, test_case["device_groups"])

        deviceconf_MGMT = ApiClient(deviceconfig.URL_MGMT)

        device_id = grouped_devices[test_case["deploy_group"]][0].id

        # Attempt to set configuration
        rsp = deviceconf_MGMT.with_auth(test_user.token).call(
            "PUT",
            deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=device_id),
            body={"foo": "bar"},
        )
        assert rsp.status_code == test_case["set_configuration_status_code"], rsp.text

        # Attempt to deploy the configuration
        rsp = deviceconf_MGMT.with_auth(test_user.token).call(
            "POST",
            deviceconfig.URL_MGMT_DEVICE_CONFIGURATION_DEPLOY.format(id=device_id),
            body={"retries": 0},
        )
        assert (
            rsp.status_code == test_case["deploy_configuration_status_code"]
        ), rsp.text
        self.logger.info("PASS: %s" % test_case["name"])

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC deploy configuration to device belonging to a given group",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_PERMIT_ALL"],
                },
                "roles": [],
                "device_groups": {"test": 1, "production": 1},
                "view_group": "test",
                "get_configuration_status_code": 200,
            },
            {
                "name": "Test RBAC deploy configuration to device belonging to a given group with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_PERMIT_ALL"],
                },
                "roles": [],
                "device_groups": {"test": 1, "production": 1},
                "view_group": "test",
                "get_configuration_status_code": 200,
            },
            {
                "name": "Test RBAC configuration deployment forbidden",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 1, "production": 1},
                "view_group": "production",
                "get_configuration_status_code": 403,
            },
            {
                "name": "Test RBAC configuration deployment forbidden with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                        ],
                    },
                ],
                "device_groups": {"test": 1, "production": 1},
                "view_group": "production",
                "get_configuration_status_code": 403,
            },
            {
                "name": "Test RBAC configuration deployment forbidden for role RBAC_ROLE_OBSERVER",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["RBAC_ROLE_OBSERVER"],
                },
                "roles": [],
                "device_groups": {"test": 1, "production": 1},
                "view_group": "production",
                "get_configuration_status_code": 403,
            },
            {
                "name": "Test RBAC GET deployment configuration allowed with ConfigureDevices permission set",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ConfigureDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 1, "production": 1},
                "view_group": "test",
                "get_configuration_status_code": 200,
            },
        ],
    )
    def test_get_configuration(self, clean_mongo, test_case):
        """
        Tests adding group restriction to roles and checking that users
        are not allowed to set and deploy configuration to devices outside the restricted
        groups.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        update_tenant(tenant.id, addons=["configure"])
        login(tenant.users[0], test_case["use_personal_access_token"])

        admin_user = tenant.users[0]
        test_case["user"]["name"] = test_case["user"]["name"].replace("UUID", uuidv4)
        if test_case["roles"]:
            create_roles(tenant.users[0].token, test_case["roles"])
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])

        # Initialize tenant's devices
        grouped_devices = setup_tenant_devices(tenant, test_case["device_groups"])

        deviceconf_MGMT = ApiClient(deviceconfig.URL_MGMT)

        device_id = grouped_devices[test_case["view_group"]][0].id

        # set the configuration using admin account
        rsp = deviceconf_MGMT.with_auth(admin_user.token).call(
            "PUT",
            deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=device_id),
            body={"foo": "bar"},
        )
        assert rsp.status_code == 204, rsp.text

        # Attempt to get configuration
        rsp = deviceconf_MGMT.with_auth(test_user.token).call(
            "GET", deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=device_id)
        )
        assert rsp.status_code == test_case["get_configuration_status_code"], rsp.text
        self.logger.info("PASS: %s" % test_case["name"])

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC access to device - read, manage, deploy",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "ManageDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 204,
                "deploy_configuration_status_code": 200,
                "get_device_status_code": 200,
                "reject_device_status_code": 204,
                "move_device_between_groups_status_code": 204,
            },
            {
                "name": "Test RBAC access to device - read, manage, deploy with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "ManageDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 204,
                "deploy_configuration_status_code": 200,
                "get_device_status_code": 200,
                "reject_device_status_code": 204,
                "move_device_between_groups_status_code": 204,
            },
            {
                "name": "Test RBAC access to device - read, manage",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "ManageDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
                "get_device_status_code": 200,
                "reject_device_status_code": 204,
                "move_device_between_groups_status_code": 204,
            },
            {
                "name": "Test RBAC access to device - read, manage with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "ManageDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
                "get_device_status_code": 200,
                "reject_device_status_code": 204,
                "move_device_between_groups_status_code": 204,
            },
            {
                "name": "Test RBAC access to device - read, deploy",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 204,
                "deploy_configuration_status_code": 200,
                "get_device_status_code": 200,
                "reject_device_status_code": 403,
                "move_device_between_groups_status_code": 403,
            },
            {
                "name": "Test RBAC access to device - read, deploy with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 204,
                "deploy_configuration_status_code": 200,
                "get_device_status_code": 200,
                "reject_device_status_code": 403,
                "move_device_between_groups_status_code": 403,
            },
            {
                "name": "Test RBAC access to device - read only",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
                "get_device_status_code": 200,
                "reject_device_status_code": 403,
                "move_device_between_groups_status_code": 403,
            },
            {
                "name": "Test RBAC access to device - read only with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "test",
                "get_configuration_status_code": 200,
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
                "get_device_status_code": 200,
                "reject_device_status_code": 403,
                "move_device_between_groups_status_code": 403,
            },
            {
                "name": "Test RBAC access to device - no access",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "ManageDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "production",
                "get_configuration_status_code": 403,
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
                "get_device_status_code": 403,
                "reject_device_status_code": 403,
                "move_device_between_groups_status_code": 403,
            },
            {
                "name": "Test RBAC access to device - no access with pat",
                "use_personal_access_token": True,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "ManageDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {
                                "name": "DeployToDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                            {"name": "ManageTokens",},
                        ],
                    },
                ],
                "device_groups": {"test": 5, "production": 5},
                "device_group": "production",
                "get_configuration_status_code": 403,
                "set_configuration_status_code": 403,
                "deploy_configuration_status_code": 403,
                "get_device_status_code": 403,
                "reject_device_status_code": 403,
                "move_device_between_groups_status_code": 403,
            },
        ],
    )
    def test_access_to_devices(self, clean_mongo, test_case):
        """
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")

        update_tenant(tenant.id, addons=["configure"])
        login(tenant.users[0], test_case["use_personal_access_token"])

        test_case["user"]["name"] = test_case["user"]["name"].replace("UUID", uuidv4)
        create_roles(tenant.users[0].token, test_case["roles"])
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])

        # Initialize tenant's devices
        grouped_devices = setup_tenant_devices(tenant, test_case["device_groups"])

        deviceconf_MGMT = ApiClient(deviceconfig.URL_MGMT)

        device_id = grouped_devices[test_case["device_group"]][0].id

        # Attempt to get configuration
        #
        # temporary use admin user's auth token until deviceconfig doesn't
        # have dedicated permissions sets
        #
        token = test_user.token
        if test_case["get_configuration_status_code"] < 300:
            token = tenant.users[0].token
        rsp = deviceconf_MGMT.with_auth(token).call(
            "GET", deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=device_id),
        )
        assert rsp.status_code == test_case["get_configuration_status_code"], rsp.text
        # Attempt to set configuration
        token = test_user.token
        if test_case["set_configuration_status_code"] < 300:
            token = tenant.users[0].token
        rsp = deviceconf_MGMT.with_auth(token).call(
            "PUT",
            deviceconfig.URL_MGMT_DEVICE_CONFIGURATION.format(id=device_id),
            body={"foo": "bar"},
        )
        assert rsp.status_code == test_case["set_configuration_status_code"], rsp.text

        # Attempt to deploy the configuration
        token = test_user.token
        if test_case["deploy_configuration_status_code"] < 300:
            token = tenant.users[0].token
        rsp = deviceconf_MGMT.with_auth(token).call(
            "POST",
            deviceconfig.URL_MGMT_DEVICE_CONFIGURATION_DEPLOY.format(id=device_id),
            body={"retries": 0},
        )
        assert (
            rsp.status_code == test_case["deploy_configuration_status_code"]
        ), rsp.text
        self.logger.info("PASS: %s" % test_case["name"])

        devauth_MGMT = ApiClient(deviceauth.URL_MGMT)
        # get device from deviceauth
        r = devauth_MGMT.with_auth(test_user.token).call(
            "GET", deviceauth.URL_DEVICE, path_params={"id": device_id}
        )
        assert r.status_code == test_case["get_device_status_code"]

        if test_case["get_device_status_code"] == 200:
            dev = r.json()
            r = devauth_MGMT.with_auth(test_user.token).call(
                "PUT",
                deviceauth.URL_AUTHSET_STATUS,
                deviceauth.req_status("rejected"),
                path_params={"did": dev["id"], "aid": dev["auth_sets"][0]["id"]},
            )
            assert r.status_code == test_case["reject_device_status_code"]

        inventory_MGMT = ApiClient(inventory.URL_MGMT)
        # get device from inventory
        r = inventory_MGMT.with_auth(test_user.token).call(
            "GET", inventory.URL_DEVICE, path_params={"id": device_id}
        )
        assert r.status_code == test_case["get_device_status_code"]

        # move device between groups
        r = inventory_MGMT.with_auth(test_user.token).call(
            "PUT",
            inventory.URL_DEVICE_GROUP,
            inventory.dev_group("production"),
            path_params={"id": device_id},
        )
        assert r.status_code == test_case["move_device_between_groups_status_code"]


class TestRBACGetEmailsByGroupEnterprise:
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "ok, admin users only",
                "use_personal_access_token": False,
                "users": [
                    {
                        "name": "test1-UUID@example.com",
                        "pwd": "password",
                        "roles": ["test"],
                    }
                ],
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                    {
                        "name": "production",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {
                                    "type": "DeviceGroups",
                                    "value": ["production"],
                                },
                            },
                        ],
                    },
                ],
                "device_groups": {"test": 3, "production": 3, "staging": 2},
                "device_group": "test",
                "status_code": 200,
                "emails_prefix": "test",
                "emails_count": 1,
            },
            {
                "name": "ok, admin users only with pat",
                "use_personal_access_token": True,
                "users": [
                    {
                        "name": "test1-UUID@example.com",
                        "pwd": "password",
                        "roles": ["test"],
                    }
                ],
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                    {
                        "name": "production",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadDevices",
                                "scope": {
                                    "type": "DeviceGroups",
                                    "value": ["production"],
                                },
                            },
                            {"name": "ManageTokens",},
                        ],
                    },
                ],
                "device_groups": {"test": 3, "production": 3, "staging": 2},
                "device_group": "test",
                "status_code": 200,
                "emails_prefix": "test",
                "emails_count": 1,
            },
        ],
    )
    def test_get_emails_by_group(self, clean_mongo, test_case):
        """
        Tests endpoint for retrieving list of users emails with access
        to devices from given group.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "admin+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(tenant.users[0].token, test_case["roles"])
        for i in range(len(test_case["users"])):
            test_case["users"][i]["name"] = test_case["users"][i]["name"].replace(
                "UUID", uuidv4
            )
            test_user = create_user(
                test_case["users"][i]["name"],
                test_case["users"][i]["pwd"],
                tid=tenant.id,
                roles=test_case["users"][i]["roles"],
            )
            tenant.users.append(test_user)

        # Initialize tenant's devices
        grouped_devices = setup_tenant_devices(tenant, test_case["device_groups"])

        device_id = grouped_devices[test_case["device_group"]][0].id

        useradm_INT = ApiClient(
            useradm.URL_INTERNAL, host=useradm.HOST, schema="http://"
        )
        rsp = useradm_INT.call(
            "GET",
            useradm.URL_EMAILS,
            path_params={"tenant_id": tenant.id, "device_id": device_id},
        )
        assert rsp.status_code == test_case["status_code"], rsp.text
        emails = rsp.json()["emails"]
        assert len(emails) == test_case["emails_count"] + 1
        for email in emails:
            assert email.startswith(test_case["emails_prefix"]) or email.startswith(
                "admin"
            )


class TestRBACReleasesEnterprise:
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "ReadReleases permission set with DeviceGroups scope",
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadReleases",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "status_code": 400,
            },
            {
                "name": "ManageReleases permission set with DeviceGroups scope",
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ManageReleases",
                                "scope": {"type": "DeviceGroups", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "status_code": 400,
            },
            {
                "name": "ReadReleases and ManageReleases permission sets with ReleaseTags scope",
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadReleases",
                                "scope": {"type": "ReleaseTags", "value": ["test"],},
                            },
                            {
                                "name": "ManageReleases",
                                "scope": {"type": "ReleaseTags", "value": ["test"],},
                            },
                        ],
                    },
                ],
                "status_code": 201,
            },
        ],
    )
    def test_create_role(self, clean_mongo, test_case):
        """
        Tests role creation with releases scope.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "admin+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(
            tenant.users[0].token,
            test_case["roles"],
            status_code=test_case["status_code"],
        )

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "single tag",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                            {
                                "name": "ManageReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                        ],
                    },
                ],
                "tags": ["foo"],
                "number_of_allwed_releases": 1,
            },
            {
                "name": "multiple tags",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                            {
                                "name": "ManageReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                        ],
                    },
                ],
                "tags": ["foo", "bar", "baz"],
                "number_of_allwed_releases": 1,
            },
        ],
    )
    def test_read_releases_and_artifacts(self, clean_mongo, test_case):
        """
        Tests access to releases with releases scope.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "admin+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(
            tenant.users[0].token, test_case["roles"], status_code=201,
        )
        # create and upload artifacts
        artifacts = (
            {"artifact_name": "foo", "device_types": ["arm1"], "size": 256},
            {"artifact_name": "bar", "device_types": ["arm1"], "size": 256},
        )
        api_client = ApiClient(deployments.URL_MGMT)
        api_client_v2 = ApiClient(deployments_v2.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(tenant.users[0].token)
        for artifact_kw in artifacts:
            with get_mender_artifact(**artifact_kw) as artifact:
                r = api_client.call(
                    "POST",
                    deployments.URL_DEPLOYMENTS_ARTIFACTS,
                    files=(
                        ("description", (None, "description")),
                        ("size", (None, str(os.path.getsize(artifact)))),
                        (
                            "artifact",
                            (
                                artifact,
                                open(artifact, "rb"),
                                "application/octet-stream",
                            ),
                        ),
                    ),
                )
            assert r.status_code == 201

        # get all releases and artifacts
        r = api_client.call("GET", deployments.URL_DEPLOYMENTS_ARTIFACTS)
        assert r.status_code == 200
        all_artifacts = r.json()
        assert len(all_artifacts) == 2

        api_client_v2.with_auth(tenant.users[0].token)
        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES)
        assert r.status_code == 200
        all_releases = r.json()
        assert len(all_releases) == 2

        # switch to user with limited access
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])
        api_client.with_auth(test_user.token)
        api_client_v2.with_auth(test_user.token)

        r = api_client.call("GET", deployments.URL_DEPLOYMENTS_ARTIFACTS)
        assert r.status_code == 200
        artifacts = r.json()
        assert len(artifacts) == 0

        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES)
        assert r.status_code == 200
        releases = r.json()
        assert len(releases) == 0

        # tag the artifact
        api_client_v2.with_auth(tenant.users[0].token)
        release_url = deployments_v2.URL_RELEASE_TAGS.replace("{release_name}", "foo")
        r = api_client_v2.call("PUT", release_url, test_case["tags"])
        assert r.status_code == 204

        # get artifacts and releases after tagging
        api_client.with_auth(test_user.token)
        api_client_v2.with_auth(test_user.token)

        r = api_client.call("GET", deployments.URL_DEPLOYMENTS_ARTIFACTS)
        assert r.status_code == 200
        artifacts = r.json()
        assert len(artifacts) == test_case["number_of_allwed_releases"]
        assert artifacts[0]["name"] == "foo"

        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES)
        assert r.status_code == 200
        releases = r.json()
        assert len(releases) == test_case["number_of_allwed_releases"]
        assert releases[0]["name"] == "foo"

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "ok",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                            {
                                "name": "ManageReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                            {"name": "DeployToDevices",},
                        ],
                    },
                ],
                "tags": ["foo", "bar"],
            },
        ],
    )
    def test_manage_releases(self, clean_mongo, test_case):
        """
        Tests access to releases with releases scope.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "admin+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(
            tenant.users[0].token, test_case["roles"], status_code=201,
        )
        # create and upload artifacts
        artifacts = (
            {"artifact_name": "foo", "device_types": ["arm1"], "size": 256},
            {"artifact_name": "bar", "device_types": ["arm1"], "size": 256},
        )
        api_client = ApiClient(deployments.URL_MGMT)
        api_client_v2 = ApiClient(deployments_v2.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(tenant.users[0].token)
        for artifact_kw in artifacts:
            with get_mender_artifact(**artifact_kw) as artifact:
                r = api_client.call(
                    "POST",
                    deployments.URL_DEPLOYMENTS_ARTIFACTS,
                    files=(
                        ("description", (None, "description")),
                        ("size", (None, str(os.path.getsize(artifact)))),
                        (
                            "artifact",
                            (
                                artifact,
                                open(artifact, "rb"),
                                "application/octet-stream",
                            ),
                        ),
                    ),
                )
            assert r.status_code == 201

        # get all releases
        api_client_v2.with_auth(tenant.users[0].token)
        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES)
        assert r.status_code == 200
        all_releases = r.json()
        assert len(all_releases) == 2

        # switch to user with limited access
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])
        api_client.with_auth(test_user.token)
        api_client_v2.with_auth(test_user.token)

        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES)
        assert r.status_code == 200
        releases = r.json()
        assert len(releases) == 0

        # tag releases
        api_client_v2.with_auth(tenant.users[0].token)
        release_url = deployments_v2.URL_RELEASE_TAGS.replace("{release_name}", "foo")
        r = api_client_v2.call("PUT", release_url, test_case["tags"])
        assert r.status_code == 204

        api_client_v2.with_auth(tenant.users[0].token)
        release_url = deployments_v2.URL_RELEASE_TAGS.replace("{release_name}", "bar")
        r = api_client_v2.call("PUT", release_url, ["tag1", "tag2"])
        assert r.status_code == 204

        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES_ALL_TAGS)
        assert r.status_code == 200
        tags = r.json()
        assert len(tags) == 4

        # switch to test user
        api_client.with_auth(test_user.token)
        api_client_v2.with_auth(test_user.token)

        # try to replace tags
        release_url = deployments_v2.URL_RELEASE_TAGS.replace("{release_name}", "foo")
        r = api_client_v2.call("PUT", release_url, ["baz", "bar"])
        assert r.status_code == 403

        # patch
        release_url = deployments_v2.URL_RELEASE.replace("{release_name}", "foo")
        r = api_client_v2.call("PATCH", release_url, {"notes": "foo bar baz"})
        assert r.status_code == 204

        release_url = deployments_v2.URL_RELEASE.replace("{release_name}", "bar")
        r = api_client_v2.call("PATCH", release_url, {"notes": "foo bar baz"})
        assert r.status_code == 404

        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES)
        assert r.status_code == 200
        releases = r.json()
        assert len(releases) == 1

        # get all tags
        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES_ALL_TAGS)
        assert r.status_code == 200
        tags = r.json()
        assert len(tags) == 2

        # create deployment
        request_body = {
            "name": "dummy-deployment",
            "artifact_name": "bar",
            "devices": ["1"],
        }
        resp = api_client.call("POST", "/deployments", body=request_body)
        assert resp.status_code == 403

        # delete release
        r = api_client_v2.call(
            "DELETE", deployments_v2.URL_RELEASES + "?name=foo&name=bar"
        )
        assert r.status_code == 204

        # get all releases and check the one test user has no access to
        # is still there
        api_client_v2.with_auth(tenant.users[0].token)
        r = api_client_v2.call("GET", deployments_v2.URL_RELEASES)
        assert r.status_code == 200
        # this list includes the demo artifact
        assert len(all_releases) == 2
        # remove the demo artifact and verify the bar release
        excluded_artifact_prefix = "mender-demo-artifact"
        all_releases = [
            x for x in r.json() if not x["name"].startswith(excluded_artifact_prefix)
        ]
        assert len(all_releases) == 1
        assert all_releases[0]["name"] == "bar"

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "ok",
                "use_personal_access_token": False,
                "user": {
                    "name": "test1-UUID@example.com",
                    "pwd": "password",
                    "roles": ["test"],
                },
                "roles": [
                    {
                        "name": "test",
                        "permission_sets_with_scope": [
                            {
                                "name": "ReadReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                            {
                                "name": "ManageReleases",
                                "scope": {"type": "ReleaseTags", "value": ["foo"],},
                            },
                        ],
                    },
                ],
                "tags": ["foo", "bar", "baz"],
                "number_of_allwed_artifacts": 1,
            },
        ],
    )
    def test_manage_artifacts(self, clean_mongo, test_case):
        """
        Tests manage artifacts with releases scope.
        """
        self.logger.info("RUN: %s", test_case["name"])

        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "admin+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, "enterprise")
        create_roles(
            tenant.users[0].token, test_case["roles"], status_code=201,
        )
        # create and upload artifacts
        artifacts = (
            {"artifact_name": "foo", "device_types": ["arm1"], "size": 256},
            {"artifact_name": "bar", "device_types": ["arm1"], "size": 256},
        )
        api_client = ApiClient(deployments.URL_MGMT)
        api_client_v2 = ApiClient(deployments_v2.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(tenant.users[0].token)
        for artifact_kw in artifacts:
            with get_mender_artifact(**artifact_kw) as artifact:
                r = api_client.call(
                    "POST",
                    deployments.URL_DEPLOYMENTS_ARTIFACTS,
                    files=(
                        ("description", (None, "description")),
                        ("size", (None, str(os.path.getsize(artifact)))),
                        (
                            "artifact",
                            (
                                artifact,
                                open(artifact, "rb"),
                                "application/octet-stream",
                            ),
                        ),
                    ),
                )
            assert r.status_code == 201

        # get all artifacts
        r = api_client.call("GET", deployments.URL_DEPLOYMENTS_ARTIFACTS)
        assert r.status_code == 200
        all_artifacts = r.json()
        assert len(all_artifacts) == 2
        foo_artifact_id = ""
        bar_artifact_id = ""
        for a in all_artifacts:
            if a["name"] == "bar":
                bar_artifact_id = a["id"]
            elif a["name"] == "foo":
                foo_artifact_id = a["id"]

        # switch to user with limited access
        test_user = create_user(tid=tenant.id, **test_case["user"])
        login(test_user, test_case["use_personal_access_token"])
        api_client.with_auth(test_user.token)
        api_client_v2.with_auth(test_user.token)

        r = api_client.call("GET", deployments.URL_DEPLOYMENTS_ARTIFACTS)
        assert r.status_code == 200
        artifacts = r.json()
        assert len(artifacts) == 0

        # tag the release
        api_client_v2.with_auth(tenant.users[0].token)
        release_url = deployments_v2.URL_RELEASE_TAGS.replace("{release_name}", "foo")
        r = api_client_v2.call("PUT", release_url, test_case["tags"])
        assert r.status_code == 204

        # get artifacts after tagging
        api_client.with_auth(test_user.token)
        api_client_v2.with_auth(test_user.token)

        r = api_client.call("GET", deployments.URL_DEPLOYMENTS_ARTIFACTS)
        assert r.status_code == 200
        artifacts = r.json()
        assert len(artifacts) == test_case["number_of_allwed_artifacts"]
        assert artifacts[0]["name"] == "foo"

        # try to upload artifact
        baz_artifact = {"artifact_name": "baz", "device_types": ["arm1"], "size": 256}
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(test_user.token)
        with get_mender_artifact(**baz_artifact) as artifact:
            r = api_client.call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS,
                files=(
                    ("description", (None, "description")),
                    ("size", (None, str(os.path.getsize(artifact)))),
                    (
                        "artifact",
                        (artifact, open(artifact, "rb"), "application/octet-stream",),
                    ),
                ),
            )
        assert r.status_code == 403

        # direct upload
        r = api_client.call(
            "POST", deployments.URL_DEPLOYMENTS_ARTIFACTS_DIRECT_UPLOAD,
        )
        assert r.status_code == 403

        # generate
        r = api_client.call("POST", deployments.URL_DEPLOYMENTS_ARTIFACTS_GENERATE,)
        assert r.status_code == 403

        # get by id
        r = api_client.call(
            "GET",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace("{id}", foo_artifact_id),
        )
        assert r.status_code == 200

        r = api_client.call(
            "GET",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace("{id}", bar_artifact_id),
        )
        assert r.status_code == 404

        # put
        r = api_client.call(
            "PUT",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace("{id}", foo_artifact_id),
            {"description": "foo"},
        )
        assert r.status_code == 204

        r = api_client.call(
            "PUT",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace("{id}", bar_artifact_id),
            {"description": "foo"},
        )
        assert r.status_code == 404

        # download
        r = api_client.call(
            "GET",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_DOWNLOAD.replace(
                "{id}", foo_artifact_id
            ),
        )
        assert r.status_code == 200

        r = api_client.call(
            "GET",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_DOWNLOAD.replace(
                "{id}", bar_artifact_id
            ),
        )
        assert r.status_code == 404

        # delete
        r = api_client.call(
            "DELETE",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace("{id}", foo_artifact_id),
        )
        assert r.status_code == 204

        r = api_client.call(
            "DELETE",
            deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace("{id}", bar_artifact_id),
        )
        assert r.status_code == 404
