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
from common import *
from common_setup import *
from helpers import Helpers
from common_update import common_update_procedure
from MenderAPI import adm, deploy, image
from mendertesting import MenderTesting

@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestDeploymentAborting(MenderTesting):

    def abort_deployment(self, abort_step=None, mender_performs_reboot=False):
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
        token = Helpers.place_reboot_token()
        deployment_id, _ = common_update_procedure(install_image, verify_status=False)

        if abort_step is not None:
            deploy.check_expected_statistics(deployment_id, abort_step, len(get_mender_clients()))
        deploy.abort(deployment_id)
        deploy.check_expected_statistics(deployment_id, "aborted", len(get_mender_clients()))

        # no deployment logs are sent by the client, is this expected?
        for d in adm.get_devices():
            deploy.get_logs(d["device_id"], deployment_id, expected_status=404)

        if not mender_performs_reboot:
            token.verify_reboot_not_performed()
            run("( sleep 10 ; reboot ) 2>/dev/null >/dev/null &")

        token.verify_reboot_performed()

        starttime = time.time()
        while True:
            try:
                assert Helpers.get_active_partition() == expected_partition
                assert Helpers.yocto_id_installed_on_machine() == expected_image_id
                break
            except AssertionError:
                # Check the above multiple times if failed. Because aborting
                # during a reboot will in fact reboot, it may be that the agent
                # is temporarily on the wrong partition. But it should recover.
                if time.time() - starttime > 300:
                    raise
                time.sleep(10)
                run_after_connect("true")
        deploy.check_expected_status("finished", deployment_id)

    @MenderTesting.fast
    def test_deployment_abortion_instantly(self):
        self.abort_deployment()

    # Because the install step is over almost instantly, this test is very
    # fragile, it breaks at the slightest timing issue: MEN-1364
    @pytest.mark.skip
    @MenderTesting.fast
    def test_deployment_abortion_downloading(self):
        self.abort_deployment("downloading")

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
        token = Helpers.place_reboot_token()
        deployment_id, _ = common_update_procedure(install_image)

        token.verify_reboot_performed()

        deploy.check_expected_statistics(deployment_id, "success", len(get_mender_clients()))
        deploy.abort_finished_deployment(deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", len(get_mender_clients()))
        deploy.check_expected_status("finished", deployment_id)
