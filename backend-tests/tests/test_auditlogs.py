# Copyright 2021 Northern.tech AS
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
import uuid
import os
import json
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import redo

from testutils.infra.cli import CliUseradm, CliTenantadm, CliDeployments
from testutils.common import (
    Device,
    Tenant,
    User,
    create_org,
    create_user,
    mongo,
    clean_mongo,
    get_mender_artifact,
    update_tenant,
    make_pending_device,
    make_device_with_inventory,
    change_authset_status,
)
from testutils.api.client import ApiClient
import testutils.api.deviceauth as deviceauth
import testutils.api.useradm as useradm
import testutils.api.inventory as inventory
import testutils.api.deployments as deployments_v1
import testutils.api.auditlogs as auditlogs


@pytest.fixture(scope="function")
def clean_migrated_mongo(clean_mongo):
    useradm_cli = CliUseradm()
    depl_cli = CliDeployments()

    useradm_cli.migrate()
    depl_cli.migrate()

    yield clean_mongo


@pytest.fixture(scope="function")
def tenant_users(clean_migrated_mongo):
    """Create test tenant with sample organization and user, log user in."""
    uuidv4 = str(uuid.uuid4())
    tenant, username, password = (
        "test.mender.io-" + uuidv4,
        "some.user+" + uuidv4 + "@example.com",
        "secretsecret",
    )
    tenant = create_org(tenant, username, password, "enterprise")
    user = create_user(
        "foo+" + uuidv4 + "@user.com", "correcthorsebatterystaple", tid=tenant.id
    )

    tenant.users.append(user)

    update_tenant(tenant.id, addons=["troubleshoot"])

    for u in tenant.users:
        r = ApiClient(useradm.URL_MGMT).call(
            "POST", useradm.URL_LOGIN, auth=(u.name, u.pwd)
        )
        assert r.status_code == 200
        assert r.text is not None
        assert r.text != ""

        u.token = r.text

    yield tenant


