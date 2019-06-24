# Copyright 2019 Northern.tech AS
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

from api.client import ApiClient
from common import mongo, clean_mongo
from infra.cli import CliUseradm, CliDeviceauth, CliTenantadm
import api.deviceauth as deviceauth_v1
import api.useradm as useradm
import api.inventory as inventory_v1
import api.inventory_v2 as inventory
import api.tenantadm as tenantadm
import util.crypto
from common import User, Device, Authset, Tenant, \
        create_user, create_tenant, create_tenant_user, \
        create_authset, get_device_by_id_data, change_authset_status

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

def rand_id_data():
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), 'x') for i in range(6)])
    sn = "".join(["{}".format(random.randint(0x00, 0xFF)) for i in range(6)])

    return {'mac': mac, 'sn': sn}

def make_pending_device(utoken, tenant_token='', id_data=None):
    if id_data is None:
        id_data = rand_id_data()

    priv, pub = util.crypto.rsa_get_keypair()
    new_set = create_authset(id_data, pub, priv, utoken, tenant_token=tenant_token)

    dev = Device(new_set.did, new_set.id_data, utoken, tenant_token)

    dev.authsets.append(new_set)

    dev.status = 'pending'

    return dev

def make_accepted_device(utoken, devauthd, tenant_token='', id_data=None):
    dev = make_pending_device(utoken, tenant_token=tenant_token, id_data=id_data)
    aset_id = dev.authsets[0].id
    change_authset_status(dev.id, aset_id, 'accepted', utoken)

    aset = dev.authsets[0]
    aset.status = 'accepted'

    # obtain auth token
    body, sighdr = deviceauth_v1.auth_req(aset.id_data,
                                          aset.pubkey,
                                          aset.privkey,
                                          tenant_token)

    r = devauthd.call('POST',
                      deviceauth_v1.URL_AUTH_REQS,
                      body,
                      headers=sighdr)

    assert r.status_code == 200
    dev.token = r.text

    dev.status = 'accepted'

    return dev

def make_accepted_devices(utoken, devauthd, num_devices=1, tenant_token=''):
    """ Create accepted devices.
        returns list of Device objects."""
    devices = []

    # some 'accepted' devices, single authset
    for _ in range(num_devices):
        dev = make_accepted_device(utoken, devauthd, tenant_token=tenant_token)
        devices.append(dev)

    return devices

class TestGetDevicesV1Base:
    def do_test_get_devices_ok(self, user, tenant_token=''):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory_v1.URL_MGMT)
        invd = ApiClient(inventory_v1.URL_DEV)

        # log in user
        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 40, tenant_token)

        # wait for devices to be provisioned
        time.sleep(3)

        r = invm.with_auth(utoken).call('GET',
                                        inventory_v1.URL_DEVICES,
                                        qs_params={'per_page':100})
        assert r.status_code == 200
        api_devs = r.json()
        assert len(api_devs) == 40

    def do_test_filter_devices_ok(self, user, tenant_token=''):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory_v1.URL_MGMT)
        invd = ApiClient(inventory_v1.URL_DEV)

        # log in user
        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 40, tenant_token)

        # wait for devices to be provisioned
        time.sleep(3)

        r = invm.with_auth(utoken).call('GET',
                                        inventory_v1.URL_DEVICES,
                                        qs_params={'per_page':100})
        assert r.status_code == 200
        api_devs = r.json()
        assert len(api_devs) == 40

        # upload inventory attributes
        for i, d in enumerate(devs):
            payload = [
                    {
                        "name": "mac",
                        "value": "de:ad:be:ef:06:" + str(i)
                    }
            ]
            r = invd.with_auth(d.token).call('PATCH',
                                        inventory_v1.URL_DEVICE_ATTRIBUTES,
                                        payload)
            assert r.status_code == 200

        # get device with exact mac value
        qs_params={}
        qs_params['per_page'] = 100
        qs_params['mac'] = 'de:ad:be:ef:06:7'
        r = invm.with_auth(utoken).call('GET',
                                        inventory_v1.URL_DEVICES,
                                        qs_params=qs_params)
        assert r.status_code == 200
        api_devs = r.json()
        assert len(api_devs) == 1

class TestGetDevicesV1(TestGetDevicesV1Base):
    def test_get_devices_ok(self, user):
        self.do_test_get_devices_ok(user)

    def test_filter_devices_ok(self, user):
        self.do_test_filter_devices_ok(user)

class TestGetDevicesV1Multitenant(TestGetDevicesV1Base):
    def test_get_devices_ok(self, tenants_users):
        for t in tenants_users:
            self.do_test_get_devices_ok(t.users[0], tenant_token=t.tenant_token)

    def test_filter_devices_ok(self, tenants_users):
        for t in tenants_users:
            self.do_test_filter_devices_ok(t.users[0], tenant_token=t.tenant_token)

