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
import json
import pytest
import uuid
import os
import os.path
import time

from testutils.common import Tenant, User, update_tenant, create_user
from testutils.infra.cli import CliTenantadm
from testutils.api.client import ApiClient
import testutils.api.deviceconnect as deviceconnect
import testutils.api.deviceconfig as deviceconfig
import testutils.api.auditlogs as auditlogs
import testutils.api.useradm as useradm
import testutils.api.tenantadm as tenantadm
import testutils.api.tenantadm_v2 as tenantadm_v2
import testutils.integration.stripe as stripeutils

from testutils.common import (
    clean_mongo,
    create_org,
    mongo,
)

logger = logging.getLogger("testAccess")


def device_connect_insert_device(mongo, device_id, tenant_id, status="connected"):
    devices_collection = mongo.client["deviceconnect"]["devices"]
    devices_collection.insert_one(
        {
            "_id": device_id,
            "tenant_id": tenant_id,
            "created_ts": "2022-10-26T16:28:18.796Z",
            "status": "connected",
            "updated_ts": "2022-10-26T16:28:51.031Z",
        }
    )


def device_config_insert_device(mongo, device_id, tenant_id, status="connected"):
    devices_collection = mongo.client["deviceconfig"]["devices"]
    devices_collection.insert_one(
        {
            "_id": device_id,
            "tenant_id": tenant_id,
            "reported_ts": "2022-10-26T16:28:18.796Z",
            "updated_ts": "2022-10-26T16:28:51.031Z",
            "reported": [{"key": "timezone", "value": "UTC"}],
        }
    )


