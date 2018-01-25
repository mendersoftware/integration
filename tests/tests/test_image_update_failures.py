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

from fabric.api import *
import pytest
import time
from common import *
from common_setup import *
from helpers import Helpers
from MenderAPI import adm, deploy, image, logger
from common_update import common_update_procedure
from mendertesting import MenderTesting

@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestFailures(MenderTesting):

    @MenderTesting.slow
    def test_update_image_id_already_installed(self, install_image=conftest.get_valid_image()):
        """Uploading an image with an incorrect name set results in failure and rollback."""

        if not env.host_string:
            execute(self.test_update_image_id_already_installed,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        with Helpers.RebootDetector() as reboot:
            deployment_id, expected_image_id = common_update_procedure(install_image, True)
            reboot.verify_reboot_performed()

        devices_accepted_id = [device["device_id"] for device in adm.get_devices_status("accepted")]
        deployment_id = deploy.trigger_deployment(name="New valid update",
                                                       artifact_name=expected_image_id,
                                                       devices=devices_accepted_id)

        deploy.check_expected_statistics(deployment_id, "already-installed", len(get_mender_clients()))
        deploy.check_expected_status("finished", deployment_id)

    @MenderTesting.fast
    def test_large_update_image(self):
        """Installing an image larger than the passive/active parition size should result in a failure."""
        if not env.host_string:
            execute(self.test_large_update_image, hosts=get_mender_clients())
            return

        with Helpers.RebootDetector() as reboot:
            deployment_id, _ = common_update_procedure(install_image="large_image.dat", regenerate_image_id=False, broken_image=True)
            deploy.check_expected_statistics(deployment_id, "failure", len(get_mender_clients()))
            reboot.verify_reboot_not_performed()
            deploy.check_expected_status("finished", deployment_id)
