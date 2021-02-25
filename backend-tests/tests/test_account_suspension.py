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
import time
import uuid

from testutils.api.client import ApiClient
import testutils.api.useradm as useradm
import testutils.api.deviceauth as deviceauth
import testutils.api.tenantadm as tenantadm
import testutils.api.deployments as deployments
from testutils.common import (
    Device,
    mongo,
    clean_mongo,
    create_org,
    create_random_authset,
    change_authset_status,
)


@pytest.fixture(scope="function")
def tenants(clean_mongo):
    tenants = []

    for n in range(2):
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenants.append(create_org(tenant, username, password))

    yield tenants


@pytest.fixture(scope="function")
def tenants_users_devices(tenants, mongo):
    uc = ApiClient(useradm.URL_MGMT)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)
    for t in tenants:
        user = t.users[0]
        r = uc.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        for _ in range(2):
            aset = create_random_authset(devauthd, devauthm, utoken, t.tenant_token)
            dev = Device(aset.did, aset.id_data, aset.pubkey, t.tenant_token)
            dev.authsets.append(aset)
            t.devices.append(dev)

    yield tenants


class TestAccountSuspensionEnterprise:
    def test_user_cannot_log_in(self, tenants):
        tc = ApiClient(tenantadm.URL_INTERNAL, host=tenantadm.HOST, schema="http://")

        uc = ApiClient(useradm.URL_MGMT)

        for u in tenants[0].users:
            r = uc.call("POST", useradm.URL_LOGIN, auth=(u.name, u.pwd))
            assert r.status_code == 200

        # tenant's users can log in
        for u in tenants[0].users:
            r = uc.call("POST", useradm.URL_LOGIN, auth=(u.name, u.pwd))
            assert r.status_code == 200

        assert r.status_code == 200

        # suspend tenant
        r = tc.call(
            "PUT",
            tenantadm.URL_INTERNAL_SUSPEND,
            tenantadm.req_status("suspended"),
            path_params={"tid": tenants[0].id},
        )
        assert r.status_code == 200

        time.sleep(10)

        # none of tenant's users can log in
        for u in tenants[0].users:
            r = uc.call("POST", useradm.URL_LOGIN, auth=(u.name, u.pwd))
            assert r.status_code == 401

        # but other users still can
        for u in tenants[1].users:
            r = uc.call("POST", useradm.URL_LOGIN, auth=(u.name, u.pwd))
            assert r.status_code == 200

    def test_authenticated_user_is_rejected(self, tenants):
        tc = ApiClient(tenantadm.URL_INTERNAL, host=tenantadm.HOST, schema="http://")
        uc = ApiClient(useradm.URL_MGMT)
        dc = ApiClient(deviceauth.URL_MGMT)

        u = tenants[0].users[0]

        # log in
        r = uc.call("POST", useradm.URL_LOGIN, auth=(u.name, u.pwd))
        assert r.status_code == 200

        token = r.text

        # check can access an api
        r = dc.with_auth(token).call("GET", deviceauth.URL_MGMT_DEVICES)
        assert r.status_code == 200

        # suspend tenant
        r = tc.call(
            "PUT",
            tenantadm.URL_INTERNAL_SUSPEND,
            tenantadm.req_status("suspended"),
            path_params={"tid": tenants[0].id},
        )
        assert r.status_code == 200

        time.sleep(10)

        # check token is rejected
        r = dc.with_auth(token).call("GET", deviceauth.URL_MGMT_DEVICES)
        assert r.status_code == 401

    def test_accepted_dev_cant_authenticate(self, tenants_users_devices):
        dacd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        uc = ApiClient(useradm.URL_MGMT)
        tc = ApiClient(tenantadm.URL_INTERNAL, host=tenantadm.HOST, schema="http://")

        # accept a dev
        device = tenants_users_devices[0].devices[0]
        user = tenants_users_devices[0].users[0]

        r = uc.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        aset = device.authsets[0]
        change_authset_status(devauthm, aset.did, aset.id, "accepted", utoken)

        # suspend
        r = tc.call(
            "PUT",
            tenantadm.URL_INTERNAL_SUSPEND,
            tenantadm.req_status("suspended"),
            path_params={"tid": tenants_users_devices[0].id},
        )
        assert r.status_code == 200

        time.sleep(10)

        # try requesting auth
        body, sighdr = deviceauth.auth_req(
            aset.id_data,
            aset.pubkey,
            aset.privkey,
            tenants_users_devices[0].tenant_token,
        )

        r = dacd.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)

        assert r.status_code == 401
        assert r.json()["error"] == "Account suspended"

    def test_authenticated_dev_is_rejected(self, tenants_users_devices):
        dacd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        uc = ApiClient(useradm.URL_MGMT)
        tc = ApiClient(tenantadm.URL_INTERNAL, host=tenantadm.HOST, schema="http://")
        dc = ApiClient(deployments.URL_DEVICES)

        # accept a dev
        user = tenants_users_devices[0].users[0]

        r = uc.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        aset = tenants_users_devices[0].devices[0].authsets[0]
        change_authset_status(devauthm, aset.did, aset.id, "accepted", utoken)

        # request auth
        body, sighdr = deviceauth.auth_req(
            aset.id_data,
            aset.pubkey,
            aset.privkey,
            tenants_users_devices[0].tenant_token,
        )

        r = dacd.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)
        assert r.status_code == 200
        dtoken = r.text

        # check device can access APIs
        r = dc.with_auth(dtoken).call(
            "GET",
            deployments.URL_NEXT,
            qs_params={"device_type": "foo", "artifact_name": "bar"},
        )
        assert r.status_code == 204

        # suspend
        r = tc.call(
            "PUT",
            tenantadm.URL_INTERNAL_SUSPEND,
            tenantadm.req_status("suspended"),
            path_params={"tid": tenants_users_devices[0].id},
        )
        assert r.status_code == 200

        time.sleep(10)

        # check device is rejected
        r = dc.with_auth(dtoken).call(
            "GET",
            deployments.URL_NEXT,
            qs_params={"device_type": "foo", "artifact_name": "bar"},
        )
        assert r.status_code == 401