class TestAuditLogsEnterprise:
    def setup(self):
        self.useradmm = ApiClient(useradm.URL_MGMT)
        self.devauthd = ApiClient(deviceauth.URL_DEVICES)
        self.devauthm = ApiClient(deviceauth.URL_MGMT)
        self.alogs = ApiClient(auditlogs.URL_MGMT)

    @pytest.mark.parametrize("event_type", ["decommission", "reject"])
    def test_device_audit_log_events(self, event_type: str, tenant_users: Tenant):
        """Test if device events are loggged with correct fields."""
        user = tenant_users.users[0]
        device = make_pending_device(
            self.devauthd,
            self.devauthm,
            user.token,
            tenant_token=tenant_users.tenant_token,
        )

        if event_type == "decommission":
            response = self.devauthm.with_auth(user.token).call(
                "DELETE", deviceauth.URL_DEVICE, path_params={"id": device.id}
            )
            assert response.status_code == 204
        elif event_type == "reject":
            for auth_set in device.authsets:
                change_authset_status(
                    self.devauthm, device.id, auth_set.id, "rejected", user.token
                )
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = self.alogs.with_auth(user.token).call(
                "GET", auditlogs.URL_LOGS + "?object_type=device"
            )
            assert res.status_code == 200
            if len(res.json()) == 1:
                break
        else:
            assert False, "max GET /logs retries hit"

        expected = event_device(user, device, event_type=event_type)
        check_log(res.json()[0], expected)

    def test_deployment_create(self, tenant_users):
        """Baseline test - deployment create event is logged with correct fields."""
        user = tenant_users.users[0]

        d, _ = make_deployment(user.token, tenant_users.tenant_token)
        expected = evt_deployment_create(user, d)

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = self.alogs.with_auth(user.token).call(
                "GET", auditlogs.URL_LOGS + "?object_type=deployment"
            )
            assert res.status_code == 200
            res = res.json()
            if len(res) == 1:
                break
        else:
            assert False, "max GET /logs retries hit"

        check_log(res[0], expected)

    def test_user_create(self, tenant_users):
        user = tenant_users.users[0]

        uuidv4 = str(uuid.uuid4())
        uid = make_user(user.token, "foo+" + uuidv4 + "@acme.com", "secretsecret")
        expected = evt_user_create(user, uid, "foo+" + uuidv4 + "@acme.com")

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = self.alogs.with_auth(user.token).call("GET", auditlogs.URL_LOGS)
            assert res.status_code == 200
            res = res.json()
            if len(res) == 1:
                break
        else:
            assert False, "max GET /logs retries hit"

        check_log(res[0], expected)

    def test_user_delete(self, tenant_users):
        user = tenant_users.users[0]
        user_del = tenant_users.users[1]

        delete_user(user, user_del.id)
        expected = evt_user_delete(user, user_del)

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = self.alogs.with_auth(user.token).call("GET", auditlogs.URL_LOGS)
            assert res.status_code == 200
            res = res.json()
            if len(res) == 1:
                break
        else:
            assert False, "max GET /logs retries hit"

        check_log(res[0], expected)

    def test_user_change_role(self, tenant_users):
        user = tenant_users.users[0]
        user_change = tenant_users.users[1]

        roles = ["RBAC_ROLE_CI"]
        change_role(user.token, user_change.id, roles)
        expected = evt_change_role(user, user_change)

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = self.alogs.with_auth(user.token).call("GET", auditlogs.URL_LOGS)
            assert res.status_code == 200
            res = res.json()
            if len(res) == 1:
                break
        else:
            assert False, "max GET /logs retries hit"

        check_log(res[0], expected)

    def test_get_params(self, tenant_users):
        """Mix up some audiltog events, check GET with various params"""

        def get_auditlog_time(oid: str):
            # get exact time for filter testing
            found = None
            for _ in redo.retrier(attempts=3, sleeptime=1):
                resp = self.alogs.with_auth(tenant_users.users[0].token).call(
                    "GET", auditlogs.URL_LOGS
                )
                found = [
                    audit_log
                    for audit_log in resp.json()
                    if audit_log["object"]["id"] == oid
                ]
                if len(found) == 1:
                    return found[0]["time"]
            else:
                assert False, "max GET /logs retries hit"

        # N various events from both users
        events = []
        for i in range(10):
            uidx = i % 2
            user = tenant_users.users[uidx]

            evt = None
            evt_artifact = None
            oid = None
            if i % 3 == 0:
                uuidv4 = str(uuid.uuid4())
                uid = make_user(user.token, uuidv4 + "@acme.com", "secretsecret")
                evt = evt_user_create(user, uid, uuidv4 + "@acme.com")
                oid = uid
            else:
                d, a = make_deployment(user.token, tenant_users.tenant_token)
                evt_artifact = evt_artifact_upload(user, a)
                evt = evt_deployment_create(user, d)
                oid = d["id"]

            time.sleep(0.5)

            evt["time"] = parse_auditlog_time(get_auditlog_time(oid))
            events.append(evt)

            if evt_artifact is not None:
                evt_artifact["time"] = parse_auditlog_time(get_auditlog_time(a["id"]))
                events.append(evt_artifact)

        # default sorting is desc by time
        events = sorted(events, key=lambda x: x["time"], reverse=True)

        self._test_args_paging(tenant_users, events)
        self._test_args_actor(tenant_users, events)
        self._test_args_before_after(tenant_users, events)
        self._test_args_object(tenant_users, events)
        self._test_args_sort(tenant_users, events)

    def _test_args_paging(self, tenant_users, events):
        cases = [
            # default
            {"expected": events[:10]},
            # default, but specified
            {"page": "1", "per_page": "20", "expected": events},
            # past bounds
            {"page": "10", "expected": []},
            # >1 page, custom number
            {"page": "2", "per_page": "3", "expected": events[3:6]},
        ]

        for case in cases:
            arg = "?"
            if "page" in case:
                arg += "page=" + case["page"]
            if "per_page" in case:
                arg += "&per_page=" + case["per_page"]

            resp = self.alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + arg
            )

            assert resp.status_code == 200
            resp = resp.json()

            assert len(resp) == len(case["expected"])

            for i in range(len(resp)):
                check_log(resp[i], case["expected"][i])

    def _test_args_actor(self, tenant_users, events):
        ids = [user.id for user in tenant_users.users]
        emails = [user.name for user in tenant_users.users]

        for id in ids:
            expected = [e for e in events if e["actor"]["id"] == id]

            resp = self.alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + "?per_page=20&actor_id=" + id
            )

            assert resp.status_code == 200
            resp = resp.json()

            assert len(resp) == len(expected)
            for i in range(len(resp)):
                check_log(resp[i], expected[i])

        for email in emails:
            expected = [e for e in events if e["actor"]["email"] == email]

            resp = self.alogs.with_auth(tenant_users.users[0].token).call(
                "GET",
                auditlogs.URL_LOGS
                + "?per_page=20&actor_email="
                + urllib.parse.quote(email),
            )

            assert resp.status_code == 200
            resp = resp.json()

            assert len(resp) == len(expected)
            for i in range(len(resp)):
                check_log(resp[i], expected[i])

    def _test_args_before_after(self, tenant_users, events):
        # note events are newest first - highest idx is oldest
        cases = [
            # after first
            {"idx": len(events) - 1, "arg": "created_after"},
            # after last
            {"idx": 0, "arg": "created_after"},
            # after middle
            {"idx": int(len(events) / 2), "arg": "created_after"},
            # before first
            {"idx": len(events) - 1, "arg": "created_before"},
            # before last
            {"idx": len(events) - 1, "arg": "created_before"},
            # before middle
            {"idx": int(len(events) / 2), "arg": "created_before"},
        ]

        # compute unix timestamps for event datetimes (ms to s resolution)
        # to correctly select expected results
        for e in events:
            e["test_unix_time"] = e["time"].timestamp()

        for case in cases:
            time = events[case["idx"]]["time"]

            # round the time - must be an int on input
            time_unix = int(time.timestamp())

            resp = self.alogs.with_auth(tenant_users.users[0].token).call(
                "GET",
                "{}?per_page=20&{}={}".format(
                    auditlogs.URL_LOGS, case["arg"], time_unix
                ),
            )

            assert resp.status_code == 200
            resp = resp.json()

            if case["arg"] == "created_before":
                expected = [e for e in events if e["test_unix_time"] <= time_unix]

            if case["arg"] == "created_after":
                expected = [e for e in events if e["test_unix_time"] >= time_unix]

            assert len(resp) == len(expected)

            for i in range(len(resp)):
                check_log(resp[i], expected[i])

    def _test_args_object(self, tenant_users, events):
        expected = events[0]

        # id filter
        resp = self.alogs.with_auth(tenant_users.users[0].token).call(
            "GET",
            auditlogs.URL_LOGS + "?per_page=20&object_id=" + expected["object"]["id"],
        )

        resp = resp.json()
        assert len(resp) == 1

        for i in range(len(resp)):
            check_log(resp[0], expected)

        # type filter
        for obj_type in ["deployment"]:
            expected = [e for e in events if e["object"]["type"] == obj_type]
            resp = self.alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + "?object_type=" + obj_type
            )

            resp = resp.json()
            assert len(resp) == len(expected)

            for i in range(len(resp)):
                check_log(resp[i], expected[i])

    def _test_args_sort(self, tenant_users, events):
        cases = [
            {"arg": "desc", "expected": events},
            {"arg": "asc", "expected": events[::-1]},
        ]

        for case in cases:
            resp = self.alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + "?per_page=20&sort=" + case["arg"]
            )

            resp = resp.json()
            assert len(resp) == len(case["expected"])

            for i in range(len(resp)):
                check_log(resp[i], case["expected"][i])


