# Copyright 2021 Northern.tech AS
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

import requests

from . import api_version
from . import get_container_manager
from .requests_helpers import requests_retry


class Inventory:
    auth = None

    def __init__(self, auth):
        self.reset()
        self.auth = auth

    def reset(self):
        # Reset all temporary values.
        pass

    def get_inv_base_path(self):
        return "https://%s/api/management/%s/inventory/" % (
            get_container_manager().get_mender_gateway(),
            api_version,
        )

    def get_devices(self, has_group=None):
        """get_devices API. has_group can be True/False/None string."""
        params = {}
        if has_group is not None:
            params = {"has_group": has_group}
        ret = requests_retry().get(
            self.get_inv_base_path() + "devices",
            params=params,
            headers=self.auth.get_auth_token(),
            verify=False,
        )
        assert ret.status_code == requests.status_codes.codes.ok
        return ret.json()

    def get_device(self, device_id):
        devurl = "%s%s/%s" % (self.get_inv_base_path(), "devices", device_id)
        ret = requests_retry().get(
            devurl, headers=self.auth.get_auth_token(), verify=False
        )
        return ret

    def get_groups(self):
        ret = requests_retry().get(
            self.get_inv_base_path() + "groups",
            headers=self.auth.get_auth_token(),
            verify=False,
        )
        assert ret.status_code == requests.status_codes.codes.ok
        return ret.json()

    def get_devices_in_group(self, group):
        req = "groups/%s/devices" % group
        ret = requests_retry().get(
            self.get_inv_base_path() + req,
            headers=self.auth.get_auth_token(),
            verify=False,
        )
        assert ret.status_code == requests.status_codes.codes.ok
        return ret.json()

    def get_device_group(self, device):
        req = "devices/%s/group" % device
        ret = requests_retry().get(
            self.get_inv_base_path() + req,
            headers=self.auth.get_auth_token(),
            verify=False,
        )
        assert ret.status_code == requests.status_codes.codes.ok
        return ret.json()

    def put_device_in_group(self, device, group):
        headers = {"Content-Type": "application/json"}
        headers.update(self.auth.get_auth_token())
        body = '{"group":"%s"}' % group
        req = "devices/%s/group" % device
        ret = requests_retry().put(
            self.get_inv_base_path() + req, data=body, headers=headers, verify=False
        )
        assert ret.status_code == requests.status_codes.codes.no_content

    def delete_device_from_group(self, device, group):
        req = "devices/%s/group/%s" % (device, group)
        ret = requests_retry().delete(
            self.get_inv_base_path() + req,
            headers=self.auth.get_auth_token(),
            verify=False,
        )
        assert ret.status_code == requests.status_codes.codes.no_content
