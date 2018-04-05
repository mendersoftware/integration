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
import common
from common_setup import *
import common_docker
from helpers import Helpers
from common_update import common_update_procedure
from MenderAPI import inv, adm, deviceauth
from mendertesting import MenderTesting
from conductor import Conductor


class TestDeviceDecommissioning(MenderTesting):
    def setup_method(self, method):
        if common.setup_type() == common.ST_OneClient:
            stop_docker_compose()

    def check_gone_from_inventory(self, device_id):
        r = inv.get_device(device_id)
        assert r.status_code == 404, "device [%s] not removed from inventory" % (device_id,)

    def check_gone_from_deviceauth(self, device_id):
        r = deviceauth.get_device(device_id)
        assert r.status_code == 404, "device [%s] not removed from deviceauth" % (device_id,)

    def check_gone_from_deviceadm(self, adm_id, device_id):
        admissions = adm.get_devices()[0]
        if device_id != admissions["device_id"] and adm_id != admissions["id"]:
            logger.info("device [%s] successfully removed from admission: [%s]" % (device_id, str(admissions)))
        else:
            assert False, "device [%s] not removed from admission: [%s]" % (device_id, str(admissions))

    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_one_client")
    def test_device_decommissioning(self):
        """ Decommission a device successfully """

        if not env.host_string:
            execute(self.test_device_decommissioning, hosts=get_mender_clients())
            return

        adm.check_expected_status("pending", len(get_mender_clients()))
        adm_id = adm.get_devices()[0]["id"]
        device_id = adm.get_devices()[0]["device_id"]

        adm.set_device_status(adm_id, "accepted")

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
        deviceauth.decommission(device_id)

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

        # now check that the device no longer exists in admission
        self.check_gone_from_deviceadm(adm_id, device_id)
