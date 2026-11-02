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

from ..common_setup import (
    standard_setup_one_client,
    enterprise_one_client,
    enterprise_one_client_bootstrapped,
)
from ..MenderAPI import DeviceAuthV2, logger
from ..helpers import Helpers
from .mendertesting import MenderTesting


class BaseTestBootstrapping(MenderTesting):
    def do_test_reject_bootstrap(self, env):
        """Make sure a rejected device gets it's auth token removed"""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)

        reject_time = time.time()

        # iterate over devices and reject them
        for device in devauth.get_devices():
            devauth.set_device_auth_set_status(
                device["id"], device["auth_sets"][0]["id"], "rejected"
            )
            logger.info("Rejecting DeviceID: %s" % device["id"])

        devauth.check_expected_status("rejected", 1)

        # Check from client side
        Helpers.check_log_is_unauthenticated(
            mender_device,
            time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(reject_time)),
        )

        # Restart client to force log reset.
        mender_device.run("systemctl restart mender-updated")

        # Check that we can accept again the device from the server
        devauth.accept_devices(1)

        # Check from client side that it can be authorized
        Helpers.check_log_is_authenticated(mender_device)


class TestBootstrappingEnterprise(BaseTestBootstrapping):
    @MenderTesting.slow
    def test_reject_bootstrap(self, enterprise_one_client_bootstrapped):
        self.do_test_reject_bootstrap(enterprise_one_client_bootstrapped)
