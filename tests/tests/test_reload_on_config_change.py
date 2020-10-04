# Copyright 2020 Northern.tech AS
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

import json
import os.path
import pytest
import shutil
import tempfile
import time

from testutils.common import create_org
from testutils.infra.container_manager import factory
from testutils.infra.device import MenderDevice

from .. import conftest
from ..MenderAPI import reset_mender_api, auth, deploy, devauth, logger
from .common_artifact import get_script_artifact
from .mendertesting import MenderTesting

container_factory = factory.get_factory()


@pytest.fixture(scope="function")
def setup_ent_reload(request):
    env = container_factory.getEnterpriseSetup()
    request.addfinalizer(env.teardown)
    env.setup()

    env.reload_username = "reload@mender.io"
    env.reload_password = "correcthorsebatterystaple"

    env.tenant = create_org(
        "Mender",
        env.reload_username,
        env.reload_password,
        containers_namespace=env.name,
        container_manager=env,
    )
    env.user = env.tenant.users[0]

    env.newtenant = create_org(
        "Mender Chain",
        "chain" + env.reload_username,
        env.reload_password,
        containers_namespace=env.name,
        container_manager=env,
    )
    env.newuser = env.tenant.users[0]

    reset_mender_api(env)

    auth.username = env.reload_username
    auth.password = env.reload_password
    auth.multitenancy = True
    auth.current_tenant = env.tenant
    #     auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
    auth.create_org = False
    auth.reset_auth_token()

    # start a new mender client
    env.new_tenant_client("mender-client", env.tenant.tenant_token)
    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    return env


class TestClientReloadOnTokenChange:
    @MenderTesting.fast
    @pytest.mark.parametrize("algorithm", ["rsa"])
    def test_reload_on_token_change(self, setup_ent_reload, algorithm):
        tmpdir = tempfile.mkdtemp()
        try:
            # retrieve the original configuration file
            output = setup_ent_reload.device.run("cat /etc/mender/mender.conf")
            logger.info('mender.conf: "\n%s\n"' % output)
            config = json.loads(output)
            # replace mender.conf with an mTLS enabled one
            config["TenantToken"] = setup_ent_reload.tenant.tenant_token
            logger.info(
                'in mender.conf: replacing "TenantToken" with :"%s"'
                % setup_ent_reload.tenant.tenant_token
            )
            mender_conf = os.path.join(tmpdir, "mender.conf")
            with open(mender_conf, "w") as fd:
                json.dump(config, fd)
            setup_ent_reload.device.put(
                os.path.basename(mender_conf),
                local_path=os.path.dirname(mender_conf),
                remote_path="/etc/mender",
            )
        finally:
            shutil.rmtree(tmpdir)

        client_service_name = setup_ent_reload.device.get_client_service_name()
        setup_ent_reload.device.run("systemctl restart %s" % client_service_name)

        time.sleep(30)
        # Get the pid of the mender process, can we assume that we have pidof?
        output = setup_ent_reload.device.run("pidof mender", hide=True)
        pid0 = output.rstrip()
        logger.info("mender pid :%s" % pid0)

        # Check if the client has started
        output = setup_ent_reload.device.run(
            "journalctl -u %s | grep 'Mender running'"
            % setup_ent_reload.device.get_client_service_name()
        )
        assert "Mender running" in output

        # set to tenant0
        auth.username = setup_ent_reload.reload_username
        auth.password = setup_ent_reload.reload_password
        auth.multitenancy = True
        auth.current_tenant = setup_ent_reload.tenant
        auth.create_org = False
        auth.reset_auth_token()

        devices = devauth.get_devices_status("pending")
        assert len(devices) == 1
        device_id0 = devices[0]["id"]

        tmpdir = tempfile.mkdtemp()
        try:
            # retrieve the original configuration file
            output = setup_ent_reload.device.run("cat /etc/mender/mender.conf")

            config = json.loads(output)
            # replace mender.conf with an mTLS enabled one
            config["TenantToken"] = setup_ent_reload.newtenant.tenant_token
            mender_conf = os.path.join(tmpdir, "mender.conf")
            with open(mender_conf, "w") as fd:
                json.dump(config, fd)
            setup_ent_reload.device.put(
                os.path.basename(mender_conf),
                local_path=os.path.dirname(mender_conf),
                remote_path="/etc/mender",
            )
        finally:
            shutil.rmtree(tmpdir)

        # set to tenant1
        auth.username = "chain" + setup_ent_reload.reload_username
        auth.password = setup_ent_reload.reload_password
        auth.multitenancy = True
        auth.current_tenant = setup_ent_reload.newtenant
        auth.create_org = False
        auth.reset_auth_token()

        # here check if the device is in pending
        devauth.get_devices(expected_devices=1)
        devices = devauth.get_devices_status("pending")
        assert len(devices) == 1
        device_id1 = devices[0]["id"]

        # Get the pid of the mender process
        output = setup_ent_reload.device.run("pidof mender", hide=True)
        pid1 = output.rstrip()

        time.sleep(30)
        # Check if the client has started
        output = setup_ent_reload.device.run(
            "journalctl -u %s | cat" % setup_ent_reload.device.get_client_service_name()
        )
        assert "Mender running" in output
        #         assert "restarting on SIGHUP" in output

        # the pid0 and pid1 should be non-empty and same -- the restarth isusing exec
        assert len(pid0) > 0
        assert len(pid1) > 0
        assert pid0 == pid1

        # here check if the device is in pending, maybe even accept it.
        devauth.get_devices(expected_devices=1)
        devices = devauth.get_devices_status("pending")
        assert len(devices) == 1
        device_id1 = devices[0]["id"]

        # device is should change
        assert device_id1 != device_id0
