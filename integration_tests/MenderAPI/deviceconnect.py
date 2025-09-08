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

from integration_testutils.util import websockets
from integration_testutils.api import deviceconnect
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
        url_path = deviceconnect.URL_MGMT + deviceconnect.URL_MGMT_CONNECT.format(
            id=dev_id
        )
        host_uri = "wss://" + get_container_manager().get_mender_gateway()
        return host_uri + url_path

    def get_websocket(self):
        headers = {}
        headers.update(self.auth.get_auth_token())

        ws = websockets.Websocket(
            self.get_websocket_url(), headers=headers, insecure=True
        )

        return ws

    def get_playback_url(self, session_id, sleep_ms=None):
        url_path = deviceconnect.URL_MGMT + deviceconnect.URL_MGMT_PLAYBACK.format(
            session_id=session_id
        )
        host_uri = "wss://" + get_container_manager().get_mender_gateway()
        url = host_uri + url_path
        if sleep_ms is not None:
            url += "?sleep_ms=%d" % sleep_ms
        return url

    def get_playback_websocket(self, session_id, sleep_ms=None):
        headers = {}
        headers.update(self.auth.get_auth_token())

        ws = websockets.Websocket(
            self.get_playback_url(session_id, sleep_ms), headers=headers, insecure=True
        )
        return ws
