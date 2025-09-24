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


class DeviceMonitor:
    auth = None

    def __init__(self, auth):
        self.reset()
        self.auth = auth

    def reset(self):
        # Reset all temporary values.
        pass

    def get_inv_base_path(self):
        return "https://%s/api/management/%s/devicemonitor/" % (
            get_container_manager().get_mender_gateway(),
            api_version,
        )

    def get_alerts(self, device_id):
        """get_alerts for given device management API."""
        params = {"page=1": 1, "per_page": 20, "sort_ascending": False}
        ret = requests_retry().get(
            self.get_inv_base_path() + "devices/" + device_id + "/alerts",
            params=params,
            headers=self.auth.get_auth_token(),
            verify=False,
        )
        assert ret.status_code == requests.status_codes.codes.ok
        return ret.json()

    def get_configuration(self, device_id):
        """get_configuration for given device management API."""
        ret = requests_retry().get(
            self.get_inv_base_path() + "devices/" + device_id + "/config",
            headers=self.auth.get_auth_token(),
            verify=False,
        )
        assert ret.status_code == requests.status_codes.codes.ok
        return ret.json()
