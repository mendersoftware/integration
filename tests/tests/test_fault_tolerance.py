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
class TestFaultTolerance(MenderTesting):

    @MenderTesting.slow
    @pytest.mark.usefixtures("bootstrapped_successfully")
    def test_update_image_breaks_networking(self, install_image="core-image-full-cmdline-vexpress-qemu-broken-network.ext4"):
        """
            Install an image without systemd-networkd binary existing.
            The network will not function, mender will not be able to send any logs.

            The expected status is the update will rollback, and be considered a failure
        """
        if not env.host_string:
            execute(self.test_update_image_breaks_networking,
                    hosts=conftest.get_mender_clients(),
                    install_image=install_image)
            return

        deployment_id, _ = common_update_proceduce(install_image, name=None)
        Helpers.verify_reboot_performed() # since the network is broken, two reboots will be performed, and the last one will be detected
        deploy.check_expected_status(deployment_id, "failure", len(conftest.get_mender_clients()))

    @MenderTesting.fast
    @pytest.mark.usefixtures("bootstrapped_successfully")
    def test_update_image_recovery(self, install_image=conftest.get_valid_image()):
        """
            Install an update, and reboot the system when we detect it's being copied over to the inactive parition.

            The test should result in a failure.
        """
        if not env.host_string:
            execute(self.test_update_image_recovery,
                    hosts=conftest.get_mender_clients(),
                    install_image=install_image)
            return

        installed_yocto_id = Helpers.yocto_id_installed_on_machine()

        inactive_part = Helpers.get_passive_partition()
        deployment_id, _ = common_update_proceduce(install_image, name=None)
        active_part = Helpers.get_active_partition()

        for i in range(60):
            time.sleep(0.5)
            with quiet():
                # make sure we are writing to the inactive partition
                output = run("fuser -mv %s" % (inactive_part))
            if output.return_code == 0:
                run("killall -s 9 mender")
                with settings(warn_only=True):
                    run("( sleep 3 ; reboot ) 2>/dev/null >/dev/null &")
                break

        logging.info("Waiting for system to finish reboot")
        Helpers.verify_reboot_performed()
        assert Helpers.get_active_partition() == active_part
        deploy.check_expected_status(deployment_id, "failure", len(conftest.get_mender_clients()))
        Helpers.verify_reboot_not_performed()

        assert Helpers.yocto_id_installed_on_machine() == installed_yocto_id

    @MenderTesting.slow
    @pytest.mark.usefixtures("bootstrapped_successfully")
    def test_deployed_during_network_outage(self, install_image=conftest.get_valid_image()):
        """
            Install a valid upgrade image while there is no network availability on the device
            Re-establishing the network connectivity results in the upgrade to be triggered.

            Emulate a flaky network connection, and ensure that the deployment still succeeds.
        """
        if not env.host_string:
            execute(self.test_deployed_during_network_outage,
                    hosts=conftest.get_mender_clients(),
                    install_image=install_image)
            return

        Helpers.gateway_connectivity(False)
        deployment_id, expected_yocto_id = common_update_proceduce(install_image, name=None)
        time.sleep(60)

        for i in range(5):
            time.sleep(5)
            Helpers.gateway_connectivity(i % 2 == 0)
        Helpers.gateway_connectivity(True)

        logging.info("Network stabilized")
        Helpers.verify_reboot_performed()
        deploy.check_expected_status(deployment_id, "success", len(conftest.get_mender_clients()))

        assert Helpers.yocto_id_installed_on_machine() == expected_yocto_id
