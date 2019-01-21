# Copyright 2018 Northern.tech AS
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
import random
import time

from common import mongo, clean_mongo
from api.client import ApiClient
import api.useradm as useradm
import api.deviceauth as deviceauth
import api.deviceauth_v2 as deviceauth_v2
import api.tenantadm as tenantadm
import api.deployments as deployments
from infra.cli import CliTenantadm, CliUseradm
import util.crypto
from common import User, Device, Tenant, \
        create_user, create_tenant, create_tenant_user, \
        create_random_device

@pytest.yield_fixture(scope="function")
def tenants(clean_mongo):
    tenants = []

    for n in ['tenant1', 'tenant2']:
        tenants.append(create_tenant(n))

    yield tenants

@pytest.yield_fixture(scope="function")
def tenants_users(tenants, clean_mongo):
    for t in tenants:
        for i in range(2):
            user = create_tenant_user(i, t)
            t.users.append(user)

    yield tenants

@pytest.yield_fixture(scope="function")
def tenants_users_devices(tenants_users, mongo):
    for t in tenants_users:
        for _ in range(2):
            dev = create_random_device(t.tenant_token)
            t.devices.append(dev)

    yield tenants_users

def get_authset_id(pubkey, utoken):
    api = ApiClient(deviceauth_v2.URL_MGMT)
    r = api.with_auth(utoken).call('GET',
                                   deviceauth_v2.URL_DEVICES)

    assert r.status_code == 200

    api_devs = r.json()
    api_dev = None
    for ad in api_devs:
        aset = [a for a in ad['authsets'] if util.crypto.rsa_compare_keys(a['pubkey'], pubkey)]
        if len(aset) == 1:
            return aset['id']

    assert False, "authset not found, can't get id"

class TestAccountSuspensionMultitenant:
    def test_user_cannot_log_in(self, tenants_users):
        tc = ApiClient(tenantadm.URL_INTERNAL)

        uc = ApiClient(useradm.URL_MGMT)

        for u in tenants_users[0].users:
            r = uc.call('POST',
                        useradm.URL_LOGIN,
                        auth=(u.name, u.pwd))
            assert r.status_code == 200

        # tenant's users can log in
        for u in tenants_users[0].users:
            r = uc.call('POST',
                        useradm.URL_LOGIN,
                        auth=(u.name, u.pwd))
            assert r.status_code == 200

        assert r.status_code==200

        # suspend tenant
        r = tc.call('PUT',
                tenantadm.URL_INTERNAL_SUSPEND,
                tenantadm.req_status('suspended'),
                path_params={'tid': tenants_users[0].id})
        assert r.status_code == 200

        time.sleep(10)

        # none of tenant's users can log in
        for u in tenants_users[0].users:
            r = uc.call('POST',
                        useradm.URL_LOGIN,
                        auth=(u.name, u.pwd))
            assert r.status_code == 401

        # but other users still can
        for u in tenants_users[1].users:
            r = uc.call('POST',
                        useradm.URL_LOGIN,
                        auth=(u.name, u.pwd))
            assert r.status_code == 200

    def test_authenticated_user_is_rejected(self, tenants_users):
        tc = ApiClient(tenantadm.URL_INTERNAL)
        uc = ApiClient(useradm.URL_MGMT)
        dc = ApiClient(deviceauth.URL_MGMT)

        u = tenants_users[0].users[0]

        # log in
        r = uc.call('POST',
                     useradm.URL_LOGIN,
                     auth=(u.name, u.pwd))
        assert r.status_code == 200

        token = r.text

        # check can access an api
        r = dc.with_auth(token).call('GET', deviceauth.URL_LIST_DEVICES)
        assert r.status_code == 200

        # suspend tenant
        r = tc.call('PUT',
                tenantadm.URL_INTERNAL_SUSPEND,
                tenantadm.req_status('suspended'),
                path_params={'tid': tenants_users[0].id})
        assert r.status_code == 200

        time.sleep(10)

        # check token is rejected
        r = dc.with_auth(token).call('GET', deviceauth.URL_LIST_DEVICES)
        assert r.status_code == 401

    def test_accepted_dev_cant_authenticate(self, tenants_users_devices):
        dacd = ApiClient(deviceauth.URL_DEVICES)
        uc = ApiClient(useradm.URL_MGMT)
        tc = ApiClient(tenantadm.URL_INTERNAL)

        # accept a dev
        device = tenants_users_devices[0].devices[0]
        user = tenants_users_devices[0].users[0]

        r = uc.call('POST',
                    useradm.URL_LOGIN,
                    auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        dev = tenants_users_devices[0].devices[0]
        r = dacd.with_auth(utoken).call('PUT',
                                        deviceauth_v2.URL_AUTHSET_STATUS,
                                        deviceauth_v2.req_status('accepted'),
                                        path_params={
                                            'did': device.id,
                                            'aid': get_authset_id(dev.pubkey, utoken)})
        assert r.status_code == 200

        # suspend
        r = tc.call('PUT',
                tenantadm.URL_INTERNAL_SUSPEND,
                tenantadm.req_status('suspended'),
                path_params={'tid': tenants_users_devices[0].id})
        assert r.status_code == 200

        time.sleep(10)

        # try requesting auth
        body, sighdr = deviceauth.auth_req(device.id_data,
                                           device.pubkey,
                                           device.privkey,
                                           device.tenant_token)

        r = devauth.call('POST',
                         deviceauth.URL_AUTH_REQS,
                         body,
                         headers=sighdr)

        assert r.status_code == 401
        assert r.json()['error'] == 'Account suspended'

    def test_authenticated_dev_is_rejected(self, tenants_users_devices):
        dacm = ApiClient(deviceadm.URL_MGMT)
        dacd = ApiClient(deviceauth.URL_DEVICES)
        uc = ApiClient(useradm.URL_MGMT)
        tc = ApiClient(tenantadm.URL_INTERNAL)
        dc = ApiClient(deployments.URL_DEVICES)

        # accept a dev
        device = tenants_users_devices[0].devices[0]
        user = tenants_users_devices[0].users[0]

        r = uc.call('POST',
                    useradm.URL_LOGIN,
                    auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        dev = tenants_users_devices[0].devices[0]
        r = dacm.with_auth(utoken).call('PUT',
                                       deviceauth_v2.URL_AUTHSET_STATUS,
                                       deviceauth_v2.req_status('accepted'),
                                       path_params={
                                           'did': device.id,
                                           'aid': get_authset_id(dev.pubkey, utoken)
                                           })
        assert r.status_code == 200

        # request auth
        body, sighdr = deviceauth.auth_req(device.id_data,
                                           device.pubkey,
                                           device.privkey,
                                           device.tenant_token)

        r = dacd.call('POST',
                      deviceauth.URL_AUTH_REQS,
                      body,
                      headers=sighdr)
        assert r.status_code == 200
        dtoken = r.text

        # check device can access APIs
        r = dc.with_auth(dtoken).call('GET',
                                      deployments.URL_NEXT,
                                      qs_params={'device_type': 'foo',
                                                 'artifact_name': 'bar'})
        assert r.status_code == 204

        # suspend
        r = tc.call('PUT',
                tenantadm.URL_INTERNAL_SUSPEND,
                tenantadm.req_status('suspended'),
                path_params={'tid': tenants_users_devices[0].id})
        assert r.status_code == 200

        time.sleep(10)

        # check device is rejected
        r = dc.with_auth(dtoken).call('GET',
                                      deployments.URL_NEXT,
                                      qs_params={'device_type': 'foo',
                                                 'artifact_name': 'bar'})
        assert r.status_code == 401
