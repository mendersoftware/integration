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

from api.client import ApiClient
from common import mongo, clean_mongo
from infra.cli import CliUseradm, CliDeviceauth, CliTenantadm
import api.deviceauth as deviceauth_v1
import api.deviceauth_v2 as deviceauth_v2
import api.useradm as useradm
import api.tenantadm as tenantadm
import util.crypto

class User:
    def __init__(self, id, name, pwd):
        self.name=name
        self.pwd=pwd
        self.id=id


class Device:
    def __init__(self, id_data, pubkey, privkey, tenant_token=''):
        self.id_data=id_data
        self.pubkey=pubkey
        self.privkey=privkey
        self.tenant_token=tenant_token


class Tenant:
    def __init__(self, name, id, token):
        self.name=name
        self.users=[]
        self.devices=[]
        self.id=id
        self.tenant_token=token

@pytest.yield_fixture(scope='function')
def clean_migrated_mongo(clean_mongo):
    deviceauth_cli = CliDeviceauth()
    useradm_cli = CliUseradm()

    deviceauth_cli.migrate()
    useradm_cli.migrate()

    yield clean_mongo

@pytest.yield_fixture(scope='function')
def clean_migrated_mongo_mt(clean_mongo):
    deviceauth_cli = CliDeviceauth()
    useradm_cli = CliUseradm()
    for t in ['tenant1', 'tenant2']:
        deviceauth_cli.migrate(t)
        useradm_cli.migrate(t)

    yield clean_mongo

@pytest.yield_fixture(scope="function")
def user(clean_migrated_mongo):
    yield create_user('user-foo@acme.com', 'correcthorse')

@pytest.yield_fixture(scope="function")
def devices(clean_migrated_mongo):
    devauthd = ApiClient(deviceauth_v1.URL_DEVICES)

    devices = []

    for _ in range(5):
        d = create_random_device()
        devices.append(d)

    yield devices

@pytest.yield_fixture(scope="function")
def tenants_users(clean_migrated_mongo_mt):
    cli = CliTenantadm()
    api = ApiClient(tenantadm.URL_INTERNAL)

    names = ['tenant1', 'tenant2']
    tenants=[]

    for n in names:
        tenants.append(create_tenant(n))

    for t in tenants:
        for i in range(2):
            user = create_tenant_user(i, t)
            t.users.append(user)

    yield tenants

@pytest.yield_fixture(scope="function")
def tenants_users_devices(clean_migrated_mongo_mt, tenants_users):
    for t in tenants_users:
        for _ in range(5):
            dev = create_random_device(t.tenant_token)
            t.devices.append(dev)

    yield tenants_users

def create_tenant(name):
    """ Create a tenant via cli, record its id and token for further use.  """
    cli = CliTenantadm()
    api = ApiClient(tenantadm.URL_INTERNAL)

    id = cli.create_tenant(name)

    r = api.call('GET', tenantadm.URL_INTERNAL_TENANTS)
    assert r.status_code == 200

    api_tenants = r.json()

    api_tenant = [at for at in api_tenants if at['id'] == id]
    token=api_tenant[0]['tenant_token']

    return Tenant(name, id, token)

def create_random_device(tenant_token=''):
    """ create_device with random id data and keypair"""
    priv, pub = util.crypto.rsa_get_keypair()
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), 'x') for i in range(6)])
    id_data = {'mac': mac}

    return create_device(id_data, pub, priv, tenant_token)

def create_device(id_data, pubkey, privkey, tenant_token=''):
    """ Simply submit an auth request for a device; it will result in a 'pending' device/authset."""
    api = ApiClient(deviceauth_v1.URL_DEVICES)

    body, sighdr = deviceauth_v1.auth_req(id_data, pubkey, privkey, tenant_token)

    # submit auth req
    r = api.call('POST',
                 deviceauth_v1.URL_AUTH_REQS,
                 body,
                 headers=sighdr)
    assert r.status_code == 401

    return Device(id_data, pubkey, privkey, tenant_token)

def create_user(name, pwd, tid=''):
    cli = CliUseradm()

    uid = cli.create_user(name, pwd, tid)

    return User(uid, name, pwd)

def create_tenant_user(idx, tenant):
    name = 'user{}@{}.com'.format(idx, tenant.name)
    pwd = 'correcthorse'

    return create_user(name, pwd, tenant.id)

