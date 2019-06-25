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
from pymongo import MongoClient

from api.client import ApiClient
from infra.cli import CliUseradm, CliTenantadm
import api.deviceauth as deviceauth_v1
import api.deviceauth_v2 as deviceauth_v2
import api.tenantadm as tenantadm
import util.crypto

@pytest.fixture(scope="session")
def mongo():
    return MongoClient('mender-mongo:27017')

@pytest.yield_fixture(scope='function')
def clean_mongo(mongo):
    """Fixture setting up a clean (i.e. empty database). Yields
    pymongo.MongoClient connected to the DB."""
    yield from _clean_mongo(mongo)

@pytest.yield_fixture(scope='class')
def clean_mongo_cls(mongo):
    """Fixture setting up a clean (i.e. empty database). Yields
    pymongo.MongoClient connected to the DB."""
    yield from _clean_mongo(mongo)

def _clean_mongo(mongo):
    mongo_cleanup(mongo)
    yield mongo
    mongo_cleanup(mongo)

def mongo_cleanup(mongo):
    dbs = mongo.database_names()
    dbs = [d for d in dbs if d not in ['local', 'admin']]
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


def create_tenant(name):
    """ Create a tenant via cli, record its id and token for further use.  """
    cli = CliTenantadm()
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

def create_random_authset(utoken, tenant_token=''):
    """ create_device with random id data and keypair"""
    priv, pub = util.crypto.rsa_get_keypair()
    mac = ":".join(["{:02x}".format(random.randint(0x00, 0xFF), 'x') for i in range(6)])
    id_data = {'mac': mac}

    return create_authset(id_data, pub, priv, utoken, tenant_token)

def create_authset(id_data, pubkey, privkey, utoken, tenant_token=''):
    api = ApiClient(deviceauth_v1.URL_DEVICES)

    body, sighdr = deviceauth_v1.auth_req(id_data, pubkey, privkey, tenant_token)

    # submit auth req
    r = api.call('POST',
                 deviceauth_v1.URL_AUTH_REQS,
                 body,
                 headers=sighdr)
    assert r.status_code == 401

    # dev must exist and have *this* aset
    api_dev = get_device_by_id_data(id_data, utoken)
    assert api_dev is not None

    aset = [a for a in api_dev['auth_sets'] if util.crypto.rsa_compare_keys(a['pubkey'], pubkey)]
    assert len(aset) == 1

    aset = aset[0]

    assert aset['identity_data'] == id_data 
    assert aset['status'] == 'pending' 

    return Authset(aset['id'], api_dev['id'], id_data, pubkey, privkey, 'pending')

def create_user(name, pwd, tid=''):
    cli = CliUseradm()

    uid = cli.create_user(name, pwd, tid)

    return User(uid, name, pwd)

def create_tenant_user(idx, tenant):
    name = 'user{}@{}.com'.format(idx, tenant.name)
    pwd = 'correcthorse'

    return create_user(name, pwd, tenant.id)

def get_device_by_id_data(id_data, utoken):
    devauthm = ApiClient(deviceauth_v2.URL_MGMT)
    page = 0
    per_page = 20
    qs_params = {}
    found = None
    while True:
        page = page + 1
        qs_params['page'] = page
        qs_params['per_page'] = per_page
        r = devauthm.with_auth(utoken).call('GET',
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

def change_authset_status(did, aid, status, utoken):
    devauthm = ApiClient(deviceauth_v2.URL_MGMT)
    r = devauthm.with_auth(utoken).call('PUT',
                                   deviceauth_v2.URL_AUTHSET_STATUS,
                                   deviceauth_v2.req_status(status),
                                   path_params={'did': did, 'aid': aid })
    assert r.status_code == 204
