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

from ..common_setup import (
    standard_setup_two_clients_bootstrapped,
    enterprise_two_clients_bootstrapped,
)
from .common_update import common_update_procedure
from ..MenderAPI import DeviceAuthV2, Deployments, Inventory, logger
from .mendertesting import MenderTesting
from ..helpers import Helpers


class BaseTestGrouping(MenderTesting):
    def do_test_update_device_group(self, env, valid_image_with_mender_conf):
        """
        Perform a successful upgrade on one group of devices, and assert that:
        * deployment status/logs are correct.
        * only the correct group is updated, not the other one.

        A reboot is performed, and running partitions have been swapped.
        Deployment status will be set as successful for device.
        Logs will not be retrieved, and result in 404.
        """
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        inv = Inventory(env.auth)

        # Beware that there will two parallel things going on below, one for
        # each group. We aim to update the group alpha, not beta.

        mender_device_group = env.device_group
        assert len(mender_device_group) == 2
        alpha = mender_device_group[0]
        bravo = mender_device_group[1]

        ip_to_device_id = Helpers.ip_to_device_id_map(
            mender_device_group, devauth=devauth
        )
        id_alpha = ip_to_device_id[alpha.host_string]
        id_bravo = ip_to_device_id[bravo.host_string]
        logger.info("ID of alpha host: %s" % id_alpha)
        logger.info("ID of bravo host: %s" % id_bravo)

        # TODO: parallelize these using fabric.group.ThreadingGroup once we upgrade to Python 3
        pass_part_alpha = alpha.get_passive_partition()
        pass_part_bravo = bravo.get_passive_partition()

        inv.put_device_in_group(id_alpha, "Update")

        reboot = {alpha: None, bravo: None}
        host_ip = env.get_virtual_network_host_ip()
        with alpha.get_reboot_detector(host_ip) as reboot[
            alpha
        ], bravo.get_reboot_detector(host_ip) as reboot[bravo]:

            mender_conf = alpha.run("cat /etc/mender/mender.conf")
            deployment_id, expected_image_id = common_update_procedure(
                valid_image_with_mender_conf(mender_conf),
                devices=[id_alpha],
                devauth=devauth,
                deploy=deploy,
            )

            # Extra long wait here, because a real update takes quite a lot of time.
            reboot[bravo].verify_reboot_not_performed(300)
            reboot[alpha].verify_reboot_performed()

        assert alpha.get_passive_partition() != pass_part_alpha
        assert bravo.get_passive_partition() == pass_part_bravo

        assert alpha.get_active_partition() == pass_part_alpha
        assert bravo.get_active_partition() != pass_part_bravo

        deploy.check_expected_statistics(
            deployment_id, expected_status="success", expected_count=1
        )

        # No logs for either host: alpha because it was successful, bravo
        # because it should never have attempted an update in the first place.
        for id in [id_alpha, id_bravo]:
            deploy.get_logs(id, deployment_id, expected_status=404)

        assert alpha.yocto_id_installed_on_machine() == expected_image_id
        assert bravo.yocto_id_installed_on_machine() != expected_image_id

        # Important: Leave the groups as you found them: Empty.
        inv.delete_device_from_group(id_alpha, "Update")


@MenderTesting.fast
class TestGroupingOpenSource(BaseTestGrouping):
    def test_update_device_group(
        self, standard_setup_two_clients_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_update_device_group(
            standard_setup_two_clients_bootstrapped,
            valid_image_with_mender_conf,
        )


@MenderTesting.fast
class TestGroupingEnterprise(BaseTestGrouping):
    def test_update_device_group(
        self, enterprise_two_clients_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_update_device_group(
            enterprise_two_clients_bootstrapped,
            valid_image_with_mender_conf,
        )
