import json
import logging
import pymongo
import pytest

import testutils.api.deployments as deployments
import testutils.api.deviceauth as deviceauth
import testutils.api.deviceauth_v2 as deviceauth_v2
import testutils.api.inventory as inventory
import testutils.api.useradm as useradm

from testutils.common import (
    create_org,
    create_user,
    make_accepted_device,
    mongo,
    clean_mongo,
)
from testutils.util.artifact import Artifact
from testutils.api.client import ApiClient


class UserPermission:
    def __init__(self, action, permission_type, permission_target):
        if not isinstance(action, str) and isinstance(permission_type, str):
            raise AttributeError("action and permission_type must be string type")
        self.action = action
        self.object = {"type": permission_type, "value": permission_target}


class UserRole:
    def __init__(self, name, permissions):
        self._id = name
        self.permissions = []

        if isinstance(permissions, list):
            for permission in permissions:
                if not isinstance(permission, UserPermission):
                    raise AttributeError("permissions must be a list of permissions")
                self.add_permission(permission)
        elif isinstance(permissions, UserPermission):
            self.add_permission(permissions)
        else:
            raise AttributeError("permissions must be (a list) of type UserPermission")

    def json(self):
        return json.dumps(self.__dict__)

    @property
    def dict(self):
        return self.__dict__

    def add_permission(self, permission):
        self.permissions.append(permission.__dict__)


