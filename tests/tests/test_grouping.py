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
from common_update import common_update_procedure
from MenderAPI import deploy, inv
from mendertesting import MenderTesting

@MenderTesting.fast
@pytest.mark.usefixtures("standard_setup_two_clients_bootstrapped")
class TestGrouping(MenderTesting):
    def validate_group_responses(self, device_map):
        """Checks whether the device_map corresponds to the server's view of
        the current groups, using all the possible ways to query for this.
        device_map is a map of device to group."""

        groups = []
        groups_map = {}
        devices_with_group = []
        devices_without_group = []
        for device in device_map:
            group = device_map[device]
            if group is not None:
                groups.append(group)
                devices_with_group.append(device)
            else:
                devices_without_group.append(device)

            if groups_map.get(group):
                groups_map[group].append(device)
            else:
                groups_map[group] = [device]

        assert(sorted(inv.get_groups()) == sorted(groups))
        assert(sorted([device['id'] for device in inv.get_devices(has_group=True)]) == sorted(devices_with_group))
        assert(sorted([device['id'] for device in inv.get_devices(has_group=False)]) == sorted(devices_without_group))
        assert(sorted([device['id'] for device in inv.get_devices()]) == sorted(device_map.keys()))

        for group in groups:
            assert(sorted(inv.get_devices_in_group(group)) == sorted(groups_map[group]))
        for device in device_map:
            assert(inv.get_device_group(device)['group'] == device_map[device])

    def test_basic_groups(self):
        """Tests various group operations."""

        devices = [device['id'] for device in inv.get_devices()]
        assert(len(devices) == 2)

        # Purely for easier reading: Assign labels to each device.
        alpha = devices[0]
        bravo = devices[1]

        # Start out with no groups.
        self.validate_group_responses({alpha: None, bravo: None})

        # Test various group operations.
        inv.put_device_in_group(alpha, "Red")
        self.validate_group_responses({alpha: "Red", bravo: None})

        inv.put_device_in_group(bravo, "Blue")
        self.validate_group_responses({alpha: "Red", bravo: "Blue"})

        inv.delete_device_from_group(alpha, "Red")
        self.validate_group_responses({alpha: None, bravo: "Blue"})

        # Note that this *moves* the device into the group.
        inv.put_device_in_group(bravo, "Red")
        self.validate_group_responses({alpha: None, bravo: "Red"})

        # Important: Leave the groups as you found them: Empty.
        inv.delete_device_from_group(bravo, "Red")
        self.validate_group_responses({alpha: None, bravo: None})


    def test_update_device_group(self):
        """
            Perform a successful upgrade on one group of devices, and assert that:
            * deployment status/logs are correct.
            * only the correct group is updated, not the other one.

            A reboot is performed, and running partitions have been swapped.
            Deployment status will be set as successful for device.
            Logs will not be retrieved, and result in 404.
        """

        # Beware that there will two parallel things going on below, one for
        # each group, hence a lot of separate execute() calls for each. We aim
        # to update the group alpha, not beta.

        clients = get_mender_clients()
        assert(len(clients) == 2)
        alpha = clients[0]
        bravo = clients[1]

        ip_to_device_id = Helpers.ip_to_device_id_map(clients)
        id_alpha = ip_to_device_id[alpha]
        id_bravo = ip_to_device_id[bravo]
        print("ID of alpha host: %s\nID of bravo host: %s" % (id_alpha, id_bravo))

        ret = execute(Helpers.get_passive_partition, hosts=clients)
        pass_part_alpha = ret[alpha]
        pass_part_bravo = ret[bravo]

        inv.put_device_in_group(id_alpha, "Update")

        reboot = { alpha: None, bravo: None }
        with Helpers.RebootDetector(alpha) as reboot[alpha], Helpers.RebootDetector(bravo) as reboot[bravo]:

            deployment_id, expected_image_id = common_update_procedure(conftest.get_valid_image(),
                                                                       devices=[id_alpha])

            @parallel
            def verify_reboot_performed_for_alpha_only():
                if env.host_string == alpha:
                    reboot[alpha].verify_reboot_performed()
                elif env.host_string == bravo:
                    # Extra long wait here, because a real update takes quite a lot
                    # of time.
                    reboot[bravo].verify_reboot_not_performed(300)
                else:
                    raise Exception("verify_reboot_performed_for_alpha_only() called with unknown host")

            execute(verify_reboot_performed_for_alpha_only, hosts=clients)

        ret = execute(Helpers.get_passive_partition, hosts=clients)
        assert ret[alpha] != pass_part_alpha
        assert ret[bravo] == pass_part_bravo
        ret = execute(Helpers.get_active_partition, hosts=clients)
        assert ret[alpha] == pass_part_alpha
        assert ret[bravo] != pass_part_bravo

        deploy.check_expected_statistics(deployment_id, expected_status="success", expected_count=1)

        # No logs for either host: alpha because it was successful, bravo
        # because it should never have attempted an update in the first place.
        for id in [id_alpha, id_bravo]:
            deploy.get_logs(id, deployment_id, expected_status=404)

        assert execute(Helpers.yocto_id_installed_on_machine, hosts=alpha)[alpha] == expected_image_id
        assert execute(Helpers.yocto_id_installed_on_machine, hosts=bravo)[bravo] != expected_image_id

        # Important: Leave the groups as you found them: Empty.
        inv.delete_device_from_group(id_alpha, "Update")
