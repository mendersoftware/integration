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
from ..common_setup import standard_setup_one_client_bootstrapped
from .common_update import common_update_procedure
from ..MenderAPI import auth_v2, deploy
from .mendertesting import MenderTesting


class TestDeploymentAborting(MenderTesting):
    @staticmethod
    def abort_deployment(
        container_manager, install_image, abort_step=None, mender_performs_reboot=False,
    ):
        """
            Trigger a deployment, and cancel it within 15 seconds, make sure no deployment is performed.

            Args:
                mender_performs_reboot: if set to False, a manual reboot is performed and
                                            checks are performed.
                                        if set to True, wait until device is rebooted.
        """

        mender_device = container_manager.device

        expected_partition = mender_device.get_active_partition()
        expected_image_id = mender_device.yocto_id_installed_on_machine()
        host_ip = container_manager.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(
                install_image, verify_status=False
            )

            if abort_step is not None:
                deploy.check_expected_statistics(deployment_id, abort_step, 1)

            deploy.abort(deployment_id)

            # there will be abored deployment only if the deployment
            # for the device has already started
            if abort_step is not None:
                deploy.check_expected_statistics(deployment_id, "aborted", 1)

            # no deployment logs are sent by the client, is this expected?
            for d in auth_v2.get_devices():
                deploy.get_logs(d["id"], deployment_id, expected_status=404)

            if mender_performs_reboot:
                # If Mender performs reboot, we need to wait for it to reboot
                # back into the original filesystem.
                reboot.verify_reboot_performed(number_of_reboots=2)
            else:
                # Else we reboot ourselves, just to make sure that we have not
                # unintentionally switched to the new partition.
                reboot.verify_reboot_not_performed()
                mender_device.run("( sleep 10 ; reboot ) 2>/dev/null >/dev/null &")
                reboot.verify_reboot_performed()

        assert mender_device.get_active_partition() == expected_partition
        assert mender_device.yocto_id_installed_on_machine() == expected_image_id
        deploy.check_expected_status("finished", deployment_id)

    @MenderTesting.fast
    def test_deployment_abortion_instantly(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        TestDeploymentAborting.abort_deployment(
            standard_setup_one_client_bootstrapped, valid_image
        )

    @MenderTesting.fast
    def test_deployment_abortion_downloading(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        TestDeploymentAborting.abort_deployment(
            standard_setup_one_client_bootstrapped, valid_image, "downloading"
        )

    @MenderTesting.fast
    def test_deployment_abortion_rebooting(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        TestDeploymentAborting.abort_deployment(
            standard_setup_one_client_bootstrapped,
            valid_image,
            "rebooting",
            mender_performs_reboot=True,
        )