class TestRBACDeviceGroupEnterprise:
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    def login_tenant_users(self, tenant):
        useradm_MGMT = ApiClient(useradm.URL_MGMT)
        for user in tenant.users:
            rsp = useradm_MGMT.call(
                "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
            )
            assert rsp.status_code == 200, "Failed to setup test environment"
            user.token = rsp.text

    def setup_tenant_devices(self, tenant, device_groups):
        """
        setup_user_devices authenticates the user and creates devices
        attached to (static) groups given by the proportion map from
        the groups parameter.
        :param users:     Users to setup devices for (list).
        :param n_devices: Number of accepted devices created for each
                          user (int).
        :param groups:    Map of group names to device proportions, the
                          sum of proportion must be less than or equal
                          to 1 (dict[str] = float)
        :return: Dict mapping group_name -> list(devices)
        """
        devauth_DEV = ApiClient(deviceauth.URL_DEVICES)
        devauth_MGMT = ApiClient(deviceauth_v2.URL_MGMT)
        invtry_MGMT = ApiClient(inventory.URL_MGMT)
        user = tenant.users[0]
        grouped_devices = {}
        group_cumulative = []
        group = None

        self.login_tenant_users(tenant)

        tenant.devices = []
        for group, dev_cnt in device_groups.items():
            grouped_devices[group] = []
            for i in range(dev_cnt):
                device = make_accepted_device(
                    devauth_DEV, devauth_MGMT, user.token, tenant.tenant_token
                )
                if group is not None:
                    rsp = invtry_MGMT.with_auth(user.token).call(
                        "PUT",
                        inventory.URL_DEVICE_GROUP.format(id=device.id),
                        body={"group": group},
                    )
                    assert rsp.status_code == 204

                device.group = group
                grouped_devices[group].append(device)
                tenant.devices.append(device)

        return grouped_devices

    def add_user_to_role(self, mgo_client, user, tenant_id, roles):
        """
        Ensures that the role exists and adds the user to it.
        NOTE: if creating a role to limit deployable groups, make sure to add
              another role that permits usage of the API endpoint for creating
              deployments.
        :param mgo_client: (pymongo.MongoClient)
        :param user:       the user to which the roles should be added
                           (common.User)
        :param tenant_id:  the tenant for which the user belongs (str)
        :param roles:      the (list) of roles to constrain the user
                           (UserRole or list{UserRole})
        :return: None
        """
        useradm_MGMT = ApiClient(useradm.URL_MGMT)
        if getattr(user, "token", None) is None:
            rsp = useradm_MGMT.call(
                "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
            )
            assert rsp.status_code == 200, rsp.text
            user.token = rsp.text

        if not isinstance(roles, list):
            roles = [roles]
        for role in roles:
            try:
                coll_roles = getattr(mgo_client, "useradm-%s" % tenant_id).roles
                coll_roles.insert_one(role.dict)
            except pymongo.errors.DuplicateKeyError:
                # Role already exists
                pass

        rsp = useradm_MGMT.with_auth(user.token).call(
            "PUT",
            useradm.URL_USERS_ID.format(id=user.id),
            body={"roles": [role._id for role in roles]},
        )
        assert rsp.status_code == 204, rsp.text

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "name": "Test RBAC deploy to device group",
                "user": {"name": "test1@username.org", "pwd": "password"},
                "permissions": [
                    UserPermission("CREATE_DEPLOYMENT", "DEVICE_GROUP", "test")
                ],
                "device_groups": {"test": 5, "production": 30, "staging": 20},
                "deploy_groups": ["test"],
                "status_code": 201,
            },
            {
                "name": "Test RBAC deployment forbidden",
                "user": {"name": "test2@username.org", "pwd": "password"},
                "permissions": [
                    UserPermission("CREATE_DEPLOYMENT", "DEVICE_GROUP", "test")
                ],
                "device_groups": {"test": 5, "production": 25},
                "deploy_groups": ["production"],
                "status_code": 405,
            },
            # { TODO: This test-case should pass, but deployments only
            #         expect device IDs to come from the same group
            #   "name": "Test RBAC deployment multiple device groups",
            #   "user": {"name": "test3@username.org", "pwd": "password"},
            #   "permissions": [
            #       UserPermission("CREATE_DEPLOYMENT", "DEVICE_GROUP", "test"),
            #       UserPermission("CREATE_DEPLOYMENT", "DEVICE_GROUP", "staging"),
            #   ],
            #   "device_groups": {"test": 5, "staging": 15, "production": 25},
            #   "deploy_groups": ["test", "staging"],
            #   "status_code": 201,
            # },
            {
                "name": "Test RBAC deploy to devices outside group",
                "user": {"name": "test4@username.org", "pwd": "password"},
                "permissions": [
                    UserPermission("CREATE_DEPLOYMENT", "DEVICE_GROUP", "test"),
                ],
                "device_groups": {"test": 5, "staging": 15, "production": 25},
                "deploy_groups": ["test", "staging"],
                "status_code": 405,
            },
        ],
    )
    def test_deploy_to_group(self, clean_mongo, test_case):
        """
        Tests adding group restrinction to roles and checking that users
        are not allowed to deploy to devices outside the restricted
        groups.
        """
        dplmnt_MGMT = ApiClient(deployments.URL_MGMT)

        i = 0
        self.logger.info("RUN: %s", test_case["name"])
        tenant = create_org(
            "org%d" % i, "admin%d@username.org" % i, "password", plan="enterprise"
        )
        test_user = create_user(tid=tenant.id, **test_case["user"])
        tenant.users.append(test_user)

        # Initialize tenant's devices
        grouped_devices = self.setup_tenant_devices(tenant, test_case["device_groups"])

        # Add user to deployment group
        role = UserRole("RBAC_DEVGRP", test_case["permissions"])
        self.add_user_to_role(
            clean_mongo,
            test_user,
            tenant.id,
            # Add dummy RBAC_ROLE_PERMIT_ALL - should already be
            # present in db.
            [UserRole("RBAC_ROLE_PERMIT_ALL", []), role],
        )

        # Upload a bogus artifact
        artifact = Artifact("tester", ["qemux86-64"], payload="bogus")
        rsp = dplmnt_MGMT.with_auth(test_user.token).call(
            "POST",
            deployments.URL_DEPLOYMENTS_ARTIFACTS,
            files=(
                (
                    "artifact",
                    ("artifact.mender", artifact.make(), "application/octet-stream",),
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
