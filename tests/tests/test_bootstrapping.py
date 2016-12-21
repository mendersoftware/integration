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

from fabric.api import *
import pytest
import time
from common import *
from helpers import Helpers
from MenderAPI import adm, deploy, image, logger
from common_update import common_update_proceduce
from mendertesting import MenderTesting


@MenderTesting.fast
@pytest.mark.usefixtures("ssh_is_opened")
class TestBootstrapping(MenderTesting):
    slow = pytest.mark.skipif(not pytest.config.getoption("--runslow"),
                              reason="need --runslow option to run")

    def test_bootstrap(self):
        """Simply make sure we are able to bootstrap a device"""
        if not env.host_string:
            execute(self.test_bootstrap, hosts=conftest.get_mender_clients())
            return

        adm.check_expected_status("pending", len(conftest.get_mender_clients()))

        # iterate over devices and accept them
        for d in adm.get_devices():
            adm.set_device_status(d["id"], "accepted")
            logging.info("Accepting DeviceID: %s" % d["id"])

        # make sure all devices are accepted
        adm.check_expected_status("accepted", len(conftest.get_mender_clients()))

        # print all device ids
        for device in adm.get_devices_status("accepted"):
            logging.info("Accepted DeviceID: %s" % device["id"])

    @MenderTesting.slow
    @pytest.mark.usefixtures("bootstrapped_successfully")
    def test_reject_bootstrap(self):
        """Make sure a rejected device does not perform an upgrade, and that it gets it's auth token removed"""
        if not env.host_string:
            execute(self.test_reject_bootstrap, hosts=conftest.get_mender_clients())
            return

        # iterate over devices and reject them
        for device in adm.get_devices():
            adm.set_device_status(device["id"], "rejected")
            logging.info("Rejecting DeviceID: %s" % device["id"])

        adm.check_expected_status("rejected", len(conftest.get_mender_clients()))

        try:
            deployment_id, _ = common_update_proceduce(install_image=conftest.get_valid_image(), name=None)
        except AssertionError:
            logging.info("Failed to deploy upgrade to rejected device.")
            Helpers.verify_reboot_not_performed()

            # authtoken has been removed
            assert not exists("/data/mender/authtoken")

        else:
            raise("No error while trying to deploy to rejected device")
