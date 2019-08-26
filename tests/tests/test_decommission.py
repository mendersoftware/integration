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
import time
import pytest
from ..common_setup import *
from ..helpers import Helpers
from .common_update import common_update_procedure
from ..MenderAPI import inv, auth_v2
from .mendertesting import MenderTesting
from conductor import Conductor


class TestDeviceDecommissioning(MenderTesting):
    def check_gone_from_inventory(self, device_id):
        r = inv.get_device(device_id)
        assert r.status_code == 404, "device [%s] not removed from inventory" % (device_id,)

    def check_gone_from_deviceauth(self, device_id):
        r = auth_v2.get_device(device_id)
        assert r.status_code == 404, "device [%s] not removed from deviceauth" % (device_id,)

    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_one_client")
    def test_device_decommissioning(self):
        """ Decommission a device successfully """

        if not env.host_string:
            execute(self.test_device_decommissioning, hosts=get_mender_clients())
            return

        auth_v2.check_expected_status("pending", len(get_mender_clients()))
        device = auth_v2.get_devices()[0]
        device_id = device["id"]

        auth_v2.set_device_auth_set_status(device_id, device["auth_sets"][0]["id"], "accepted")

        # wait until inventory is populated
        timeout = time.time() + (60 * 5)

        while time.time() < timeout:
            inventoryJSON = inv.get_devices()

            # we haven't gotten an inventory data yet.
            if len(inventoryJSON) == 0:
                continue

            if "attributes" in inventoryJSON[0]:
                break
            time.sleep(.5)
        else:
            assert False, "never got inventory"

        # get all completed decommission_device WFs for reference
        c = Conductor(get_mender_conductor())
        initial_wfs = c.get_decommission_device_wfs(device_id)

        # decommission actual device
        auth_v2.decommission(device_id)

        # check that the workflow completed successfully
        timeout = time.time() + (60 * 5)
        while time.time() < timeout:
            wfs = c.get_decommission_device_wfs(device_id)
            if wfs['totalHits'] == initial_wfs['totalHits'] + 1:
                break
            else:
                logger.info("waiting for decommission_device workflow...")
                time.sleep(.5)
        else:
            assert False, "decommission_device workflow didn't complete for [%s]" % (device_id,)

        # check device gone from inventory
        self.check_gone_from_inventory(device_id)

        # check device gone from deviceauth
        self.check_gone_from_deviceauth(device_id)
