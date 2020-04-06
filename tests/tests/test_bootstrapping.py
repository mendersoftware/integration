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

import time

import pytest

from .. import conftest
from ..common_setup import (
    standard_setup_one_client,
    standard_setup_one_client_bootstrapped,
)
from .common_update import common_update_procedure
from ..MenderAPI import auth_v2, logger
from .mendertesting import MenderTesting


class TestBootstrapping(MenderTesting):
    MENDER_STORE = "/data/mender/mender-store"

    @MenderTesting.fast
    def test_bootstrap(self, standard_setup_one_client):
        """Simply make sure we are able to bootstrap a device"""

        mender_device = standard_setup_one_client.device

        auth_v2.check_expected_status("pending", 1)

        # iterate over devices and accept them
        for d in auth_v2.get_devices():
            auth_v2.set_device_auth_set_status(
                d["id"], d["auth_sets"][0]["id"], "accepted"
            )
            logger.info("Accepting DeviceID: %s" % d["id"])

        # make sure all devices are accepted
        auth_v2.check_expected_status("accepted", 1)

        # make sure mender-store contains authtoken after sometime, else fail test
        HAVE_TOKEN_TIMEOUT = 60 * 5
        sleepsec = 0
        while sleepsec < HAVE_TOKEN_TIMEOUT:
            try:
                mender_device.run(
                    "strings {} | grep authtoken".format(self.MENDER_STORE)
                )
                return
            except Exception:
                sleepsec += 5
                time.sleep(5)
                logger.info("waiting for mender-store file, sleepsec: %d" % sleepsec)

        assert sleepsec <= HAVE_TOKEN_TIMEOUT, "timeout for mender-store file exceeded"

        # print all device ids
        for device in auth_v2.get_devices_status("accepted"):
            logger.info("Accepted DeviceID: %s" % device["id"])

    @MenderTesting.slow
    def test_reject_bootstrap(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        """Make sure a rejected device does not perform an upgrade, and that it gets it's auth token removed"""

        mender_device = standard_setup_one_client_bootstrapped.device

        # iterate over devices and reject them
        for device in auth_v2.get_devices():
            auth_v2.set_device_auth_set_status(
                device["id"], device["auth_sets"][0]["id"], "rejected"
            )
            logger.info("Rejecting DeviceID: %s" % device["id"])

        auth_v2.check_expected_status("rejected", 1)

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            try:
                common_update_procedure(install_image=valid_image)
            except AssertionError:
                logger.info("Failed to deploy upgrade to rejected device.")
                reboot.verify_reboot_not_performed()

            else:
                # use assert to fail, so we can get backend logs
                pytest.fail("no error while trying to deploy to rejected device")
                return

        # Check from client side
        mender_device.run(
            "journalctl -u %s -l -n 3 | grep -q 'authentication request rejected'"
            % mender_device.get_client_service_name()
        )

        # Check that we can accept again the device from the server
        auth_v2.accept_devices(1)
