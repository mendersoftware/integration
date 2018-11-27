#!/usr/bin/python
# Copyright 2016 Mender Software AS
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
import api.tenantadm as tenantadm
import util.crypto

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
    dbs = [d for d in dbs if d not in ['local', 'admin']]
    for d in dbs:
        mongo.drop_database(d)


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
