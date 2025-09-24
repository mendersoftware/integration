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

import os
import pytest

from integration_tests.common_setup import (
    standard_setup_one_client_bootstrapped,
    enterprise_one_client_bootstrapped,
)
from integration_tests.tests.common_update import common_update_procedure
from integration_tests.MenderAPI import DeviceAuthV2, Deployments
from integration_tests.tests.mendertesting import MenderTesting


class BaseTestDeploymentAborting(MenderTesting):
    def abort_deployment(
        self, container_manager, install_image, abort_step=None, number_of_reboots=0,
    ):
        """
        Trigger a deployment, and cancel it within 15 seconds, make sure no deployment is performed.

        Args:
            number_of_reboots: if set to 0, a manual reboot is performed and
                                   checks are performed.
                               if set to > 0, wait until device is rebooted
                               number_of_reboots times.
        """

        mender_device = container_manager.device

        devauth = DeviceAuthV2(container_manager.auth)
        deploy = Deployments(container_manager.auth, devauth)

        expected_partition = mender_device.get_active_partition()
        expected_image_id = mender_device.yocto_id_installed_on_machine()
        host_ip = container_manager.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(
                install_image, verify_status=False, devauth=devauth, deploy=deploy,
            )

            if abort_step is not None:
                deploy.check_expected_statistics(
                    deployment_id, abort_step, 1, polling_frequency=0
                )

            deploy.abort(deployment_id)

            # there will be abored deployment only if the deployment
            # for the device has already started
            if abort_step is not None:
                deploy.check_expected_statistics(deployment_id, "aborted", 1)

            # no deployment logs are sent by the client, is this expected?
            for d in devauth.get_devices():
                deploy.get_logs(d["id"], deployment_id, expected_status=404)

            if number_of_reboots > 0:
                # If Mender performs reboot, we need to wait for it to reboot
                # back into the original filesystem.
                reboot.verify_reboot_performed(number_of_reboots=number_of_reboots)
            else:
                # Else we reboot ourselves, just to make sure that we have not
                # unintentionally switched to the new partition.
                reboot.verify_reboot_not_performed()
                mender_device.run("( sleep 10 ; reboot ) 2>/dev/null >/dev/null &")
                reboot.verify_reboot_performed()

        assert mender_device.get_active_partition() == expected_partition
        assert mender_device.yocto_id_installed_on_machine() == expected_image_id
        deploy.check_expected_status("finished", deployment_id)


class TestDeploymentAbortingOpenSource(BaseTestDeploymentAborting):
    @MenderTesting.fast
    def test_deployment_abortion_instantly(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            standard_setup_one_client_bootstrapped, valid_image, number_of_reboots=0
        )

    @MenderTesting.fast
    def test_deployment_abortion_downloading(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            standard_setup_one_client_bootstrapped,
            valid_image,
            "downloading",
            number_of_reboots=0,
        )

    @MenderTesting.fast
    def test_deployment_abortion_installing(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            standard_setup_one_client_bootstrapped,
            valid_image,
            "installing",
            number_of_reboots=1,
        )

    @MenderTesting.fast
    def test_deployment_abortion_rebooting(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            standard_setup_one_client_bootstrapped,
            valid_image,
            "rebooting",
            number_of_reboots=2,
        )


class TestDeploymentAbortingEnterprise(BaseTestDeploymentAborting):
    @MenderTesting.fast
    def test_deployment_abortion_instantly(
        self, enterprise_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            enterprise_one_client_bootstrapped, valid_image, number_of_reboots=0
        )

    @MenderTesting.fast
    def test_deployment_abortion_downloading(
        self, enterprise_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            enterprise_one_client_bootstrapped,
            valid_image,
            "downloading",
            number_of_reboots=0,
        )

    @MenderTesting.fast
    def test_deployment_abortion_installing(
        self, enterprise_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            enterprise_one_client_bootstrapped,
            valid_image,
            "installing",
            number_of_reboots=1,
        )

    @MenderTesting.fast
    def test_deployment_abortion_rebooting(
        self, enterprise_one_client_bootstrapped, valid_image
    ):
        self.abort_deployment(
            enterprise_one_client_bootstrapped,
            valid_image,
            "rebooting",
            number_of_reboots=2,
        )
