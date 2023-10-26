# Copyright 2023 Northern.tech AS
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

import pytest

from ..common_setup import (
    standard_setup_one_client,
    standard_setup_one_client_bootstrapped,
    enterprise_one_client,
    enterprise_one_client_bootstrapped,
)
from .common_update import common_update_procedure
from ..MenderAPI import DeviceAuthV2, Deployments, logger
from ..helpers import Helpers
from .mendertesting import MenderTesting


class BaseTestBootstrapping(MenderTesting):
    MENDER_STORE = "/data/mender/mender-store"

    def do_test_bootstrap(self, env):
        """Simply make sure we are able to bootstrap a device"""

        mender_device = env.device

        devauth = DeviceAuthV2(env.auth)
        devauth.check_expected_status("pending", 1)

        # iterate over devices and accept them
        for d in devauth.get_devices():
            devauth.set_device_auth_set_status(
                d["id"], d["auth_sets"][0]["id"], "accepted"
            )
            logger.info("Accepting DeviceID: %s" % d["id"])

        # make sure all devices are accepted
        devauth.check_expected_status("accepted", 1)

        Helpers.check_log_have_authtoken(mender_device)

        # print all device ids
        for device in devauth.get_devices_status("accepted"):
            logger.info("Accepted DeviceID: %s" % device["id"])

    def do_test_reject_bootstrap(self, env, valid_image):
        """Make sure a rejected device does not perform an upgrade, and that it gets it's auth token removed"""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        reject_time = time.time()

        # iterate over devices and reject them
        for device in devauth.get_devices():
            devauth.set_device_auth_set_status(
                device["id"], device["auth_sets"][0]["id"], "rejected"
            )
            logger.info("Rejecting DeviceID: %s" % device["id"])

        devauth.check_expected_status("rejected", 1)

        host_ip = env.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            try:
                common_update_procedure(
                    install_image=valid_image, devauth=devauth, deploy=deploy
                )
            except AssertionError:
                logger.info("Failed to deploy upgrade to rejected device.")
                reboot.verify_reboot_not_performed()

            else:
                # use assert to fail, so we can get backend logs
                pytest.fail("no error while trying to deploy to rejected device")

        # Check from client side
        mender_device.run(
            "journalctl -u mender-authd -l -S '%s' | grep -q 'Failed to authorize with the server'"
            % (
                time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(reject_time)),
            )
        )

        # Restart client to force log reset.
        mender_device.run("systemctl restart mender-updated")

        # Check that we can accept again the device from the server
        devauth.accept_devices(1)

        # Check from client side that it can be authorized
        Helpers.check_log_have_authtoken(mender_device)


class TestBootstrappingOpenSource(BaseTestBootstrapping):
    @MenderTesting.fast
    def test_bootstrap(self, standard_setup_one_client):
        self.do_test_bootstrap(standard_setup_one_client)

    @MenderTesting.slow
    def test_reject_bootstrap(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        self.do_test_reject_bootstrap(
            standard_setup_one_client_bootstrapped, valid_image
        )


class TestBootstrappingEnterprise(BaseTestBootstrapping):
    @MenderTesting.fast
    def test_bootstrap(self, enterprise_one_client):
        self.do_test_bootstrap(enterprise_one_client)

    @MenderTesting.slow
    def test_reject_bootstrap(self, enterprise_one_client_bootstrapped, valid_image):
        self.do_test_reject_bootstrap(enterprise_one_client_bootstrapped, valid_image)
