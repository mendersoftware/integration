# Copyright 2022 Northern.tech AS
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
import time
import json

import pytest

from integration_testutils.common import create_user, make_accepted_device, User, Tenant
from integration_testutils.api.client import ApiClient
from integration_testutils.infra.cli import CliTenantadm
import integration_testutils.api.deviceauth as deviceauth
import integration_testutils.api.deployments as deployments
import integration_testutils.api.useradm as useradm
from integration_testutils.infra.container_manager import factory

# This test requires special manipulation of containers, so it will use
# directly the factory to prepare fixtures instead of common_setup
container_factory = factory.get_factory()


@pytest.fixture(scope="class")
def initial_os_setup(request):
    """Start the minimum OS setup, create some uses and devices.
    Return {"os_devs": [...], "os_users": [...]}
    """
    os_env = container_factory.get_standard_setup(num_clients=0)
    # We will later re-create other environments, but this one (or any, really) will be
    # enough for the teardown if we keep using the same namespace.
    request.addfinalizer(os_env.teardown)

    os_env.setup()
    os_env.init_data = initialize_os_setup(os_env)

    return os_env


@pytest.fixture(scope="class")
def initial_enterprise_setup(initial_os_setup):
    """
    Start ENT for the first time (no tenant yet).
    """
    initial_os_setup.teardown_exclude(["mender-mongo"])

    # Create a new env reusing the same namespace
    ent_no_tenant_env = container_factory.get_enterprise_setup(
        initial_os_setup.name, num_clients=0
    )
    ent_no_tenant_env.setup()

    return initial_os_setup


@pytest.fixture(scope="class")
def migrated_enterprise_setup(initial_enterprise_setup):
    """
    Create an org (tenant + user), restart with default tenant token.
    The ENT setup is ready for tests.
    Return {"os_devs": [...], "os_users": [...], "tenant": <Tenant>}
    """
    ent_data = migrate_ent_setup(initial_enterprise_setup)

    # preserve the user/tenant created before restart
    initial_enterprise_setup.teardown_exclude(["mender-mongo"])

    # Create a new env reusing the same namespace
    ent_with_tenant_env = container_factory.get_enterprise_setup(
        initial_enterprise_setup.name, num_clients=0
    )
    ent_with_tenant_env.setup(
        recreate=False,
        env={"DEFAULT_TENANT_TOKEN": "%s" % ent_data["tenant"].tenant_token},
    )

    initial_enterprise_setup.init_data = dict(
        {**ent_data, **initial_enterprise_setup.init_data}
    )
    return initial_enterprise_setup


def initialize_os_setup(env):
    """Seed the OS setup with all operational data - users and devices.
    Return {"os_devs": [...], "os_users": [...]}
    """
    uadmm = ApiClient(useradm.URL_MGMT, host=env.get_mender_gateway())
    dauthd = ApiClient(deviceauth.URL_DEVICES, host=env.get_mender_gateway())
    dauthm = ApiClient(deviceauth.URL_MGMT, host=env.get_mender_gateway())

    users = [
        create_user("foo@tenant.com", "correcthorse", containers_namespace=env.name),
        create_user("bar@tenant.com", "correcthorse", containers_namespace=env.name),
    ]

    r = uadmm.call("POST", useradm.URL_LOGIN, auth=(users[0].name, users[0].pwd))

    assert r.status_code == 200
    utoken = r.text

    # create and accept some devs; save tokens
    devs = []
    for _ in range(10):
        devs.append(make_accepted_device(dauthd, dauthm, utoken))

    # get tokens for all
    for d in devs:
        body, sighdr = deviceauth.auth_req(
            d.id_data, d.authsets[0].pubkey, d.authsets[0].privkey
        )

        r = dauthd.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)

        assert r.status_code == 200
        d.token = r.text

    return {"os_devs": devs, "os_users": users}


def migrate_ent_setup(env):
    """Migrate the ENT setup - create a tenant and user via create-org,
    substitute default token env in the ent. testing layer.
    """
    # extra long sleep to make sure all services ran their migrations
    # maybe conductor fails because some services are still in a migration phase,
    # and not serving the API yet?
    time.sleep(30)

    u = User("", "baz@tenant.com", "correcthorse")

    cli = CliTenantadm(containers_namespace=env.name)
    tid = cli.create_org("tenant", u.name, u.pwd)
    time.sleep(10)

    tenant = cli.get_tenant(tid)

    tenant = json.loads(tenant)
    ttoken = tenant["tenant_token"]

    t = Tenant("tenant", tid, ttoken)
    t.users.append(u)

    return {"tenant": t}


@pytest.mark.usefixtures("migrated_enterprise_setup")
class TestEnterpriseMigration:
    def test_users_ok(self, migrated_enterprise_setup):
        mender_gateway = migrated_enterprise_setup.get_mender_gateway()
        uadmm = ApiClient(useradm.URL_MGMT, host=mender_gateway)

        # os users can't log in
        for u in migrated_enterprise_setup.init_data["os_users"]:
            r = uadmm.call("POST", useradm.URL_LOGIN, auth=(u.name, u.pwd))
            assert r.status_code == 401

        # but enterprise user can
        ent_user = migrated_enterprise_setup.init_data["tenant"].users[0]
        r = uadmm.call("POST", useradm.URL_LOGIN, auth=(ent_user.name, ent_user.pwd))
        assert r.status_code == 200

    def test_devs_ok(self, migrated_enterprise_setup):
        mender_gateway = migrated_enterprise_setup.get_mender_gateway()
        uadmm = ApiClient(useradm.URL_MGMT, host=mender_gateway)
        dauthd = ApiClient(deviceauth.URL_DEVICES, host=mender_gateway)
        dauthm = ApiClient(deviceauth.URL_MGMT, host=mender_gateway)
        depld = ApiClient(deployments.URL_DEVICES, host=mender_gateway)

        # current dev tokens don't work right off the bat
        # the deviceauth db is empty
        for d in migrated_enterprise_setup.init_data["os_devs"]:
            resp = depld.with_auth(d.token).call(
                "GET",
                deployments.URL_NEXT,
                qs_params={"artifact_name": "foo", "device_type": "bar"},
            )

            assert resp.status_code == 401

        # but even despite the 'dummy' tenant token
        # os devices can get into the deviceauth db for acceptance
        ent_user = migrated_enterprise_setup.init_data["tenant"].users[0]
        r = uadmm.call("POST", useradm.URL_LOGIN, auth=(ent_user.name, ent_user.pwd))
        assert r.status_code == 200
        utoken = r.text

        for d in migrated_enterprise_setup.init_data["os_devs"]:
            body, sighdr = deviceauth.auth_req(
                d.id_data,
                d.authsets[0].pubkey,
                d.authsets[0].privkey,
                tenant_token="dummy",
            )

            r = dauthd.call("POST", deviceauth.URL_AUTH_REQS, body, headers=sighdr)

            assert r.status_code == 401

        r = dauthm.with_auth(utoken).call(
            "GET", deviceauth.URL_MGMT_DEVICES, path_params={"id": d.id}
        )

        assert r.status_code == 200
        assert len(r.json()) == len(migrated_enterprise_setup.init_data["os_devs"])
