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


import conftest
import requests
import json
from fabric.api import *
import time
import pytest
from MenderAPI import gateway, api_version, logger

class Admission():
    def __init__(self):
        self.admission_base_path = "https://%s/api/integrations/%s/admission/" % (gateway, api_version)

    def get_devices(self):
        return self.get_devices_status()

    # return devices with the specified status
    def get_devices_status(self, status=None):
        device_status_path = self.admission_base_path + "devices"

        tries = 5
        for c, i in enumerate(range(tries)):
            time.sleep(c*5+5)
            try:
                devices = requests.get(device_status_path, verify=False)
                assert devices.status_code == requests.status_codes.codes.ok
                assert len(devices.json()) > 0
                break
            except AssertionError:
                logger.info("fail to get devices (payload: %s), will try #%d times" % (devices.text, tries-c-1))
                continue

        devices_json = devices.json()

        if not status:
            return devices_json

        matching = []
        for d in devices_json:
            if d["status"] == status:
                matching.append(d)
        return matching


    def set_device_status(self, device_id, status):
        r = requests.put(self.admission_base_path + "devices/%s/status" % device_id,
                         headers={'Content-Type': 'application/json'},
                         data=json.dumps({"status": status}),
                         verify=False)
        assert r.status_code == requests.status_codes.codes.ok


    def check_expected_status(self, status, expected_value, max_wait=60, polling_frequency=0.2):
        timeout = time.time() + max_wait
        seen = set()

        while time.time() <= timeout:
            time.sleep(polling_frequency)

            data = self.get_devices_status(status)
            seen.add(str(data))

            count = 0
            for device in data:
                if device["status"] == status:
                    count += 1

            if count != expected_value:
                continue
            else:
                return

        if time.time() > timeout:
            pytest.fail("Never found: %s:%s, only seen: %s" % (status, expected_value, str(seen)))
