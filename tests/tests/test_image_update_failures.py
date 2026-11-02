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

from ..common_setup import (
    enterprise_one_client_bootstrapped,
)
from .common_update import common_update_procedure
from .mendertesting import MenderTesting
from flaky import flaky
from ..MenderAPI import DeviceAuthV2, Deployments


class BaseTestFailures(MenderTesting):
    @MenderTesting.fast
    def do_test_large_update_image(self, env, large_image):
        """Installing an image larger than the passive/active partition size should result in a failure."""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(
                install_image=large_image,
                # We use verify_status=False because the device is very quick in reporting
                # failure and the test framework might miss the 'inprogress' status transition.
                verify_status=False,
                devauth=devauth,
                deploy=deploy,
            )
            deploy.check_expected_statistics(deployment_id, "failure", 1)
            reboot.verify_reboot_not_performed(wait=10)
            deploy.check_expected_status("finished", deployment_id)


# Retry the intermittent "Device never rebooted" infra flake: the QEMU VM
# sometimes does not come back after a reboot. A flaky rerun sets up a fresh VM.
@flaky(max_runs=3)
class TestFailuresOpenEnterprise(BaseTestFailures):
    @MenderTesting.fast
    def test_large_update_image(self, enterprise_one_client_bootstrapped, large_image):
        self.do_test_large_update_image(enterprise_one_client_bootstrapped, large_image)
