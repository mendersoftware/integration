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
import json
import pytest
import uuid

from testutils.common import Tenant, User, update_tenant, new_tenant_client
from testutils.infra.cli import CliTenantadm
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.api.client import ApiClient
import testutils.api.deviceconnect as deviceconnect
import testutils.api.deviceconfig as deviceconfig
import testutils.api.auditlogs as auditlogs
import testutils.api.useradm as useradm
import testutils.api.tenantadm as tenantadm
import testutils.api.tenantadm_v2 as tenantadm_v2
import testutils.integration.stripe as stripeutils

from ..common_setup import (
    enterprise_no_client_class,
    standard_setup_one_client,
)
from .common_connect import wait_for_connect
from ..MenderAPI import (
    auth,
    devauth,
    DeviceAuthV2,
    Authentication,
    get_container_manager,
)


class _TestAccessBase:
    """Access checking functions.

    Probe a selected EP from every addon feature to see if it's enabled or not.
    Other endpoints are spelled out in detail in acceptance and unit tests for
    useradm/deviceauth access layers (assume they're restricted correctly as well).
    """

    # troubleshoot
    def check_access_remote_term(self, auth, devid, forbid=False):
        devconn = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=deviceconnect.URL_MGMT,
        )

        res = devconn.call(
            "GET",
            deviceconnect.URL_MGMT_DEVICE,
            headers=auth.get_auth_token(),
            path_params={"id": devid},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok

    def check_access_file_transfer(self, auth, devid, forbid=False):
        devconn = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=deviceconnect.URL_MGMT,
        )
        res = devconn.call(
            "GET",
            deviceconnect.URL_MGMT_FDOWNLOAD,
            headers=auth.get_auth_token(),
            path_params={"id": devid},
            qs_params={"path": "/etc/mender/mender.conf"},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok

        res = devconn.call(
            "PUT",
            deviceconnect.URL_MGMT_FUPLOAD,
            headers=auth.get_auth_token(),
            path_params={"id": devid},
            qs_params={"path": "/etc/mender/mender.conf"},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.status_code != 403

    def check_access_auditlogs(self, auth, forbid=False):
        alogs = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=auditlogs.URL_MGMT,
        )
        res = alogs.call("GET", auditlogs.URL_LOGS, headers=auth.get_auth_token(),)

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok

    def check_access_sessionlogs(self, auth, forbid=False):
        devconn = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=deviceconnect.URL_MGMT,
        )
        res = devconn.call(
            "GET",
            deviceconnect.URL_MGMT_PLAYBACK,
            headers=auth.get_auth_token(),
            path_params={"session_id": "foo"},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.status_code != 403

    # configure
    def check_access_deviceconfig(self, auth, devid, forbid=False):
        devconf = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=deviceconfig.URL_MGMT,
        )
        res = devconf.call(
            "GET",
            deviceconfig.URL_MGMT_DEVICE_CONFIGURATION,
            headers=auth.get_auth_token(),
            path_params={"id": devid},
        )

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok

    # rbac (no addon)
    def check_access_rbac(self, auth, forbid=False):
        uadm = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=useradm.URL_MGMT,
        )
        res = uadm.call("GET", useradm.URL_ROLES, headers=auth.get_auth_token(),)

        if forbid:
            assert res.status_code == 403
        else:
            assert res.ok


class TestAccess(_TestAccessBase):
    """Onprem OS.

    Quite a few addon features are available here (despite being
    hidden behind paid addons in hosted).
    """

    def test_ok(self, standard_setup_one_client):
        devauth.accept_devices(1)

        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        wait_for_connect(auth, devices[0])

        devid = devices[0]
        auth.get_auth_token()

        self.check_access_remote_term(auth, devid)
        self.check_access_file_transfer(auth, devid)
        self.check_access_sessionlogs(auth)
        self.check_access_deviceconfig(auth, devid)


