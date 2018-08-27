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
import json
import pytest
import time
from common import *
from common_setup import *
from helpers import Helpers
from MenderAPI import adm, deploy, image, inv
from mendertesting import MenderTesting

@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestInventory(MenderTesting):

    @MenderTesting.fast
    def test_inventory(self):
        """Test that device reports inventory after having bootstrapped."""

        attempts = 10

        while True:
            attempts = attempts - 1
            try:
                inv_json = inv.get_devices()
                adm_json = adm.get_devices()

                adm_ids = [device['device_id'] for device in adm_json]

                assert(len(inv_json) > 0)

                for device in inv_json:
                    try:
                        # Check that admission and inventory agree.
                        assert(device['id'] in adm_ids)

                        attrs = device['attributes']

                        # Check individual attributes.
                        network_interfaces = [elem for elem in attrs if elem['name'] == "network_interfaces"]
                        assert len(network_interfaces) == 1
                        network_interfaces = network_interfaces[0]
                        if type(network_interfaces['value']) is str:
                            assert any(network_interfaces['value'] == iface for iface in ["eth0", "enp0s3"])
                        else:
                            assert any(iface in network_interfaces['value'] for iface in ["eth0", "enp0s3"])
                        assert(json.loads('{"name": "hostname", "value": "%s"}' % conftest.machine_name) in attrs)
                        assert(json.loads('{"name": "device_type", "value": "%s"}' % conftest.machine_name) in attrs)

                        if conftest.machine_name == "qemux86-64":
                            bootloader_integration = "uefi_grub"
                        elif conftest.machine_name == "vexpress-qemu":
                            bootloader_integration = "uboot"
                        else:
                            pytest.fail("Unknown machine_name. Please add an expected bootloader_integration for this machine_name")
                        assert(json.loads('{"name": "mender_bootloader_integration", "value": "%s"}' % bootloader_integration) in attrs)

                        # Check that all known keys are present.
                        keys = [str(attr['name']) for attr in attrs]
                        expected_keys = [
                            "hostname",
                            "network_interfaces",
                            "cpu_model",
                            "mem_total_kB",
                            "device_type",
                            ["ipv4_enp0s3", "ipv6_enp0s3", "ipv4_eth0"], # Multiple possibilities
                            ["mac_enp0s3", "mac_eth0"],
                            "mender_client_version",
                            "artifact_name",
                            "kernel",
                            "os",
                        ]
                        for key in expected_keys:
                            if type(key) is list:
                                assert any([subkey in keys for subkey in key])
                            else:
                                assert key in keys

                    except:
                        print("Exception caught, 'device' json: ", device)
                        raise
                break

            except:
                # This may pass only after the client has had some time to
                # report.
                if attempts > 0:
                    time.sleep(5)
                    continue
                else:
                    raise