class TestDevicePatchAttributesV1:
    def test_ok(self, user):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory_v1.URL_MGMT)
        invd = ApiClient(inventory_v1.URL_DEV)

        # log in user
        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 3)

        # wait for devices to be provisioned
        time.sleep(3)

        for i, d in enumerate(devs):
            payload = [
                    {
                        "name": "mac",
                        "value": "mac-new-" + str(d.id)
                    },
                    {
                        #empty value for existing
                        "name": "sn",
                        "value": "",
                    },
                    {
                        #empty value for new
                        "name": "new-empty",
                        "value": "",
                    }
            ]
            r = invd.with_auth(d.token).call('PATCH',
                                        inventory_v1.URL_DEVICE_ATTRIBUTES,
                                        payload)
            assert r.status_code == 200

        for d in devs:
            r = invm.with_auth(utoken).call('GET',
                                            inventory_v1.URL_DEVICE,
                                            path_params={'id': d.id})
            assert r.status_code == 200

            api_dev = r.json()
            assert len(api_dev['attributes']) == 3

            for a in api_dev['attributes']:
                if a['name'] == 'mac':
                    assert a['value'] == 'mac-new-' + str(api_dev['id'])
                elif a['name'] == 'sn':
                    assert a['value'] == ''
                elif a['name'] == 'new-empty':
                    assert a['value'] == ''
                else:
                    assert False, 'unexpected attribute ' + a['name']

    def test_fail_no_attr_value(self, user):
        useradmm = ApiClient(useradm.URL_MGMT)
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        invm = ApiClient(inventory_v1.URL_MGMT)
        invd = ApiClient(inventory_v1.URL_DEV)

        # log in user
        r = useradmm.call('POST',
                          useradm.URL_LOGIN,
                          auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text

        # prepare accepted devices
        devs = make_accepted_devices(utoken, devauthd, 1)

        # wait for devices to be provisioned
        time.sleep(3)

        for i, d in enumerate(devs):
            payload = [
                    {
                        "name": "mac",
                    }
            ]
            r = invd.with_auth(d.token).call('PATCH',
                                        inventory_v1.URL_DEVICE_ATTRIBUTES,
                                        payload)
            assert r.status_code == 400

def make_devs_get_v2(utoken, devauthd, invd, invi, tenant_token='', tenant_id=''):
    """ GET v2 - specific data fixture 
        Create 20 accepted devices, with inventory.
        All submit:
        - inventory via PATCH v1/devices/inventory/devices.
        - id data via PATCH v2/internal/inventory/devices.
        Each half of devices shares a 'batch' identity attribute, for testing filtering.
        The 'middle' 10 also share a 'common' identity attribute, also for this purpose.
    """
    devs = []

    for i in range(0,20):
        batch = 'batch1'

        if i > 9:
            batch = 'batch2'

        mac = ':'.join(['{:02x}'.format(random.randint(0x00, 0xFF), 'x') for i in range(6)])
        sn = ''.join(['{}'.format(random.randint(0, 9)) for i in range(6)])

        id_data = {
            'batch': batch,
            'mac': mac,
            'sn': sn,
        }

        if i > 4 and i < 15:
            id_data['common'] = 'common'

        dev = make_accepted_device(utoken, devauthd, tenant_token=tenant_token, id_data=id_data)

        foo = ''.join(['{}'.format(random.randint(0x00, 0xFF)) for i in range(6)])
        bar = ''.join(['{}'.format(random.randint(0x00, 0xFF)) for i in range(6)])

        inv = {
            'foo': foo,
            'bar': bar
        }

        dev.inventory = inv

        devs.append(dev)

    # before returning, make sure we have all devices in inventory
    # means first waiting for conductor so that the workflow doesn't overflow to other tests
    # then doing the PATCHes
    retries = 5
    invm = ApiClient(inventory.URL_MGMT)
    api_devs = []

    while retries>0:
        r = invm.with_auth(utoken).call('GET',
                                            inventory.URL_MGMT_DEVICES)
        retries-=1
        try:
            assert r.status_code == 200
            api_devs = r.json()
            assert len(api_devs) == 20
            break
        except AssertionError:
            print('waiting for conductor: retry count {}'.format(retries))
            time.sleep(1)
            continue

    assert retries != 0, 'waiting for conductor timed out'

    # we allowed conductor to do its async job(s), we don't know the order of devices now
    # sort our reference collection according to the order in api_devs
    sorted_ids = [x['id'] for x in api_devs]
    devs = sorted(devs, key=lambda x: sorted_ids.index(x.id))

    # only now PATCH attributes via the device/internal api
    for d in devs:
        submit_id_internal_api(d, invi, tenant_id)
        submit_inv_devices_api(d, invd)

    return devs

def submit_inv_devices_api(dev, invd):
    payload = []

    for k in dev.inventory:
        payload.append({'name': k, 'value': dev.inventory[k]})

    r = invd.with_auth(dev.token).call('PATCH',
                                   inventory_v1.URL_DEVICE_ATTRIBUTES,
                                   payload)
    assert r.status_code == 200

def submit_id_internal_api(dev, invi, tenant_id=''):
    payload = []
    for k in dev.id_data:
        payload.append({'name': k, 'value': dev.id_data[k], 'scope': 'identity'})

    now = str(round(datetime.utcnow().timestamp() * 1000))
    r = invi.with_auth(dev.token) \
             .with_header('X-MEN-Source', 'deviceauth') \
             .with_header('X-MEN-Msg-Timestamp', now) \
             .call('PATCH', \
                  inventory.URL_INT_DEVICE_ATTRIBUTES, \
                  payload, \
                  path_params={'id': dev.id}, \
                  qs_params={'tenant_id': tenant_id})
    assert r.status_code == 200
