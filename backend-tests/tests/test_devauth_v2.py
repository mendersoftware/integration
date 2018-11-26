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
from infra.cli import CliUseradm, CliDeviceauth
import api.deviceauth as deviceauth_v1
import api.deviceauth_v2 as deviceauth_v2
import api.useradm as useradm
import util.crypto

class User:
    def __init__(self, id, name, pwd):
        self.name=name
        self.pwd=pwd
        self.id=id


class Device:
    def __init__(self, id_data, pubkey, privkey):
        self.id_data=id_data
        self.pubkey=pubkey
        self.privkey=privkey

@pytest.yield_fixture(scope='function')
def clean_migrated_mongo(clean_mongo):
    deviceauth_cli = CliDeviceauth()
    useradm_cli = CliUseradm()

    deviceauth_cli.migrate()
    useradm_cli.migrate()

    yield clean_mongo

@pytest.yield_fixture(scope="function")
def user(clean_migrated_mongo):
    cu = CliUseradm()

    username = 'user-foo@acme.com'
    pwd = 'correcthorse'
    uid = cu.create_user(username, pwd)

    user = User(uid, username, pwd)

    yield user

@pytest.yield_fixture(scope="function")
def devices(clean_migrated_mongo):
    devauthd = ApiClient(deviceauth_v1.URL_DEVICES)

    devices = []

    for _ in range(5):
        priv, pub = util.crypto.rsa_get_keypair()
        mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), 'x') for i in range(6)])
        d = Device({'mac': mac}, pub, priv)

        body, sighdr = deviceauth_v1.auth_req(d.id_data, d.pubkey, d.privkey)

        # submit auth req
        r = devauthd.call('POST',
                      deviceauth_v1.URL_AUTH_REQS,
                      body,
                      headers=sighdr)
        assert r.status_code == 401

        devices.append(d)

    yield devices

class TestPreauth:
    def test_ok(self, user):
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
                                              priv)

        r = devauthd.call('POST',
                          deviceauth_v1.URL_AUTH_REQS,
                          body,
                          headers=sighdr)

        assert r.status_code == 200

    def test_fail_duplicate(self, user, devices):
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
