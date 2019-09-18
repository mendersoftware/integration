#!/usr/bin/python
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
import logging
import subprocess
import requests
import time
import json

from ..conftest import docker_compose_instance

from ..common_docker import *
from .conductor import Conductor

from testutils.common import create_user, make_accepted_device, Device, User, Tenant
from testutils.api.client import ApiClient
from testutils.infra.cli import CliTenantadm
import testutils.api.deviceauth as deviceauth_v1
import testutils.api.deviceauth_v2 as deviceauth_v2
import testutils.api.deployments as deployments
import testutils.api.useradm as useradm

@pytest.fixture(scope="class")
def initial_os_setup():
    """ Start the minimum OS setup, create some uses and devices. 
        Return {"os_devs": [...], "os_users": [...]}
    """

    stop_docker_compose()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml up -d",
                       use_common_files=False)
    ensure_conductor_ready(60, 'provision_device')

    init_data = initialize_os_setup()

    return init_data

@pytest.fixture(scope="class")
def initial_enterprise_setup(initial_os_setup):
    """
        Start ENT for the first time (no tenant yet).
    """
    stop_docker_compose_exclude(['mender-mongo'])

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml up -d",
                       use_common_files=False)

    return initial_os_setup

@pytest.fixture(scope="class")
def migrated_enterprise_setup(initial_enterprise_setup):
    """
        Create an org (tenant + user), restart with default tenant token.
        The ENT setup is ready for tests.
        Return {"os_devs": [...], "os_users": [...], "tenant": <Tenant>}
    """
    ent_data = migrate_ent_setup()

    # preserve the user/tenant created before restart
    stop_docker_compose_exclude(['mender-mongo'])

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.enterprise.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml up -d --no-recreate",
                       use_common_files=False)

    return dict(ent_data.items() + initial_enterprise_setup.items())

def initialize_os_setup():
    """ Seed the OS setup with all operational data - users and devices. 
        Return {"os_devs": [...], "os_users": [...]}
    """
    uadmm = ApiClient('https://{}/api/management/v1/useradm'.format(get_mender_gateway()))
    dauthd = ApiClient('https://{}/api/devices/v1/authentication'.format(get_mender_gateway()))
    dauthm = ApiClient('https://{}/api/management/v2/devauth'.format(get_mender_gateway()))

    users = [create_user("foo@tenant.com", "correcthorse", docker_prefix=docker_compose_instance),
             create_user("bar@tenant.com", "correcthorse", docker_prefix=docker_compose_instance)]

    r = uadmm.call('POST',
                   useradm.URL_LOGIN,
                   auth=(users[0].name, users[0].pwd))

    assert r.status_code == 200
    utoken = r.text

    # create and accept some devs; save tokens
    devs = []
    for i in range(10):
        devs.append(make_accepted_device(dauthd, dauthm, utoken))

    # get tokens for all
    for d in devs:
        body, sighdr = deviceauth_v1.auth_req(
                            d.id_data,
                            d.authsets[0].pubkey,           
                            d.authsets[0].privkey)

        r = dauthd.call('POST',
                        deviceauth_v1.URL_AUTH_REQS,
                        body,
                        headers=sighdr)

        assert r.status_code == 200
        d.token=r.text

    return {"os_devs": devs, "os_users": users}

def migrate_ent_setup():
    """ Migrate the ENT setup - create a tenant and user via create-org,
        substitute default token env in the ent. testing layer. 
    """
    ensure_conductor_ready(60, 'create_organization')

    u = User('', 'baz@tenant.com', 'correcthorse')

    cli = CliTenantadm(docker_prefix=docker_compose_instance)
    tid = cli.create_org('tenant', u.name, u.pwd)
    time.sleep(5)

    tenant = cli.get_tenant(tid)

    tenant = json.loads(tenant)
    ttoken = tenant['tenant_token']

    sed = "sed 's/$DEFAULT_TENANT_TOKEN/{}/' ".format(ttoken) + \
          os.path.join(COMPOSE_FILES_PATH, "docker-compose.testing.enterprise.yml.template") + \
          " > " + \
          os.path.join(COMPOSE_FILES_PATH, "docker-compose.testing.enterprise.yml")

    subprocess.check_call(sed, shell=True)

    t = Tenant('tenant', tid, ttoken)
    t.users.append(u)

    return {"tenant": t}

@pytest.mark.usefixtures("migrated_enterprise_setup")
class TestEntMigration:
    def test_users_ok(self, migrated_enterprise_setup):
        uadmm = ApiClient('https://{}/api/management/v1/useradm'.format(get_mender_gateway()))

        # os users can't log in
        for u in migrated_enterprise_setup["os_users"]:
            r = uadmm.call('POST', useradm.URL_LOGIN, auth=(u.name, u.pwd))
            assert r.status_code == 401

        # but enterprise user can 
        ent_user = migrated_enterprise_setup["tenant"].users[0]
        r = uadmm.call('POST', 
                       useradm.URL_LOGIN, 
                       auth=(ent_user.name, ent_user.pwd))
        assert r.status_code == 200

    def test_devs_ok(self, migrated_enterprise_setup):
        uadmm = ApiClient('https://{}/api/management/v1/useradm'.format(get_mender_gateway()))
        dauthd = ApiClient('https://{}/api/devices/v1/authentication'.format(get_mender_gateway()))
        dauthm = ApiClient('https://{}/api/management/v2/devauth'.format(get_mender_gateway()))
        depld = ApiClient('https://{}/api/devices/v1/deployments'.format(get_mender_gateway()))

        # current dev tokens don't work right off the bat
        # the deviceauth db is empty
        for d in migrated_enterprise_setup["os_devs"]:
            resp = depld.with_auth(d.token).call(
                'GET',
                deployments.URL_NEXT,
                qs_params={"artifact_name": 'foo',
                           "device_type"  : 'bar'})

            assert resp.status_code == 401

        # but even despite the 'dummy' tenant token
        # os devices can get into the deviceauth db for acceptance
        ent_user = migrated_enterprise_setup["tenant"].users[0]
        r = uadmm.call('POST', 
                       useradm.URL_LOGIN, 
                       auth=(ent_user.name, ent_user.pwd))
        assert r.status_code == 200
        utoken=r.text

        for d in migrated_enterprise_setup["os_devs"]:
            body, sighdr = deviceauth_v1.auth_req(
                                d.id_data,
                                d.authsets[0].pubkey,           
                                d.authsets[0].privkey,
                                tenant_token='dummy')

            r = dauthd.call('POST',
                        deviceauth_v1.URL_AUTH_REQS,
                        body,
                        headers=sighdr)

            assert r.status_code == 401


        r = dauthm.with_auth(utoken).call('GET',
                                          deviceauth_v2.URL_DEVICES,
                                          path_params={'id': d.id})

        assert r.status_code == 200
        assert len(r.json()) == len(migrated_enterprise_setup["os_devs"])

def ensure_conductor_ready(max_time=120, wfname='create_organization'):
    """
    Wait on:
    - conductor api being up, not refusing conns 
    - a particular workflow being available.
    """
    ip = get_mender_conductor()
    for i in range(max_time):
        try:
            r = requests.get("http://{}:8080/api/metadata/workflow/{}".format(ip, wfname))
            if r.status_code != 404:
                return 
        except requests.ConnectionError:
            pass

        time.sleep(1)

    raise RuntimeError('waiting for conductor timed out')
