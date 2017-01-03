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
import json
import pytest
import time
from common import *
from helpers import Helpers
from common_update import common_update_proceduce
from MenderAPI import adm, deploy, image, inv
from mendertesting import MenderTesting

@pytest.mark.usefixtures("bootstrapped_successfully", "ssh_is_opened")
class TestInventory(MenderTesting):

    @MenderTesting.fast
    def test_inventory(self):
        """Test that device reports inventory after having bootstrapped."""

        inv_json = inv.get_devices()
        adm_json = adm.get_devices()

        adm_ids = [device['id'] for device in adm_json]

        assert(len(inv_json) > 0)

        for device in inv_json:
            # Check that admission and inventory agree.
            assert(device['id'] in adm_ids)

            attrs = device['attributes']

            # Check individual attributes.
            assert(json.loads('{"name": "ifaces", "value": "eth0"}') in attrs)
            assert(json.loads('{"name": "hostname", "value": "vexpress-qemu"}') in attrs)
            assert(json.loads('{"name": "device_type", "value": "vexpress-qemu"}') in attrs)

            # Check that all known keys are present.
            keys = [attr['name'] for attr in attrs]
            expected_keys = [
                "hostname",
                "ifaces",
                "cpu_count",
                "time_local",
                "cpu_model",
                "mem_total",
                "device_type",
                "ipv4_eth0",
                "cpu_online",
                "time_unix",
                "uptime",
                "mac_eth0",
                "client_version",
                "mem_free",
                "artifact_name",
                "kernel"
            ]
            assert(sorted(keys) == sorted(expected_keys))
