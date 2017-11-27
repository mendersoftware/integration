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

from MenderAPI import *

class DeviceAuthentication(object):
    auth = None

    def __init__(self, auth):
        self.reset()
        self.auth = auth

    def reset(self):
        # Reset all temporary values.
        pass

    def get_deviceauth_base_path(self):
        return "https://%s/api/management/%s/devauth/devices/" % (get_mender_gateway(), api_version)

    def decommission(self, deviceID, expected_http_code=204):
        decommission_path_url = self.get_deviceauth_base_path() + str(deviceID)
        r = requests.delete(decommission_path_url,
                            verify=False,
                            headers=self.auth.get_auth_token())
        assert r.status_code == expected_http_code
        logger.info("device [%s] is decommissioned" % (deviceID))

    def get_device(self, device_id):
        url = self.get_deviceauth_base_path() + device_id
        return requests.get(url, verify=False, headers=self.auth.get_auth_token())
