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


@pytest.mark.usefixtures("ssh_is_opened")
class TestFailures(object):
    slow = pytest.mark.skipif(not pytest.config.getoption("--runslow"),
                              reason="need --runslow option to run")

    @pytest.mark.skip("MEN-632 - no rollback is performed")
    @pytest.mark.usefixtures("bootstrapped_successfully")
    def test_update_image_id_incorrect(self, install_image=conftest.get_valid_image(), name="incorrect_id"):
        "Uploading an image with an incorrect yocto_id set results in failure and rollback."

        if not env.host_string:
            execute(self.test_update_image_id_incorrect,
                    hosts=conftest.get_mender_clients(),
                    install_image=install_image,
                    name=name)
            return

        upload_request_url = Deployments.post_image_meta(name=name,
                                                         checksum="ccab1cd123",
                                                         device_type="TestDevice",
                                                         yocto_id="invalid")

        Deployments.upload_image(upload_request_url, install_image)
        devices_accepted_id = [d["id"] for d in Admission.get_devices_status("accepted")]

        inital_partition = Helpers.get_active_partition()
        previous_inactive_part = Helpers.get_passive_partition()

        deployment_id = Deployments.trigger_deployment(name="New invalid update - non matching yocotoid",
                                                       artifact_name=name,
                                                       devices=devices_accepted_id)

        Helpers.verify_reboot_performed()
        assert Helpers.get_active_partition() == previous_inactive_part

        Helpers.verify_reboot_performed()
        assert Helpers.get_active_partition() == inital_partition

        Deployments.checked_expected_status(deployment_id, "failure", len(devices_accepted))

        for d in Admission.get_devices():
            Deployments.get_logs(d["id"], deployment_id, expected_status=200)

    @pytest.mark.usefixtures("bootstrapped_successfully")
    def test_large_update_image(self):
        "Installing an image larger than the passive/active parition size should result in a failure."
        if not env.host_string:
            execute(self.test_large_update_image,
                    hosts=conftest.get_mender_clients())
            return

        deployment_id = base_update_proceduce(install_image="large_image.dat", name=None, regnerate_image_id=False)
        Deployments.checked_expected_status(deployment_id, "failure", len(conftest.get_mender_clients()))
        Helpers.verify_reboot_not_performed()
