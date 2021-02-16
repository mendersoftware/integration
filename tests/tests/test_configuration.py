# Copyright 2021 Northern.tech AS
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
import time

from testutils.infra.cli import CliTenantadm
from testutils.infra.device import MenderDevice
from testutils.common import Tenant, User

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

        # set the device's configuration
        configuration = {"key": "value"}
        configuration_url = (
            "https://%s/api/management/v1/deviceconfig/configurations/device/%s"
            % (get_container_manager().get_mender_gateway(), devices[0])
        )
        auth = authentication.Authentication()
        r = requests_retry().put(
            configuration_url,
            verify=False,
            headers=auth.get_auth_token(),
            json=configuration,
        )

        # deploy the configurations
        r = requests_retry().post(
            configuration_url + "/deploy",
            verify=False,
            headers=auth.get_auth_token(),
            json={"retries": 0},
        )

        # loop and verify the reported configuration
        reported = None
        for i in range(180):
            r = requests_retry().get(
                configuration_url, verify=False, headers=auth.get_auth_token(),
            )
            assert r.status_code == 200
            reported = r.json().get("reported")
            if reported == configuration:
                break
            time.sleep(1)

        assert configuration == reported

        verify_update_was_forced(standard_setup_one_client.device)


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
        u = User("", "bugs.bunny@acme.org", "whatsupdoc")
        cli = CliTenantadm(containers_namespace=env.name)
        tid = cli.create_org("enterprise-tenant", u.name, u.pwd, plan="enterprise")
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
        enterprise_no_client.new_tenant_client(
            "configuration-test-container", tenant.tenant_token
        )
        mender_device = MenderDevice(enterprise_no_client.get_mender_clients()[0])
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

        # set the device's configuration
        configuration = {"key": "value"}
        configuration_url = (
            "https://%s/api/management/v1/deviceconfig/configurations/device/%s"
            % (get_container_manager().get_mender_gateway(), devices[0])
        )
        r = requests_retry().put(
            configuration_url,
            verify=False,
            headers=auth.get_auth_token(),
            json=configuration,
        )

        # deploy the configurations
        r = requests_retry().post(
            configuration_url + "/deploy",
            verify=False,
            headers=auth.get_auth_token(),
            json={"retries": 0},
        )

        # loop and verify the reported configuration
        reported = None
        for i in range(180):
            r = requests_retry().get(
                configuration_url, verify=False, headers=auth.get_auth_token(),
            )
            assert r.status_code == 200
            reported = r.json().get("reported")
            if reported == configuration:
                break
            time.sleep(1)

        assert configuration == reported

        verify_update_was_forced(mender_device)


def verify_update_was_forced(mender_device):
    """ Check that the update was triggered by update-check """

    out = mender_device.run(
        "journalctl -u %s -l" % mender_device.get_client_service_name()
    )
    assert "Forced wake-up from sleep" in out
    assert "Forcing state machine to: update-check" in out
