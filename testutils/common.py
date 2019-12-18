#!/usr/bin/python
# Copyright 2019 Mender Software AS
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
import pymongo
from pymongo import MongoClient

from testutils.api.client import ApiClient
from testutils.infra.cli import CliUseradm, CliTenantadm
import testutils.api.deviceauth as deviceauth_v1
import testutils.api.deviceauth_v2 as deviceauth_v2
import testutils.api.tenantadm as tenantadm
import testutils.util.crypto

@pytest.fixture(scope="session")
def mongo():
    return MongoClient('mender-mongo:27017')

@pytest.yield_fixture(scope='function')
def clean_mongo(mongo):
    """Fixture setting up a clean (i.e. empty database). Yields
    pymongo.MongoClient connected to the DB."""
    mongo_cleanup(mongo)
    yield mongo
    mongo_cleanup(mongo)

def mongo_cleanup(mongo):
    dbs = mongo.database_names()
    dbs = [d for d in dbs if d not in ['local', 'admin', 'config']]
    for d in dbs:
        mongo.drop_database(d)


class User:
    def __init__(self, id, name, pwd):
        self.name=name
        self.pwd=pwd
        self.id=id


class Authset:
    def __init__(self, id, did, id_data, pubkey, privkey, status):
        self.id = id
        self.did = did
        self.id_data = id_data
        self.pubkey = pubkey
        self.privkey = privkey
        self.status = status


class Device:
    def __init__(self, id, id_data, pubkey, tenant_token=''):
        self.id = id
        self.id_data=id_data
        self.pubkey=pubkey
        self.tenant_token=tenant_token
        self.authsets = []
        self.token = None

class Tenant:
    def __init__(self, name, id, token):
        self.name=name
        self.users=[]
        self.devices=[]
        self.id=id
        self.tenant_token=token


def create_tenant(name, docker_prefix=None):
    """ Create a tenant via cli, record its id and token for further use.  """
    cli = CliTenantadm(docker_prefix)
    api = ApiClient(tenantadm.URL_INTERNAL)

    id = cli.create_tenant(name)

    page = 0
    per_page = 20
    qs_params = {}
    found = None
    while True:
        page = page + 1
        qs_params['page'] = page
        qs_params['per_page'] = per_page
        r = api.call('GET', tenantadm.URL_INTERNAL_TENANTS, qs_params=qs_params)
        assert r.status_code == 200
        api_tenants = r.json()

        found = [at for at in api_tenants if at['id'] == id]
        if len(found) > 0:
            break

        if len(api_tenants) == 0:
            break

    assert len(found) == 1
    token = found[0]['tenant_token']

    return Tenant(name, id, token)

def create_random_authset(dauthd1, dauthm, utoken, tenant_token=''):
    """ create_device with random id data and keypair"""
    priv, pub = testutils.util.crypto.rsa_get_keypair()
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), 'x') for i in range(6)])
    id_data = {'mac': mac}

    return create_authset(dauthd1, dauthm, id_data, pub, priv, utoken, tenant_token)

def create_authset(dauthd1, dauthm, id_data, pubkey, privkey, utoken, tenant_token=''):
    body, sighdr = deviceauth_v1.auth_req(id_data, pubkey, privkey, tenant_token)

    # submit auth req
    r = dauthd1.call('POST',
                     deviceauth_v1.URL_AUTH_REQS,
                     body,
                     headers=sighdr)
    assert r.status_code == 401

    # dev must exist and have *this* aset
    api_dev = get_device_by_id_data(dauthm, id_data, utoken)
    assert api_dev is not None

    aset = [a for a in api_dev['auth_sets'] if testutils.util.crypto.rsa_compare_keys(a['pubkey'], pubkey)]
    assert len(aset) == 1

    aset = aset[0]

    assert aset['identity_data'] == id_data
    assert aset['status'] == 'pending'

    return Authset(aset['id'], api_dev['id'], id_data, pubkey, privkey, 'pending')

def create_user(name, pwd, tid='', docker_prefix=None):
    cli = CliUseradm(docker_prefix)

    uid = cli.create_user(name, pwd, tid)

    return User(uid, name, pwd)

def create_tenant_user(idx, tenant, docker_prefix=None):
    name = 'user{}@{}.com'.format(idx, tenant.name)
    pwd = 'correcthorse'

    return create_user(name, pwd, tenant.id, docker_prefix)

def create_org(name, user, password):
    cli = CliTenantadm()

    return cli.create_org(name, user, password)


def get_device_by_id_data(dauthm, id_data, utoken):
    page = 0
    per_page = 20
    qs_params = {}
    found = None
    while True:
        page = page + 1
        qs_params['page'] = page
        qs_params['per_page'] = per_page
        r = dauthm.with_auth(utoken).call('GET',
                deviceauth_v2.URL_DEVICES, qs_params=qs_params)
        assert r.status_code == 200
        api_devs = r.json()

        found = [d for d in api_devs if d['identity_data']==id_data]
        if len(found) > 0:
            break

        if len(api_devs) == 0:
            break

    assert len(found) == 1

    return found[0]

def change_authset_status(dauthm, did, aid, status, utoken):
    r = dauthm.with_auth(utoken).call('PUT',
                                   deviceauth_v2.URL_AUTHSET_STATUS,
                                   deviceauth_v2.req_status(status),
                                   path_params={'did': did, 'aid': aid })
    assert r.status_code == 204

def rand_id_data():
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), 'x') for i in range(6)])
    sn = "".join(["{}".format(random.randint(0x00, 0xFF)) for i in range(6)])

    return {'mac': mac, 'sn': sn}

def make_pending_device(dauthd1, dauthm, utoken, tenant_token=''):
    id_data = rand_id_data()

    priv, pub = testutils.util.crypto.rsa_get_keypair()
    new_set = create_authset(dauthd1, dauthm, id_data, pub, priv, utoken, tenant_token=tenant_token)

    dev = Device(new_set.did, new_set.id_data, pub, tenant_token)

    dev.authsets.append(new_set)

    dev.status = 'pending'

    return dev

def make_accepted_device(dauthd1, dauthm, utoken, tenant_token=''):
    dev = make_pending_device(dauthd1, dauthm, utoken, tenant_token=tenant_token)
    aset_id = dev.authsets[0].id
    change_authset_status(dauthm, dev.id, aset_id, 'accepted', utoken)

    aset = dev.authsets[0]
    aset.status = 'accepted'

    # obtain auth token
    body, sighdr = deviceauth_v1.auth_req(aset.id_data,
                                          aset.pubkey,
                                          aset.privkey,
                                          tenant_token)

    r = dauthd1.call('POST',
                      deviceauth_v1.URL_AUTH_REQS,
                      body,
                      headers=sighdr)

    assert r.status_code == 200
    dev.token = r.text

    dev.status = 'accepted'

    return dev
