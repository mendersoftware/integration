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
from deployments import Deployments
from admission import Admission
from common import *
from helpers import Helpers
from base_update import base_update_proceduce


@pytest.mark.usefixtures("bootstrapped_successfully", "ssh_is_opened")
class TestBasicIntegration(object):
    slow = pytest.mark.skipif(not pytest.config.getoption("--runslow"),
                              reason="need --runslow option to run")

    def test_update_image_successful(self, install_image=conftest.get_valid_image(), name=None, regnerate_image_id=True):
        """
            Perform a successful upgrade, and assert that deployment status/logs are correct.

            A reboot is performed, and running partitions have been swapped.
            Deployment status will be set as successful for device.
            Logs will not be retrieved, and result in 404.
        """
        if not env.host_string:
            execute(self.test_update_image_successful,
                    hosts=conftest.get_mender_clients(),
                    install_image=install_image,
                    name=name,
                    regnerate_image_id=regnerate_image_id)
            return



        previous_inactive_part = Helpers.get_passive_partition()
        deployment_id = base_update_proceduce(install_image, name, regnerate_image_id)
        Helpers.verify_reboot_performed()
        assert Helpers.get_active_partition() == previous_inactive_part
        Deployments.check_expected_status(deployment_id, "success", len(conftest.get_mender_clients()))

        for d in Admission.get_devices():
            Deployments.get_logs(d["id"], deployment_id, expected_status=404)

    def test_update_image_failed(self, install_image="broken_image.dat", name=None):
        """
            Perform a upgrade using a broken image (random data)
            The device will reboot, uboot will detect this is not a bootable image, and revert to the previous partition.
            The resulting upgrade will be considered a failure.
        """
        if not env.host_string:
            execute(self.test_update_image_failed,
                    hosts=conftest.get_mender_clients(),
                    install_image=install_image,
                    name=name)
            return

        devices_accepted = conftest.get_mender_clients()

        previous_active_part = Helpers.get_active_partition()
        deployment_id = base_update_proceduce(install_image, name, broken_image=True)

        Helpers.verify_reboot_performed()
        assert Helpers.get_active_partition() == previous_active_part

        Deployments.check_expected_status(deployment_id, "failure", len(devices_accepted))

        for d in Admission.get_devices():
            assert "running rollback image" in Deployments.get_logs(d["id"], deployment_id)

    @slow
    def test_double_update(self):
        "Upload a device with two consecutive upgrade images"

        if not env.host_string:
            execute(self.test_double_update,
                    hosts=conftest.get_mender_clients())
            return

        self.test_update_image_successful()
        self.test_update_image_successful()
        Helpers.verify_reboot_not_performed()

    @slow
    def test_failed_updated_and_valid_update(self):
        "Upload a device with a broken image, followed by a valid image"

        if not env.host_string:
            execute(self.test_failed_updated_and_valid_update,
                    hosts=conftest.get_mender_clients())
            return

        self.test_update_image_failed()
        self.test_update_image_successful()
        Helpers.verify_reboot_not_performed()

    def test_image_already_installed(self):
        "Attempt to install an upgade that is already installed (matching imageID)"

        if not env.host_string:
            execute(self.test_image_already_installed,
                    hosts=conftest.get_mender_clients())
            return

        self.test_update_image_successful()
        deployment_id = base_update_proceduce(install_image=conftest.get_valid_image(), name="duplicate update", regnerate_image_id=False)
        Deployments.check_expected_status(deployment_id, "success", len(conftest.get_mender_clients()))
        Helpers.verify_reboot_not_performed()
