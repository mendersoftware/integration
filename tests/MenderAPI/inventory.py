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
from MenderAPI import gateway, api_version, logger, admission

class Inventory():
    auth_header = None
    def __init__(self, auth_header):
        self.auth_header = auth_header
        self.inv_base_path = "https://%s/api/management/%s/inventory/" % (gateway, api_version)

    def get_devices(self):
        devices = requests.get(self.inv_base_path + "devices", headers=self.auth_header, verify=False)
        assert devices.status_code == requests.status_codes.codes.ok
        return devices.json()
