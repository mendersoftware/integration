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

import pytest
import uuid
import os
import json
import time
from datetime import datetime
import urllib.parse

import redo

from testutils.infra.cli import CliUseradm, CliTenantadm, CliDeployments
from testutils.common import (
    create_org,
    create_user,
    mongo,
    clean_mongo,
    get_mender_artifact,
)
from testutils.api.client import ApiClient
import testutils.api.useradm as useradm
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
    uuidv4 = str(uuid.uuid4())
    tenant, username, password = (
        "test.mender.io-" + uuidv4,
        "some.user+" + uuidv4 + "@example.com",
        "secretsecret",
    )
    tenant = create_org(tenant, username, password, "enterprise")
    user = create_user("foo@user.com", "correcthorsebatterystaple", tid=tenant.id)

    tenant.users.append(user)

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
    def test_deployment_create(self, tenant_users):
        """ Baseline test - deployment create event is logged with correct fields."""
        user = tenant_users.users[0]

        d = make_deployment(user.token)
        expected = evt_deployment_create(user, d)

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            alogs = ApiClient(auditlogs.URL_MGMT)
            res = alogs.with_auth(user.token).call("GET", auditlogs.URL_LOGS)
            assert res.status_code == 200
            res = res.json()
            if len(res) == 1:
                break
        else:
            assert False, "max GET /logs retries hit"

        check_log(res[0], expected)

    def test_user_create(self, tenant_users):
        user = tenant_users.users[0]

        alogs = ApiClient(auditlogs.URL_MGMT)

        uid = make_user(user.token, "foo@acme.com", "secretsecret")
        expected = evt_user_create(user, uid, "foo@acme.com")

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = alogs.with_auth(user.token).call("GET", auditlogs.URL_LOGS)
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

        alogs = ApiClient(auditlogs.URL_MGMT)

        delete_user(user, user_del.id)
        expected = evt_user_delete(user, user_del)

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = alogs.with_auth(user.token).call("GET", auditlogs.URL_LOGS)
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

        alogs = ApiClient(auditlogs.URL_MGMT)

        roles = ["RBAC_ROLE_CI"]
        change_role(user.token, user_change.id, roles)
        expected = evt_change_role(user, user_change, roles)

        res = None
        for _ in redo.retrier(attempts=3, sleeptime=1):
            res = alogs.with_auth(user.token).call("GET", auditlogs.URL_LOGS)
            assert res.status_code == 200
            res = res.json()
            if len(res) == 1:
                break
        else:
            assert False, "max GET /logs retries hit"

        check_log(res[0], expected)

    def test_get_params(self, tenant_users):
        """ Mix up some audiltog events, check GET with various params """

        # N various events from both users
        events = []
        for i in range(10):
            uidx = i % 2
            user = tenant_users.users[uidx]

            evt = None
            oid = None
            if i % 3 == 0:
                uuidv4 = str(uuid.uuid4())
                uid = make_user(user.token, uuidv4 + "@acme.com", "secretsecret")
                evt = evt_user_create(user, uid, uuidv4 + "@acme.com")
                oid = uid
            else:
                d = make_deployment(user.token)
                evt = evt_deployment_create(user, d)
                oid = d["id"]

            time.sleep(0.5)

            # get exact time for filter testing
            found = None
            for _ in redo.retrier(attempts=3, sleeptime=1):
                alogs = ApiClient(auditlogs.URL_MGMT)
                resp = alogs.with_auth(tenant_users.users[0].token).call(
                    "GET", auditlogs.URL_LOGS
                )
                resp = resp.json()
                found = [e for e in resp if e["object"]["id"] == oid]
                if len(found) == 1:
                    break
            else:
                assert False, "max GET /logs retries hit"

            evt["time"] = found[0]["time"]

            events.append(evt)

        # default sorting is desc by time
        events.reverse()

        self._test_args_paging(tenant_users, events)
        self._test_args_actor(tenant_users, events)
        self._test_args_before_after(tenant_users, events)
        self._test_args_object(tenant_users, events)

    def _test_args_paging(self, tenant_users, events):
        alogs = ApiClient(auditlogs.URL_MGMT)

        cases = [
            # default
            {"expected": events},
            # default, but specified
            {"page": "1", "per_page": "20", "expected": events},
            # past bounds
            {"page": "2", "expected": []},
            # >1 page, custom number
            {"page": "2", "per_page": "3", "expected": events[3:6]},
        ]

        for case in cases:
            arg = "?"
            if "page" in case:
                arg += "page=" + case["page"]
            if "per_page" in case:
                arg += "&per_page=" + case["per_page"]

            resp = alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + arg
            )

            assert resp.status_code == 200
            resp = resp.json()

            assert len(resp) == len(case["expected"])

            for i in range(len(resp)):
                check_log(resp[i], case["expected"][i])

    def _test_args_actor(self, tenant_users, events):
        alogs = ApiClient(auditlogs.URL_MGMT)

        ids = [user.id for user in tenant_users.users]
        emails = [user.name for user in tenant_users.users]

        for id in ids:
            expected = [e for e in events if e["actor"]["id"] == id]

            resp = alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + "?actor_id=" + id
            )

            assert resp.status_code == 200
            resp = resp.json()

            assert len(resp) == len(expected)
            for i in range(len(resp)):
                check_log(resp[i], expected[i])

        for email in emails:
            expected = [e for e in events if e["actor"]["email"] == email]

            resp = alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + "?actor_email=" + urllib.parse.quote(email)
            )

            assert resp.status_code == 200
            resp = resp.json()

            assert len(resp) == len(expected)
            for i in range(len(resp)):
                check_log(resp[i], expected[i])

    def _test_args_before_after(self, tenant_users, events):
        alogs = ApiClient(auditlogs.URL_MGMT)

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
            e["test_unix_time"] = datetime.strptime(
                e["time"], "%Y-%m-%dT%H:%M:%S.%fZ"
            ).timestamp()

        for case in cases:
            time = events[case["idx"]]["time"]

            # round the time - must be an int on input
            time_unix = int(
                datetime.strptime(time, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()
            )

            resp = alogs.with_auth(tenant_users.users[0].token).call(
                "GET", "{}?{}={}".format(auditlogs.URL_LOGS, case["arg"], time_unix)
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
        alogs = ApiClient(auditlogs.URL_MGMT)

        expected = events[0]

        # id filter
        resp = alogs.with_auth(tenant_users.users[0].token).call(
            "GET", auditlogs.URL_LOGS + "?object_id=" + expected["object"]["id"]
        )

        resp = resp.json()
        assert len(resp) == 1

        for i in range(len(resp)):
            check_log(resp[0], expected)

        # type filter
        for obj_type in ["deployment"]:
            expected = [e for e in events if e["object"]["type"] == obj_type]
            resp = alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + "?object_type=" + obj_type
            )

            resp = resp.json()
            assert len(resp) == len(expected)

            for i in range(len(resp)):
                check_log(resp[i], expected[i])

    def _test_args_sort(self, tenant_users, events):
        alogs = ApiClient(auditlogs.URL_MGMT)
        cases = [
            {"arg": "desc", "expected": events},
            {"arg": "asc", "expected": events[::-1]},
        ]

        for case in cases:
            resp = alogs.with_auth(tenant_users.users[0].token).call(
                "GET", auditlogs.URL_LOGS + "?sort=" + case["arg"]
            )

            resp = resp.json()
            assert len(resp) == len(expected)

            for i in range(len(resp)):
                check_log(resp[i], expected[i])


def make_deployment(token):
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

    request_body = {
        "name": name,
        "artifact_name": artifact_name,
        "devices": ["arm1"],
    }
    resp = depl_v1.with_auth(token).call("POST", "/deployments", body=request_body)
    assert resp.status_code == 201

    depl_resp = depl_v1.with_auth(token).call("GET", "/deployments")

    depl_resp = depl_resp.json()

    found = [d for d in depl_resp if d["name"] == name]

    assert len(found) == 1

    return found[0]


def evt_deployment_create(user, deployment):
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


def make_user(token, email, pwd):
    res = (
        ApiClient(useradm.URL_MGMT)
        .with_auth(token)
        .call("POST", useradm.URL_USERS, {"email": email, "password": pwd},)
    )
    assert res.status_code == 201
    return res.headers["Location"].split("/")[1]


def evt_user_create(actor_user, newid, email):
    return {
        "action": "create",
        "actor": {"id": actor_user.id, "type": "user", "email": actor_user.name},
        "object": {"id": newid, "type": "user", "user": {"email": email},},
    }


def delete_user(actor_user, uid):
    res = (
        ApiClient(useradm.URL_MGMT)
        .with_auth(actor_user.token)
        .call("DELETE", useradm.URL_USERS_ID, path_params={"id": uid})
    )
    assert res.status_code == 204


def evt_user_delete(actor_user, del_user):
    return {
        "action": "delete",
        "actor": {"id": actor_user.id, "type": "user", "email": actor_user.name},
        "object": {
            "id": del_user.id,
            "type": "user",
            "user": {"email": del_user.name},
        },
    }


def change_role(token, uid, roles):
    res = (
        ApiClient(useradm.URL_MGMT)
        .with_auth(token)
        .call(
            "PUT", useradm.URL_USERS_ID, path_params={"id": uid}, body={"roles": roles}
        )
    )
    assert res.status_code == 204


def evt_change_role(user, user_change, roles):
    update = {"roles": roles}
    return {
        "action": "update",
        "actor": {"id": user.id, "type": "user", "email": user.name},
        "object": {
            "id": user_change.id,
            "type": "user",
            "user": {"email": user_change.name},
        },
        "change": "Updated user {}:\n{}".format(user_change.id, go_dict_str(update)),
    }


def check_log(log, expected):
    assert log["action"] == expected["action"]
    if "change" in expected:
        assert log["change"] == expected["change"]

    for k in expected["actor"]:
        assert log["actor"][k] == expected["actor"][k]

    for k in expected["object"]:
        assert log["object"][k] == expected["object"][k]

    assert log["time"] is not None


def go_dict_str(d):
    """Account for dict encoding diffs between go/py"""
    djson = json.dumps(d)

    return djson.replace(" ", "")
