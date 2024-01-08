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
    standard_setup_one_client_bootstrapped,
    enterprise_one_client_bootstrapped,
)
from .common_update import common_update_procedure
from .mendertesting import MenderTesting
from ..MenderAPI import DeviceAuthV2, Deployments


class BaseTestFailures(MenderTesting):
    @MenderTesting.slow
    def do_test_update_image_id_already_installed(
        self, env, valid_image_with_mender_conf,
    ):
        """Test that an image with the same ID as the already installed image does not install anew"""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            mender_conf = mender_device.run("cat /etc/mender/mender.conf")
            deployment_id, expected_image_id = common_update_procedure(
                valid_image_with_mender_conf(mender_conf),
                verify_status=True,
                devauth=devauth,
                deploy=deploy,
            )
            reboot.verify_reboot_performed()

        devices_accepted_id = [
            device["id"] for device in devauth.get_devices_status("accepted")
        ]
        deployment_id = deploy.trigger_deployment(
            name="New valid update",
            artifact_name=expected_image_id,
            devices=devices_accepted_id,
        )

        deploy.check_expected_statistics(deployment_id, "already-installed", 1)
        deploy.check_expected_status("finished", deployment_id)

    @MenderTesting.fast
    def do_test_large_update_image(self, env):
        """Installing an image larger than the passive/active partition size should result in a failure."""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(
                install_image="large_image.dat",
                # We use verify_status=False because the device is very quick in reporting
                # failure and the test framework might miss the 'inprogress' status transition.
                verify_status=False,
                devauth=devauth,
                deploy=deploy,
            )
            deploy.check_expected_statistics(deployment_id, "failure", 1)
            reboot.verify_reboot_not_performed()
            deploy.check_expected_status("finished", deployment_id)


class TestFailuresOpenSource(BaseTestFailures):
    @MenderTesting.slow
    def test_update_image_id_already_installed(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_update_image_id_already_installed(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
        )

    @MenderTesting.fast
    def test_large_update_image(self, standard_setup_one_client_bootstrapped):
        self.do_test_large_update_image(standard_setup_one_client_bootstrapped)


class TestFailuresOpenEnterprise(BaseTestFailures):
    @MenderTesting.slow
    def test_update_image_id_already_installed(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_update_image_id_already_installed(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )

    @MenderTesting.fast
    def test_large_update_image(self, enterprise_one_client_bootstrapped):
        self.do_test_large_update_image(enterprise_one_client_bootstrapped)
