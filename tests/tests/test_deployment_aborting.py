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
from common import *
from common_setup import *
from helpers import Helpers
from common_update import common_update_proceduce
from MenderAPI import adm, deploy, image
from mendertesting import MenderTesting

@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestDeploymentAborting(MenderTesting):

    def abort_deployment(self, abort_step, mender_performs_reboot=False):
        """
            Trigger a deployment, and cancel it within 15 seconds, make sure no deployment is performed.

            Args:
                mender_performs_reboot: if set to False, a manual reboot is performed and
                                            checks are performed.
                                        if set to True, wait until device is rebooted.
        """
        if not env.host_string:
            execute(self.abort_deployment,
                    abort_step=abort_step,
                    mender_performs_reboot=mender_performs_reboot,
                    hosts=get_mender_clients())
            return

        install_image=conftest.get_valid_image()
        expected_partition = Helpers.get_active_partition()
        expected_image_id = Helpers.yocto_id_installed_on_machine()
        deployment_id, _ = common_update_proceduce(install_image)

        deploy.check_expected_status(deployment_id, abort_step, len(get_mender_clients()))
        deploy.abort(deployment_id)
        deploy.check_expected_status(deployment_id, "aborted", len(get_mender_clients()))

        # no deployment logs are sent by the client, is this expected?
        for d in adm.get_devices():
            deploy.get_logs(d["id"], deployment_id, expected_status=404)

        if not mender_performs_reboot:
            Helpers.verify_reboot_not_performed()
            run("( sleep 3 ; reboot ) 2>/dev/null >/dev/null &")

        Helpers.verify_reboot_performed()

        assert Helpers.get_active_partition() == expected_partition
        assert Helpers.yocto_id_installed_on_machine() == expected_image_id

    @MenderTesting.fast
    def test_deployment_abortion_pending(self):
        self.abort_deployment("pending")

    @MenderTesting.fast
    def test_deployment_abortion_installing(self):
        self.abort_deployment("installing")

    @pytest.mark.skip(reason="MEN-961")
    @MenderTesting.fast
    def test_deployment_abortion_rebooting(self):
        self.abort_deployment("rebooting", mender_performs_reboot=True)

    @MenderTesting.slow
    def test_deployment_abortion_success(self):
        # maybe an acceptance test is enough for this check?

        if not env.host_string:
            execute(self.test_deployment_abortion_success,
                    hosts=get_mender_clients())
            return

        install_image = conftest.get_valid_image()
        deployment_id, _ = common_update_proceduce(install_image)

        Helpers.verify_reboot_performed()

        deploy.check_expected_status(deployment_id, "success", len(get_mender_clients()))
        deploy.abort(deployment_id)
        deploy.check_expected_status(deployment_id, "success", len(get_mender_clients()))