def make_deployment(token: str, tenant_token: str) -> Tuple[Dict, Dict]:
    """Create sample deployment for test purposes."""
    depl_v1 = ApiClient(deployments_v1.URL_MGMT)

    uuidv4 = str(uuid.uuid4())
    artifact_name = "artifact-" + uuidv4
    name = "dep-" + uuidv4

    with get_mender_artifact(
        artifact_name=artifact_name, device_types=["arm1"],
    ) as artifact:
        r = depl_v1.with_auth(token).call(
            "POST",
            deployments_v1.URL_DEPLOYMENTS_ARTIFACTS,
            files=(
                ("description", (None, "description")),
                ("size", (None, str(os.path.getsize(artifact)))),
                (
                    "artifact",
                    (artifact, open(artifact, "rb"), "application/octet-stream"),
                ),
            ),
        )
    assert r.status_code == 201
    artifact = {"id": r.headers["Location"].rsplit("/", 1)[1]}

    # single device deployments will query the inventory service to
    # obtain the name of the groups the device belongs to; for this
    # reason, we need the device to be provisioned correctly both
    # in deviceauth and inventory
    dev = make_device_with_inventory(
        [{"name": "foo", "value": "foo"}], token, tenant_token,
    )

    request_body = {
        "name": name,
        "artifact_name": artifact_name,
        "devices": [dev.id],
    }
    resp = depl_v1.with_auth(token).call("POST", "/deployments", body=request_body)
    assert resp.status_code == 201

    depl_resp = depl_v1.with_auth(token).call("GET", "/deployments")

    depl_resp = depl_resp.json()

    found = [d for d in depl_resp if d["name"] == name]

    assert len(found) == 1
    deployment = found[0]

    return deployment, artifact


