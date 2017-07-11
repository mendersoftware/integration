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
from MenderAPI import inv, adm, deviceauth
from mendertesting import MenderTesting

# ugly way of passing a the "true" parameter to "standard_setup_one_client"
@pytest.mark.parametrize("standard_setup_one_client", ["force_new"], indirect=True)
class TestDeviceDecommissioning(MenderTesting):


    @MenderTesting.fast
    def test_device_decommissioning(self, standard_setup_one_client):
        """ Decommission a device successfully """

        if not env.host_string:
            execute(self.test_device_decommissioning, standard_setup_one_client, hosts=get_mender_clients())
            return

        adm.check_expected_status("pending", len(get_mender_clients()))
        adm_id = adm.get_devices()[0]["id"]
        device_id = adm.get_devices()[0]["device_id"]

        adm.set_device_status(adm_id, "accepted")

        # wait until inventory is populated
        timeout = time.time() + (60 * 5)
        while time.time() < timeout:
            inventoryJSON = inv.get_devices()
            if "attributes" in inventoryJSON[0]:
                break
            time.sleep(.5)
        else:
            assert False, "never got inventory"

        # decommission actual device
        deviceauth.decommission(device_id)

        # now check that the device no longer exists in admissions
        timeout = time.time() + (60 * 5)
        while time.time() < timeout:
                newAdmissions = adm.get_devices()[0]
                if device_id != newAdmissions["device_id"] \
                   and adm_id != newAdmissions["id"]:
                       break
                time.sleep(.5)
        else:
            assert False, "decommissioned device still available in admissions"

        # make sure a deployment to the decommissioned device fails
        try:
            time.sleep(60)  # sometimes deployment microservice hasn't removed the device yet
            deployment_id, _ = common_update_procedure(install_image=conftest.get_valid_image(),
                                                       devices=[device_id],
                                                       verify_status=False)
        except AssertionError:
            logging.info("Failed to deploy upgrade to rejected device, as expected.")
        else:
            assert False, "No error while trying to deploy to rejected device"

        # authtoken has been removed
        run("strings /data/mender/mender-store | grep -q 'authtoken' || false")

        """
            at this point, the device will re-appear, since it's actually still
            online, and not actually decomissioned
        """
        adm.check_expected_status("pending", len(get_mender_clients()))

        # make sure inventory is empty as well
        assert len(inv.get_devices()) == 0
