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
import pytest
import redo
import time
import uuid

from testutils.infra.cli import CliTenantadm
from testutils.common import Tenant, User, update_tenant, new_tenant_client

from ..common_setup import standard_setup_one_client, enterprise_no_client
from ..MenderAPI import (
    Authentication,
    DeviceAuthV2,
    authentication,
    devauth,
    get_container_manager,
    logger,
)
from ..MenderAPI.requests_helpers import requests_retry
from .mendertesting import MenderTesting
from .common_connect import wait_for_connect


@pytest.mark.usefixtures("standard_setup_one_client")
class TestConfiguration(MenderTesting):
    """Tests the configuration deployment functionality"""

    def test_configuration(self, standard_setup_one_client):
        """Tests the deployment and reporting of the configuration

        The tests set the configuration of a device and verifies the new
        configuration is reported back to the back-end.
        """
        # accept the device
        devauth.accept_devices(1)

        # list of devices
        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        auth = authentication.Authentication()

        wait_for_connect(auth, devices[0])

        # set and verify the device's configuration
        # retry to skip possible race conditions between update poll and update trigger
        for _ in redo.retrier(attempts=3, sleeptime=1):
            set_and_verify_config({"key": "value"}, devices[0], auth.get_auth_token())

            forced = was_update_forced(standard_setup_one_client.device)
            if forced:
                return

        assert False, "the update check was never triggered"


@pytest.mark.usefixtures("enterprise_no_client")
class TestConfigurationEnterprise(MenderTesting):
    """Tests the configuration deployment functionality in the enterprise setup"""

    def test_configuration(self, enterprise_no_client):
        """Tests the deployment and reporting of the configuration

        The tests set the configuration of a device and verifies the new
        configuration is reported back to the back-end.
        """

        env = enterprise_no_client

        # Create an enterprise plan tenant
        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}".format(uuidv4)
        email = "some.user+{}@example.com".format(uuidv4)
        u = User("", email, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=env.name)
        tid = cli.create_org(tname, u.name, u.pwd, plan="enterprise")

        # what we really need is "configure"
        # but for trigger tests we're also checking device avail. in "deviceconnect"
        # so add "troubleshoot" as well
        update_tenant(
            tid,
            addons=["configure", "troubleshoot"],
            container_manager=get_container_manager(),
        )

        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]
        logger.info(f"tenant json: {tenant}")
        tenant = Tenant("tenant", tid, ttoken)
        tenant.users.append(u)

        # And authorize the user to the tenant account
        auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth_tenant = DeviceAuthV2(auth)

        # Add a client to the tenant
        mender_device = new_tenant_client(
            enterprise_no_client, "mender-client", tenant.tenant_token
        )
        mender_device.ssh_is_opened()

        devauth_tenant.accept_devices(1)

        # list of devices
        devices = list(
            set(
                [
                    device["id"]
                    for device in devauth_tenant.get_devices_status("accepted")
                ]
            )
        )
        assert 1 == len(devices)

        wait_for_connect(auth, devices[0])

        # set and verify the device's configuration
        # retry to skip possible race conditions between update poll and update trigger
        for _ in redo.retrier(attempts=3, sleeptime=1):
            set_and_verify_config({"key": "value"}, devices[0], auth.get_auth_token())

            forced = was_update_forced(mender_device)
            if forced:
                return

        assert False, "the update check was never triggered"


def was_update_forced(mender_device):
    """Check that the update was triggered by update-check
    It's possible that due to a race, the update was applied by normal check, blocking the update check trigger.
    Make sure which case it is.
    """

    out = mender_device.run(
        "journalctl -u %s -l" % mender_device.get_client_service_name()
    )
    if (
        "Forced wake-up from sleep" in out
        and "Forcing state machine to: update-check" in out
    ):
        return True
    elif "Cannot check update or update inventory while in update-fetch state" in out:
        # race condition - check-update came while we were already updating
        return False
    else:
        raise RuntimeError(
            "fatal: no expected evidence of an update was found in device logs"
        )


def set_and_verify_config(config, devid, authtoken):
    """ Deploy a configuration and assert it was reported back """

    configuration_url = (
        "https://%s/api/management/v1/deviceconfig/configurations/device/%s"
        % (get_container_manager().get_mender_gateway(), devid)
    )
    r = requests_retry().put(
        configuration_url, verify=False, headers=authtoken, json=config,
    )

    # deploy the configurations
    r = requests_retry().post(
        configuration_url + "/deploy",
        verify=False,
        headers=authtoken,
        json={"retries": 0},
    )

    # loop and verify the reported configuration
    reported = None
    for i in range(180):
        r = requests_retry().get(configuration_url, verify=False, headers=authtoken)
        assert r.status_code == 200
        reported = r.json().get("reported")
        if reported == config:
            break
        time.sleep(1)

    assert config == reported
