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
import subprocess
import time
import json
import os

import requests
import pytest

from testutils.common import create_user, make_accepted_device, User, Tenant
from testutils.api.client import ApiClient
from testutils.infra.cli import CliTenantadm
import testutils.api.deviceauth as deviceauth_v1
import testutils.api.deviceauth_v2 as deviceauth_v2
import testutils.api.deployments as deployments
import testutils.api.useradm as useradm
from ..conftest import docker_compose_instance
from ..common_setup import standard_setup_without_client

@pytest.fixture(scope="function")
def initial_os_setup(standard_setup_without_client):
    """ Start the minimum OS setup, create some uses and devices.
        Return {"os_devs": [...], "os_users": [...]}
    """
    ensure_conductor_ready(standard_setup_without_client.get_mender_conductor(), 60, 'provision_device')

    standard_setup_without_client.init_data = initialize_os_setup(standard_setup_without_client)

    return standard_setup_without_client

@pytest.fixture(scope="function")
def initial_enterprise_setup(initial_os_setup):
    """
        Start ENT for the first time (no tenant yet).
    """
    initial_os_setup.stop_docker_compose_exclude(['mender-mongo'])

    initial_os_setup.docker_compose_cmd("-f " + initial_os_setup.COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + initial_os_setup.COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml \
                        -f " + initial_os_setup.COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + initial_os_setup.COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml up -d",
                       use_common_files=False)

    return initial_os_setup

@pytest.fixture(scope="function")
def migrated_enterprise_setup(initial_enterprise_setup):
    """
        Create an org (tenant + user), restart with default tenant token.
        The ENT setup is ready for tests.
        Return {"os_devs": [...], "os_users": [...], "tenant": <Tenant>}
    """
    ent_data = migrate_ent_setup(initial_enterprise_setup)

    # preserve the user/tenant created before restart
    initial_enterprise_setup.stop_docker_compose_exclude(['mender-mongo'])

    initial_enterprise_setup.docker_compose_cmd("-f " + initial_enterprise_setup.COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + initial_enterprise_setup.COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml \
                        -f " + initial_enterprise_setup.COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + initial_enterprise_setup.COMPOSE_FILES_PATH + "/docker-compose.testing.enterprise.yml \
                        -f " + initial_enterprise_setup.COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml up -d --no-recreate",
                       use_common_files=False)

    initial_enterprise_setup.init_data = dict(ent_data.items() + initial_enterprise_setup.init_data.items())
    return initial_enterprise_setup

def initialize_os_setup(env):
    """ Seed the OS setup with all operational data - users and devices.
        Return {"os_devs": [...], "os_users": [...]}
    """
    uadmm = ApiClient('https://{}/api/management/v1/useradm'.format(env.get_mender_gateway()))
    dauthd = ApiClient('https://{}/api/devices/v1/authentication'.format(env.get_mender_gateway()))
    dauthm = ApiClient('https://{}/api/management/v2/devauth'.format(env.get_mender_gateway()))

    users = [create_user("foo@tenant.com", "correcthorse", containers_namespace=docker_compose_instance),
             create_user("bar@tenant.com", "correcthorse", containers_namespace=docker_compose_instance)]

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

def migrate_ent_setup(env):
    """ Migrate the ENT setup - create a tenant and user via create-org,
        substitute default token env in the ent. testing layer.
    """
    ensure_conductor_ready(env.get_mender_conductor(), 60, 'create_organization')

    # extra long sleep to make sure all services ran their migrations
    # maybe conductor fails because some services are still in a migration phase,
    # and not serving the API yet?
    time.sleep(30)

    u = User('', 'baz@tenant.com', 'correcthorse')

    cli = CliTenantadm(containers_namespace=docker_compose_instance)
    tid = cli.create_org('tenant', u.name, u.pwd)
    time.sleep(10)

    tenant = cli.get_tenant(tid)

    tenant = json.loads(tenant)
    ttoken = tenant['tenant_token']

    sed = "sed 's/$DEFAULT_TENANT_TOKEN/{}/' ".format(ttoken) + \
          os.path.join(env.COMPOSE_FILES_PATH, "docker-compose.testing.enterprise.yml.template") + \
          " > " + \
          os.path.join(env.COMPOSE_FILES_PATH, "docker-compose.testing.enterprise.yml")

    subprocess.check_call(sed, shell=True)

    t = Tenant('tenant', tid, ttoken)
    t.users.append(u)

    return {"tenant": t}

@pytest.mark.usefixtures("migrated_enterprise_setup")
class TestEntMigration:
    def test_users_and_devs_ok(self, migrated_enterprise_setup):
        mender_gateway = migrated_enterprise_setup.get_mender_gateway()
        uadmm = ApiClient('https://{}/api/management/v1/useradm'.format(mender_gateway))

        # os users can't log in
        for u in migrated_enterprise_setup.init_data["os_users"]:
            r = uadmm.call('POST', useradm.URL_LOGIN, auth=(u.name, u.pwd))
            assert r.status_code == 401

        # but enterprise user can
        ent_user = migrated_enterprise_setup.init_data["tenant"].users[0]
        r = uadmm.call('POST',
                       useradm.URL_LOGIN,
                       auth=(ent_user.name, ent_user.pwd))
        assert r.status_code == 200

        mender_gateway = migrated_enterprise_setup.get_mender_gateway()
        uadmm = ApiClient('https://{}/api/management/v1/useradm'.format(mender_gateway))
        dauthd = ApiClient('https://{}/api/devices/v1/authentication'.format(mender_gateway))
        dauthm = ApiClient('https://{}/api/management/v2/devauth'.format(mender_gateway))
        depld = ApiClient('https://{}/api/devices/v1/deployments'.format(mender_gateway))

        # current dev tokens don't work right off the bat
        # the deviceauth db is empty
        for d in migrated_enterprise_setup.init_data["os_devs"]:
            resp = depld.with_auth(d.token).call(
                'GET',
                deployments.URL_NEXT,
                qs_params={"artifact_name": 'foo',
                           "device_type"  : 'bar'})

            assert resp.status_code == 401

        # but even despite the 'dummy' tenant token
        # os devices can get into the deviceauth db for acceptance
        ent_user = migrated_enterprise_setup.init_data["tenant"].users[0]
        r = uadmm.call('POST',
                       useradm.URL_LOGIN,
                       auth=(ent_user.name, ent_user.pwd))
        assert r.status_code == 200
        utoken=r.text

        for d in migrated_enterprise_setup.init_data["os_devs"]:
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
        assert len(r.json()) == len(migrated_enterprise_setup.init_data["os_devs"])

def ensure_conductor_ready(ip, max_time=120, wfname='create_organization'):
    """
    Wait on:
    - conductor api being up, not refusing conns
    - a particular workflow being available.
    """
    for i in range(max_time):
        try:
            r = requests.get("http://{}:8080/api/metadata/workflow/{}".format(ip, wfname))
            if r.status_code != 404:
                return
        except requests.ConnectionError:
            pass

        time.sleep(1)

    raise RuntimeError('waiting for conductor timed out')
