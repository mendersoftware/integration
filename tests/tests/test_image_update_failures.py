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

@pytest.mark.usefixtures("ssh_is_opened", "bootstrapped_successfully")
class TestFailures(MenderTesting):

    @MenderTesting.slow
    def test_update_image_id_already_installed(self, install_image=conftest.get_valid_image(), name="duplicate_id"):
        """Uploading an image with an incorrect yocto_id set results in failure and rollback."""

        if not env.host_string:
            execute(self.test_update_image_id_already_installed,
                    hosts=conftest.get_mender_clients(),
                    install_image=install_image)
            return

        previous_inactive_part = Helpers.get_passive_partition()

        deployment_id, expected_image_id = common_update_proceduce(install_image, name, True)
        Helpers.verify_reboot_performed()

        devices_accepted_id = [device["id"] for device in adm.get_devices_status("accepted")]
        deployment_id = deploy.trigger_deployment(name="New valid update",
                                                       artifact_name=name,
                                                       devices=devices_accepted_id)

        deploy.check_expected_status(deployment_id, "already-installed", len(conftest.get_mender_clients()))

    @MenderTesting.fast
    def test_large_update_image(self):
        """Installing an image larger than the passive/active parition size should result in a failure."""
        if not env.host_string:
            execute(self.test_large_update_image, hosts=conftest.get_mender_clients())
            return

        deployment_id, _ = common_update_proceduce(install_image="large_image.dat", name=None, regnerate_image_id=False, broken_image=True)
        deploy.check_expected_status(deployment_id, "failure", len(conftest.get_mender_clients()))
        Helpers.verify_reboot_not_performed()