class TestPreauthBase:
    def do_test_ok(self, user, tenant_token=''):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthm = ApiClient(deviceauth_v2.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)

        # log in user
        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200

        utoken = r.text

        # preauth device
        priv, pub = util.crypto.rsa_get_keypair()
        id_data = {'mac': 'pretenditsamac'}
        body = deviceauth_v2.preauth_req(
                    id_data,
                    pub)
        r = devauthm.with_auth(utoken).call('POST',
                                            deviceauth_v2.URL_DEVICES,
                                            body)
        assert r.status_code == 201

        # device appears in device list
        r = devauthm.with_auth(utoken).call('GET',
                                            deviceauth_v2.URL_DEVICES)
        assert r.status_code == 200
        api_devs = r.json()

        assert len(api_devs) == 1
        api_dev = api_devs[0]

        assert api_dev['status'] == 'preauthorized'
        assert api_dev['identity_data'] == id_data
        assert len(api_dev['auth_sets']) == 1
        aset = api_dev['auth_sets'][0]

        assert aset['identity_data'] == id_data
        assert util.crypto.rsa_compare_keys(aset['pubkey'], pub)
        assert aset['status'] == 'preauthorized'

        # actual device can obtain auth token
        body, sighdr = deviceauth_v1.auth_req(id_data,
                                              pub,
                                              priv,
                                              tenant_token)

        r = devauthd.call('POST',
                          deviceauth_v1.URL_AUTH_REQS,
                          body,
                          headers=sighdr)

        assert r.status_code == 200

    def do_test_fail_duplicate(self, user, devices):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthm = ApiClient(deviceauth_v2.URL_MGMT)

        # log in user
        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200

        utoken = r.text

        # preauth duplicate device
        priv, pub = util.crypto.rsa_get_keypair()
        id_data = devices[0].id_data
        body = deviceauth_v2.preauth_req(
                    id_data,
                    pub)
        r = devauthm.with_auth(utoken).call('POST',
                                            deviceauth_v2.URL_DEVICES,
                                            body)
        assert r.status_code == 409

        # device list is unmodified
        r = devauthm.with_auth(utoken).call('GET',
                                            deviceauth_v2.URL_DEVICES)
        assert r.status_code == 200
        api_devs = r.json()

        assert len(api_devs) == len(devices)

        # existing device has no new auth sets
        existing = [d for d in api_devs if d['identity_data'] == id_data]
        assert len(existing) == 1
        existing = existing[0]

        assert len(existing['auth_sets']) == 1
        aset = existing['auth_sets'][0]
        assert util.crypto.rsa_compare_keys(aset['pubkey'], devices[0].pubkey)
        assert aset['status'] == 'pending'


class TestPreauth(TestPreauthBase):
    def test_ok(self, user):
        self.do_test_ok(user)

    def test_fail_duplicate(self, user, devices):
        self.do_test_fail_duplicate(user, devices)

    def test_fail_bad_request(self, user):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthm = ApiClient(deviceauth_v2.URL_MGMT)

        # log in user
        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200

        utoken = r.text

        # id data not json
        priv, pub = util.crypto.rsa_get_keypair()
        id_data = '{\"mac\": \"foo\"}'
        body = deviceauth_v2.preauth_req(
                    id_data,
                    pub)
        r = devauthm.with_auth(utoken).call('POST',
                                            deviceauth_v2.URL_DEVICES,
                                            body)
        assert r.status_code == 400

        # not a valid key
        id_data = {'mac': 'foo'}
        body = deviceauth_v2.preauth_req(
                    id_data,
                    'not a public key')
        r = devauthm.with_auth(utoken).call('POST',
                                            deviceauth_v2.URL_DEVICES,
                                            body)
        assert r.status_code == 400

class TestPreauthMultitenant(TestPreauthBase):
    def test_ok(self, tenants_users):
        user = tenants_users[0].users[0]

        self.do_test_ok(user, tenants_users[0].tenant_token)

        # check other tenant's devices unmodified
        user1 = tenants_users[1].users[0]
        devs1 = tenants_users[1].devices
        self.verify_devices_unmodified(user1, devs1)

    def test_fail_duplicate(self, tenants_users_devices):
        user = tenants_users_devices[0].users[0]
        devices = tenants_users_devices[0].devices

        self.do_test_fail_duplicate(user, devices)

        # check other tenant's devices unmodified
        user1 = tenants_users_devices[1].users[0]
        devs1 = tenants_users_devices[1].devices
        self.verify_devices_unmodified(user1, devs1)

    def verify_devices_unmodified(self, user, in_devices):
        devauthm = ApiClient(deviceauth_v2.URL_MGMT)
        useradmm = ApiClient(useradm.URL_MGMT)

        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200

        utoken = r.text

        r = devauthm.with_auth(utoken).call('GET',
                                            deviceauth_v2.URL_DEVICES)
        assert r.status_code == 200
        api_devs = r.json()

        assert len(api_devs) == len(in_devices)
        for ad in api_devs:
            assert ad['status'] == 'pending'

            orig_device = [d for d in in_devices if d.id_data == ad['identity_data']]
            assert len(orig_device) == 1
            orig_device = orig_device[0]

            assert len(ad['auth_sets']) == 1
            aset = ad['auth_sets'][0]
            assert util.crypto.rsa_compare_keys(aset['pubkey'], orig_device.pubkey)
