#!/usr/bin/python
# Copyright 2017 Northern.tech AS
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

from fabric.api import *
import pytest

from .. import conftest
from ..common import *
from ..common_setup import standard_setup_one_client, standard_setup_one_client_bootstrapped
from .common_update import common_update_procedure
from ..helpers import Helpers
from ..MenderAPI import auth_v2, logger
from .mendertesting import MenderTesting


class TestBootstrapping(MenderTesting):
    @MenderTesting.fast
    def test_bootstrap(self, standard_setup_one_client):
        """Simply make sure we are able to bootstrap a device"""

        mender_clients = standard_setup_one_client.get_mender_clients()

        execute(self.accept_devices,
                mender_clients,
                hosts=mender_clients)

    def accept_devices(self, mender_clients):
        auth_v2.check_expected_status("pending", len(mender_clients))

        # iterate over devices and accept them
        for d in auth_v2.get_devices():
            auth_v2.set_device_auth_set_status(d["id"], d["auth_sets"][0]["id"], "accepted")
            logger.info("Accepting DeviceID: %s" % d["id"])

        # make sure all devices are accepted
        auth_v2.check_expected_status("accepted", len(mender_clients))

        # make sure mender-store contains authtoken after sometime, else fail test
        HAVE_TOKEN_TIMEOUT = 60 * 5
        sleepsec = 0
        while sleepsec < HAVE_TOKEN_TIMEOUT:
            try:
                run('strings {} | grep authtoken'.format(MENDER_STORE))
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
    def test_reject_bootstrap(self, standard_setup_one_client_bootstrapped):
        """Make sure a rejected device does not perform an upgrade, and that it gets it's auth token removed"""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_reject_bootstrap,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients)
            return

        # iterate over devices and reject them
        for device in auth_v2.get_devices():
            auth_v2.set_device_auth_set_status(device["id"], device["auth_sets"][0]["id"], "rejected")
            logger.info("Rejecting DeviceID: %s" % device["id"])

        auth_v2.check_expected_status("rejected", len(mender_clients))

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot:
            try:
                deployment_id, _ = common_update_procedure(install_image=conftest.get_valid_image())
            except AssertionError:
                logger.info("Failed to deploy upgrade to rejected device.")
                reboot.verify_reboot_not_performed()

            else:
                # use assert to fail, so we can get backend logs
                pytest.fail("no error while trying to deploy to rejected device")
                return

        finished = False
        # wait until auththoken is removed from file
        for _ in range(10):
            with settings(abort_exception=Exception):
                try:
                    run("journalctl -u mender-client -l -n 3 | grep -q 'authentication request rejected'")
                except:
                    time.sleep(30)
                else:
                    finished = True
                    break

        auth_v2.accept_devices(1)

        if not finished:
            pytest.fail("failed to remove authtoken from mender-store file")
