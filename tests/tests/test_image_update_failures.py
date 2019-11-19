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

from .. import conftest
from ..common import *
from ..common_setup import standard_setup_one_client_bootstrapped
from .common_update import common_update_procedure
from ..helpers import Helpers
from ..MenderAPI import auth_v2, deploy
from .mendertesting import MenderTesting

@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestFailures(MenderTesting):

    @MenderTesting.slow
    def test_update_image_id_already_installed(self, standard_setup_one_client_bootstrapped, install_image=conftest.get_valid_image()):
        """Uploading an image with an incorrect name set results in failure and rollback."""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_update_image_id_already_installed,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients,
                    install_image=install_image)
            return

        host_ip = standard_setup_one_client_bootstrapped.docker_get_docker_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot:
            deployment_id, expected_image_id = common_update_procedure(install_image, True)
            reboot.verify_reboot_performed()

        devices_accepted_id = [device["id"] for device in auth_v2.get_devices_status("accepted")]
        deployment_id = deploy.trigger_deployment(name="New valid update",
                                                       artifact_name=expected_image_id,
                                                       devices=devices_accepted_id)

        deploy.check_expected_statistics(deployment_id, "already-installed", len(mender_clients))
        deploy.check_expected_status("finished", deployment_id)

    @MenderTesting.fast
    def test_large_update_image(self, standard_setup_one_client_bootstrapped):
        """Installing an image larger than the passive/active parition size should result in a failure."""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_large_update_image,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients)
            return

        host_ip = standard_setup_one_client_bootstrapped.docker_get_docker_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(install_image="large_image.dat")
            deploy.check_expected_statistics(deployment_id, "failure", len(mender_clients))
            reboot.verify_reboot_not_performed()
            deploy.check_expected_status("finished", deployment_id)