class _TestAccessBase:
    """Access checking functions.

    Probe a selected EP from every addon feature to see if it's enabled or not.
    Other endpoints are spelled out in detail in acceptance and unit tests for
    useradm/deviceauth access layers (assume they're restricted correctly as well).
    """

    # troubleshoot
    def check_access_remote_term(self, auth, devid, forbid=False):
        devconn = ApiClient(deviceconnect.URL_MGMT)

        res = devconn.with_auth(auth).call(
            "GET", deviceconnect.URL_MGMT_DEVICE, path_params={"id": devid},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok

    def check_access_file_transfer(self, auth, devid, forbid=False):
        devconn = ApiClient(deviceconnect.URL_MGMT)

        res = devconn.with_auth(auth).call(
            "GET",
            deviceconnect.URL_MGMT_FDOWNLOAD,
            path_params={"id": devid},
            qs_params={"path": "/etc/mender/mender.conf"},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.status_code == 408

        res = devconn.with_auth(auth).call(
            "PUT",
            deviceconnect.URL_MGMT_FUPLOAD,
            path_params={"id": devid},
            qs_params={"path": "/etc/mender/mender.conf"},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.status_code != 403

    def check_access_auditlogs(self, auth, forbid=False):
        alogs = ApiClient(auditlogs.URL_MGMT)

        res = alogs.with_auth(auth).call("GET", auditlogs.URL_LOGS)

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok

    def check_access_sessionlogs(self, auth, forbid=False):
        devconn = ApiClient(deviceconnect.URL_MGMT)

        res = devconn.with_auth(auth).call(
            "GET", deviceconnect.URL_MGMT_PLAYBACK, path_params={"session_id": "foo"},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.status_code != 403

    # configure
    def check_access_deviceconfig(self, auth, devid, forbid=False):
        devconf = ApiClient(deviceconfig.URL_MGMT)
        res = devconf.with_auth(auth).call(
            "GET",
            deviceconfig.URL_MGMT_DEVICE_CONFIGURATION,
            path_params={"id": devid},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok

    # rbac (no addon)
    def check_access_rbac(self, auth, forbid=False):
        uadm = ApiClient(useradm.URL_MGMT)
        res = uadm.with_auth(auth).call("GET", useradm.URL_ROLES)

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok


class TestAccess(_TestAccessBase):
    """Onprem OS.

    Quite a few addon features are available here (despite being
    hidden behind paid addons in hosted).
    """

    def test_ok(self, mongo):
        devid = str(uuid.uuid4())
        email = "mender_tests@" + str(uuid.uuid4()) + ".com"
        password = str(uuid.uuid4())
        user = create_user(email, password)
        r = ApiClient(useradm.URL_MGMT).call(
            "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
        )
        assert r.status_code == 200
        auth = r.text

        device_connect_insert_device(mongo, device_id=devid, tenant_id="")
        device_config_insert_device(mongo, device_id=devid, tenant_id="")

        self.check_access_remote_term(auth, devid)
        self.check_access_file_transfer(auth, devid)
        self.check_access_sessionlogs(auth)
        self.check_access_deviceconfig(auth, devid)


class TestAccessEnterprise(_TestAccessBase):
    """ Full enterprise setup, with HAVE_ADDONS and MT."""

    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    @pytest.fixture(scope="class")
    def mt_env(self):
        """Prepare 4 tenants across all plans (trial...enterprise) + a device each."""
        env = {"tenants": {}}

        for p in ["os", "professional", "enterprise"]:
            env["tenants"][p] = _make_tenant(p)

        env["tenants"]["trial"] = _make_trial_tenant()

        yield env

    def test_initial_restrictions(self, mongo, mt_env):
        """ Test that existing users are in fact under new addon restrictions, to incentivize addon upgrades. """

        for plan in ["os", "professional", "enterprise"]:
            tenant = mt_env["tenants"][plan]
            device_connect_insert_device(mongo, tenant.device_id, tenant_id=tenant.id)
            device_config_insert_device(mongo, tenant.device_id, tenant_id=tenant.id)
            self.check_access_remote_term(tenant.auth, tenant.device_id, forbid=True)
            self.check_access_file_transfer(tenant.auth, tenant.device_id, forbid=True)
            self.check_access_deviceconfig(tenant.auth, tenant.device_id, forbid=True)

            if plan == "enterprise":
                self.check_access_rbac(tenant.auth)
                self.check_access_auditlogs(tenant.auth, forbid=False)
                self.check_access_sessionlogs(tenant.auth)
            else:
                self.check_access_auditlogs(tenant.auth, forbid=True)
                self.check_access_sessionlogs(tenant.auth, forbid=True)

        for plan in ["trial"]:
            tenant = mt_env["tenants"][plan]
            # to actually access any RT/FT - wait for device
            device_connect_insert_device(mongo, tenant.device_id, tenant.id)
            device_config_insert_device(mongo, tenant.device_id, tenant.id)

            self.check_access_remote_term(tenant.auth, tenant.device_id)
            self.check_access_file_transfer(tenant.auth, tenant.device_id)
            self.check_access_auditlogs(tenant.auth)
            self.check_access_sessionlogs(tenant.auth)
            self.check_access_deviceconfig(tenant.auth, tenant.device_id)
            self.check_access_rbac(tenant.auth)

    @pytest.mark.skipif(
        not bool(os.environ.get("STRIPE_API_KEY")),
        reason="STRIPE_API_KEY not provided",
    )
    @pytest.mark.skip(reason="See QA-451")
    def test_upgrades(self, mongo, mt_env):
        """Test that plan/addon upgrades take effect on feature availability.
        Special case is the trial tenant upgrade to a paid plan.
        """
        tenant = mt_env["tenants"]["os"]

        # add troubleshoot
        update_tenant(
            tenant.id, addons=["troubleshoot"],
        )

        device_connect_insert_device(mongo, tenant.device_id, tenant_id=tenant.id)
        device_config_insert_device(mongo, tenant.device_id, tenant_id=tenant.id)

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth, forbid=True)
        self.check_access_sessionlogs(tenant.auth, forbid=True)
        self.check_access_deviceconfig(
            tenant.auth, tenant.device_id, forbid=True,
        )

        # add configure
        update_tenant(
            tenant.id, addons=["troubleshoot", "configure"],
        )

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_deviceconfig(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth, forbid=True)
        self.check_access_sessionlogs(tenant.auth, forbid=True)

        # upgrade to "enterprise" - makes audit, session logs and rbac available
        update_tenant(
            tenant.id, plan="enterprise",
        )

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_deviceconfig(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth)
        self.check_access_sessionlogs(tenant.auth)
        self.check_access_rbac(tenant.auth)

        # upgrade trial tenant - straight to enterprise
        tenant = mt_env["tenants"]["trial"]

        tadmm = ApiClient(tenantadm_v2.URL_MGMT)

        res = tadmm.with_auth(tenant.auth).call(
            "POST",
            tenantadm_v2.URL_TENANT_UPGRADE_START,
            path_params={"id": tenant.id},
        )

        assert res.status_code == 200
        res = res.json()

        stripeutils.confirm("pm_card_visa", res["intent_id"])

        body = {
            "plan": "enterprise",
        }

        res = tadmm.with_auth(tenant.auth).call(
            "POST",
            tenantadm_v2.URL_TENANT_UPGRADE_COMPLETE,
            path_params={"id": tenant.id},
            body=body,
        )
        assert res.status_code == 202

        update_tenant(
            tenant.id, addons=["troubleshoot", "configure"],
        )

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_deviceconfig(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth)
        self.check_access_sessionlogs(tenant.auth)
        self.check_access_rbac(tenant.auth)


def _make_tenant(plan):
    uuidv4 = str(uuid.uuid4())
    tenant, username, password = (
        "test.mender.io-" + uuidv4,
        "ci.email.tests+" + uuidv4 + "@mender.io",
        "secretsecret",
    )
    email = "ci.email.tests+" + uuidv4 + "-user2@mender.io"

    # Create tenant with two users
    tenant = create_org(tenant, username, password, plan=plan)
    tenant.users.append(create_user(email, password, tenant.id))
    update_tenant(
        tenant.id, addons=[],
    )
    r = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(email, password),
    )
    assert r.status_code == 200
    tenant.auth = r.text
    tenant.device_id = str(uuid.uuid4())
    return tenant


def _make_trial_tenant():
    uuidv4 = str(uuid.uuid4())
    tname = "test.mender.io-{}-{}".format(uuidv4, "trial")
    email = "some.user+{}@example.com".format(uuidv4)
    password = "correcthorse"

    tadmm = ApiClient(tenantadm_v2.URL_MGMT)

    args = {
        "organization": tname,
        "email": email,
        "password": password,
        "name": "foo",
        "g-recaptcha-response": "dummy",
        "plan": "enterprise",
    }

    res = tadmm.call("POST", tenantadm_v2.URL_CREATE_ORG_TRIAL, body=args,)

    assert res.status_code == 202

    tadmi = ApiClient(tenantadm.URL_INTERNAL, host=tenantadm.HOST, schema="http://")

    res = tadmi.call(
        "GET",
        tenantadm.URL_INTERNAL_TENANTS,
        qs_params={"username": email},  # urllib.parse.quote(email)}
    )

    assert res.status_code == 200
    assert len(res.json()) == 1

    api_tenant = res.json()[0]
    cli = CliTenantadm()
    tenant = cli.get_tenant(api_tenant["id"])
    tenant = json.loads(tenant)
    tenant_token = tenant["tenant_token"]

    propagate_wait_s = 2
    max_tries = 150
    tries_left = max_tries
    while tries_left > 0:
        r = ApiClient(useradm.URL_MGMT).call(
            "POST", useradm.URL_LOGIN, auth=(email, password)
        )
        if r.status_code == 200:
            logger.info(
                "_make_trial_tenant: it took %d tries to login"
                % (max_tries - tries_left + 1)
            )
            break
        time.sleep(propagate_wait_s)
        tries_left = tries_left - 1

    assert r.status_code == 200

    tenant = Tenant(tname, api_tenant["id"], tenant_token)
    u = User("", email, password)

    tenant.users.append(u)
    tenant.auth = r.text
    tenant.device_id = str(uuid.uuid4())

    return tenant
