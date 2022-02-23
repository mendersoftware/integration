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
#

import json
import os
import os.path
import pytest
import shutil
import tempfile
import time
import uuid
import inspect

from email.parser import Parser
from email.policy import default
from redo import retriable
from ..common_setup import monitor_commercial_setup_no_client

from ..MenderAPI import (
    authentication,
    get_container_manager,
    DeviceAuthV2,
    DeviceMonitor,
    Inventory,
    logger,
)

from testutils.api import useradm
from testutils.api.client import ApiClient
from testutils.infra.container_manager import factory
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra import smtpd_mock
from testutils.common import User, new_tenant_client
from testutils.infra.cli import CliTenantadm

container_factory = factory.get_factory()


def configure_connectivity(
    mender_device,
    disable_keep_alive=False,
    idle_connections_timeout_seconds=0,
    inventory_poll=5,
    update_poll=5,
):
    mender_device.run("cp /etc/mender/mender.conf /etc/mender/mender.conf.backup")
    output = mender_device.run("cat /etc/mender/mender.conf")
    config = json.loads(output)
    config["Connectivity"] = {
        "DisableKeepAlive": disable_keep_alive,
        "IdleConnTimeoutSeconds": idle_connections_timeout_seconds,
    }
    config["InventoryPollIntervalSeconds"] = inventory_poll
    config["UpdatePollIntervalSeconds"] = update_poll
    tmpdir = tempfile.mkdtemp()
    mender_conf = os.path.join(tmpdir, "mender.conf")
    with open(mender_conf, "w") as fd:
        json.dump(config, fd)
    mender_device.put(
        os.path.basename(mender_conf),
        local_path=os.path.dirname(mender_conf),
        remote_path="/etc/mender",
    )
    mender_device.run("systemctl stop mender-connect || true")
    mender_device.run("systemctl stop mender-monitor || true")
    mender_device.run("systemctl restart mender-client")


def clean_config(mender_device):
    mender_device.run(
        "mv /etc/mender/mender.conf.backup /etc/mender/mender.conf || true"
    )
    mender_device.run("systemctl start mender-connect || true")
    mender_device.run("systemctl start mender-monitor || true")
    mender_device.run("systemctl restart mender-client || true")


# TestMenderClientKeepAlive
# purpose: test the keep alive connections, the complete disable (no connections kept)
#          and the idle timeout (close connections after given time elapses)
# general idea:
#  * start the client with default options (this is 5s intervals as of today)
#  * verify that we have at least one connection to the backend
#  * configure DisableKeepAlive (test_keepalive_disable)
#    * restart mender-client and expect 0 connections
#  * configure IdleConnTimeoutSeconds while DisableKeepAlive is false (test_keepalive_idle_connections)
#    * expect the connection count to drop to 0 after given timeout
class TestMenderClientKeepAlive:
    """Tests for the Mender client and keep alive connections"""

    def prepare_env(self, env, user_name):
        u = User("", user_name, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=env.name)

        uuidv4 = str(uuid.uuid4())
        name = "test.mender.io-" + uuidv4
        tid = cli.create_org(name, u.name, u.pwd, plan="enterprise")

        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)

        auth = authentication.Authentication(name=name, username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth_tenant = DeviceAuthV2(auth)

        mender_device = new_tenant_client(env, "test-container", tenant["tenant_token"])
        mender_device.ssh_is_opened()

        devauth_tenant.accept_devices(1)

        logger.info("%s: env ready.", inspect.stack()[1].function)
        return mender_device

    def test_keepalive_idle_connections(self, monitor_commercial_setup_no_client):
        """Tests the closing of persistent connections on timeout"""
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        mender_device = self.prepare_env(monitor_commercial_setup_no_client, user_name)

        idle_connections_timeout_seconds = 15
        disable_keep_alive = False
        output = mender_device.run("netstat -4np | grep -F /mender | wc -l")
        logger.info("test_keepalive_idle_connections got: '%s'",output)
        t="/tmp/bp0"
        logger.info("test_keepalive_idle_connections waiting on '%s'",t)
        while not os.path.exists(t):
         time.sleep(0.4)
        assert int(output) > 1

        configure_connectivity(
            mender_device,
            disable_keep_alive=disable_keep_alive,
            idle_connections_timeout_seconds=idle_connections_timeout_seconds,
            inventory_poll=3600,
            update_poll=3600,
        )
        time.sleep(1)
        output = mender_device.run("netstat -4np | grep -F /mender | wc -l")
        t="/tmp/bp1"
        logger.info("test_keepalive_idle_connections waiting on '%s'",t)
        while not os.path.exists(t):
         time.sleep(0.4)

        assert int(output) == 1

        logger.info(
            "test_keepalive_idle_connections: waiting for IdleConnTimeoutSeconds to elapse"
        )
        time.sleep(1.5 * idle_connections_timeout_seconds)
        output = mender_device.run("netstat -4np | grep -F /mender | wc -l")
        clean_config(mender_device)
        t="/tmp/bp2"
        logger.info("test_keepalive_idle_connections waiting on '%s'",t)
        while not os.path.exists(t):
         time.sleep(0.4)

        assert int(output) == 0
        logger.info("test_keepalive_idle_connections: ok, no connections to backend")

    def test_keepalive_disable(self, monitor_commercial_setup_no_client):
        """Tests the closing of persistent connections on timeout"""
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        mender_device = self.prepare_env(monitor_commercial_setup_no_client, user_name)

        disable_keep_alive = True
        output = mender_device.run("netstat -4np | grep -F /mender | wc -l")
        assert int(output) > 1

        configure_connectivity(mender_device, disable_keep_alive=disable_keep_alive)
        logger.info("test_keepalive_disable: waiting for client to restart")
        time.sleep(1)
        output = mender_device.run("netstat -4np | grep -F /mender | wc -l")
        clean_config(mender_device)
        assert int(output) == 0
        logger.info("test_keepalive_disable: ok, no connections to backend")
