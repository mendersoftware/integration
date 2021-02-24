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

import pytest
import ssl

from testutils.util import websockets
from . import api_version
from . import get_container_manager


class DeviceConnect:
    def __init__(self, auth, devauth):
        self.reset()
        self.auth = auth
        self.devauth = devauth

    def reset(self):
        # Reset all temporary values.
        pass

    def get_websocket_url(self):
        auth_json = self.devauth.get_devices()
        dev_id = auth_json[0]["id"]
        return "wss://%s/api/management/%s/deviceconnect/devices/%s/connect" % (
            get_container_manager().get_mender_gateway(),
            api_version,
            dev_id,
        )

    def get_websocket(self):
        headers = {}
        headers.update(self.auth.get_auth_token())

        ws = websockets.Websocket(
            self.get_websocket_url(), headers=headers, insecure=True
        )

        return ws