def evt_artifact_upload(user: User, artifact: Dict) -> Dict:
    """Prepare artifact upload event dictionary using sample artifact data."""
    return {
        "action": "upload",
        "actor": {"id": user.id, "type": "user", "email": user.name},
        "object": {"id": artifact["id"], "type": "artifact"},
    }


def evt_deployment_create(user: User, deployment: Dict) -> Dict:
    """Prepare test deployment creation event dictionary using deployment data."""
    return {
        "action": "create",
        "actor": {"id": user.id, "type": "user", "email": user.name},
        "object": {
            "id": deployment["id"],
            "type": "deployment",
            "deployment": {
                "name": deployment["name"],
                "artifact_name": deployment["artifact_name"],
            },
        },
    }


def event_device(user: User, device: Device, event_type: str = "decommission") -> Dict:
    """Prepare test device decommission event dictionary with user and device data."""
    return {
        "action": event_type,
        "actor": {"id": user.id, "type": "user", "email": user.name},
        "object": {
            "id": device.id,
            "type": "device",
            "device": {
                "identity_data": str(device.id_data).replace("'", '"').replace(" ", "")
            },
        },
    }


def make_user(token: str, email: str, pwd: str) -> Optional[str]:
    """Create user in useradm service with given data."""
    res = (
        ApiClient(useradm.URL_MGMT)
        .with_auth(token)
        .call("POST", useradm.URL_USERS, {"email": email, "password": pwd},)
    )
    assert res.status_code == 201
    return res.headers["Location"].split("/")[1]


def evt_user_create(actor_user: User, newid: str, email: str) -> Dict:
    """Prepare test user creation event dictionary."""
    return {
        "action": "create",
        "actor": {"id": actor_user.id, "type": "user", "email": actor_user.name},
        "object": {"id": newid, "type": "user", "user": {"email": email}},
    }


def delete_user(actor_user: User, uid: str):
    """Send request to useradm service to delete given user. """
    res = (
        ApiClient(useradm.URL_MGMT)
        .with_auth(actor_user.token)
        .call("DELETE", useradm.URL_USERS_ID, path_params={"id": uid})
    )
    assert res.status_code == 204


def evt_user_delete(actor_user: User, del_user: User) -> Dict:
    """Prepare test user delete event dictionary."""
    return {
        "action": "delete",
        "actor": {"id": actor_user.id, "type": "user", "email": actor_user.name},
        "object": {
            "id": del_user.id,
            "type": "user",
            "user": {"email": del_user.name},
        },
    }


def change_role(token: str, uid: str, roles: List[str]):
    """Send request to useradm service to change test user roles."""
    res = (
        ApiClient(useradm.URL_MGMT)
        .with_auth(token)
        .call(
            "PUT", useradm.URL_USERS_ID, path_params={"id": uid}, body={"roles": roles}
        )
    )
    assert res.status_code == 204


def evt_change_role(user: User, user_change: User) -> Dict:
    """Prepare test user role change event dictionary."""
    return {
        "action": "update",
        "actor": {"id": user.id, "type": "user", "email": user.name},
        "object": {
            "id": user_change.id,
            "type": "user",
            "user": {"email": user_change.name},
        },
        "change": "Updated user {}:\n".format(user_change.name),
    }


def check_log(log: Dict, expected: Dict):
    assert log["action"] == expected["action"]
    if "change" in expected:
        assert log["change"].startswith(expected["change"])

    for k in expected["actor"]:
        assert log["actor"][k] == expected["actor"][k]

    for k in expected["object"]:
        assert log["object"][k] == expected["object"][k]

    assert log["time"] is not None


def parse_auditlog_time(auditlog_time: str) -> datetime:
    try:
        return datetime.strptime(auditlog_time, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return datetime.strptime(auditlog_time, "%Y-%m-%dT%H:%M:%SZ")