class TestAccessEnterprise(_TestAccessBase):
    """ Full enterprise setup, with HAVE_ADDONS and MT."""

    @pytest.fixture(scope="class")
    def docker_env(self, enterprise_no_client_class):
        """Prepare 4 tenants across all plans (trial...enterprise) + a device each."""
        env = enterprise_no_client_class

        env.tenants = {}

        for p in ["os", "professional", "enterprise"]:
            env.tenants[p] = self._make_tenant(p, env)

        env.tenants["trial"] = self._make_trial_tenant(env)

        yield env

    def test_initial_restrictions(self, docker_env):
        """ Test that existing users are in fact under new addon restrictions, to incentivize addon upgrades. """

        for plan in ["os", "professional", "enterprise"]:
            tenant = docker_env.tenants[plan]
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
                # self.check_access_rbac(tenant.auth, forbid=True)

        for plan in ["trial"]:
            tenant = docker_env.tenants[plan]
            # to actually access any RT/FT - wait for device
            wait_for_connect(tenant.auth, tenant.device_id)

            self.check_access_remote_term(tenant.auth, tenant.device_id)
            self.check_access_file_transfer(tenant.auth, tenant.device_id)
            self.check_access_auditlogs(tenant.auth)
            self.check_access_sessionlogs(tenant.auth)
            self.check_access_deviceconfig(tenant.auth, tenant.device_id)
            self.check_access_rbac(tenant.auth)

    def test_upgrades(self, docker_env):
        """Test that plan/addon upgrades take effect on feature availability.
        Special case is the trial tenant upgrade to a paid plan.
        """
        tenant = docker_env.tenants["os"]

        # add troubleshoot
        update_tenant(
            tenant.id,
            addons=["troubleshoot"],
            container_manager=get_container_manager(),
        )

        tenant.auth.reset_auth_token()

        wait_for_connect(tenant.auth, tenant.device_id)

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth, forbid=True)
        self.check_access_sessionlogs(tenant.auth, forbid=True)
        self.check_access_deviceconfig(
            tenant.auth, tenant.device_id, forbid=True,
        )
        # self.check_access_rbac(tenant.auth, forbid=True)

        # add configure
        update_tenant(
            tenant.id,
            addons=["troubleshoot", "configure"],
            container_manager=get_container_manager(),
        )

        tenant.auth.reset_auth_token()

        wait_for_connect(tenant.auth, tenant.device_id)

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_deviceconfig(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth, forbid=True)
        self.check_access_sessionlogs(tenant.auth, forbid=True)
        # self.check_access_rbac(tenant.auth, forbid=True)

        # upgrade to "enterprise" - makes audit, session logs and rbac available
        update_tenant(
            tenant.id, plan="enterprise", container_manager=get_container_manager(),
        )

        tenant.auth.reset_auth_token()

        wait_for_connect(tenant.auth, tenant.device_id)

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_deviceconfig(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth)
        self.check_access_sessionlogs(tenant.auth)
        self.check_access_rbac(tenant.auth)

        # upgrade trial tenant - straight to enterprise
        tenant = docker_env.tenants["trial"]

        tadmm = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=tenantadm_v2.URL_MGMT,
        )

        res = tadmm.call(
            "POST",
            tenantadm_v2.URL_TENANT_UPGRADE_START,
            path_params={"id": tenant.id},
            headers=tenant.auth.get_auth_token(),
        )

        assert res.status_code == 200
        res = res.json()

        stripeutils.confirm("pm_card_visa", res["intent_id"])

        body = {
            "plan": "enterprise",
        }

        res = tadmm.call(
            "POST",
            tenantadm_v2.URL_TENANT_UPGRADE_COMPLETE,
            path_params={"id": tenant.id},
            body=body,
            headers=tenant.auth.get_auth_token(),
        )
        assert res.status_code == 202

        update_tenant(
            tenant.id,
            addons=["troubleshoot", "configure"],
            container_manager=get_container_manager(),
        )

        tenant.auth.reset_auth_token()

        wait_for_connect(tenant.auth, tenant.device_id)

        self.check_access_remote_term(tenant.auth, tenant.device_id)
        self.check_access_file_transfer(tenant.auth, tenant.device_id)
        self.check_access_deviceconfig(tenant.auth, tenant.device_id)
        self.check_access_auditlogs(tenant.auth)
        self.check_access_sessionlogs(tenant.auth)
        self.check_access_rbac(tenant.auth)

    def _make_tenant(self, plan, env):
        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}-{}".format(uuidv4, plan)
        email = "some.user+{}@example.com".format(uuidv4)

        cli = CliTenantadm(containers_namespace=env.name)
        tid = cli.create_org(tname, email, "correcthorse", plan)

        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]

        # the cli now sets all addons to 'enabled' -
        # disable them for initial 'all disabled' state
        update_tenant(
            tenant["id"], addons=[], container_manager=get_container_manager(),
        )

        auth = Authentication(name=tname, username=email, password="correcthorse")
        auth.create_org = False
        auth.reset_auth_token()
        devauth = DeviceAuthV2(auth)

        new_tenant_client(env, "test-container-{}".format(plan), ttoken)
        devauth.accept_devices(1)

        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        tenant = Tenant(tname, tid, ttoken)
        u = User("", email, "correcthorse")

        tenant.users.append(u)
        tenant.device_id = devices[0]
        tenant.auth = auth
        tenant.devauth = devauth

        return tenant

    def _make_trial_tenant(self, env):
        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}-{}".format(uuidv4, "trial")
        email = "some.user+{}@example.com".format(uuidv4)

        tadmm = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=tenantadm_v2.URL_MGMT,
        )

        args = {
            "organization": tname,
            "email": email,
            "password": "correcthorse",
            "name": "foo",
            "g-recaptcha-response": "dummy",
            "plan": "enterprise",
        }

        res = tadmm.call("POST", tenantadm_v2.URL_CREATE_ORG_TRIAL, body=args,)

        assert res.status_code == 202

        # get tenant id
        tenantadm_host = (
            tenantadm.HOST
            if isK8S()
            else get_container_manager().get_ip_of_service("mender-tenantadm")[0]
            + ":8080"
        )
        tadmi = ApiClient(
            host=tenantadm_host, base_url=tenantadm.URL_INTERNAL, schema="http://",
        )

        res = tadmi.call(
            "GET", tenantadm.URL_INTERNAL_TENANTS, qs_params={"username": email}
        )
        assert res.status_code == 200
        assert len(res.json()) == 1

        apitenant = res.json()[0]

        cli = CliTenantadm(containers_namespace=env.name)

        tenant = cli.get_tenant(apitenant["id"])
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]

        auth = Authentication(name=tname, username=email, password="correcthorse")
        auth.create_org = False
        auth.reset_auth_token()
        devauth = DeviceAuthV2(auth)

        new_tenant_client(env, "test-container-trial", ttoken)
        devauth.accept_devices(1)

        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        tenant = Tenant(tname, apitenant["id"], ttoken)
        u = User("", email, "correcthorse")

        tenant.users.append(u)
        tenant.device_id = devices[0]
        tenant.auth = auth
        tenant.devauth = devauth

        return tenant
