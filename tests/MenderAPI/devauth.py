# Copyright 2022 Northern.tech AS
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

import time
import json
import requests
import pytest
import pdb

from . import logger
from . import get_container_manager
from .requests_helpers import requests_retry


class DeviceAuthV2:
    def __init__(self, auth):
        self.reset()
        self.auth = auth

    def reset(self):
        # Reset all temporary values.
        pass

    def get_devauth_base_path(self):
        return "https://%s/api/management/v2/devauth/" % (
            get_container_manager().get_mender_gateway()
        )

    def get_device(self, device_id):
        url = self.get_devauth_base_path() + device_id
        return requests_retry().get(
            url, verify=False, headers=self.auth.get_auth_token()
        )

    def get_devices(self, expected_devices=1):
        return self.get_devices_status(expected_devices=expected_devices)

    # return devices with the specified status
    def get_devices_status(
        self, status=None, expected_devices=1, max_wait=10 * 60, no_assert=False
    ):
        device_status_path = self.get_devauth_base_path() + "devices"
        devices = None
        starttime = time.time()
        sleeptime = 5

        pdb.set_trace()
        got_devices = False
        while starttime + max_wait >= time.time():
            time.sleep(sleeptime)
            # Linear backoff
            sleeptime += 5
            logger.info("getting all devices from: %s" % (device_status_path))
            devices = requests_retry().get(
                device_status_path, headers=self.auth.get_auth_token(), verify=False
            )
            if (
                devices.status_code == requests.status_codes.codes.ok
                and len(devices.json()) >= expected_devices
            ):
                got_devices = True
                break
            else:
                if devices is not None and getattr(devices, "text"):
                    logger.info(
                        "fail to get devices (payload: %s), will try for at least %d more seconds"
                        % (devices.text, starttime + max_wait - time.time())
                    )
                else:
                    logger.info(
                        "failed to get devices, will try for at least %d more seconds"
                        % (starttime + max_wait - time.time())
                    )

        if not no_assert:
            assert got_devices, "Not able to get devices"

        devices_json = devices.json()

        if not status:
            return devices_json

        matching = []
        for d in devices_json:
            if d["status"] == status:
                matching.append(d)
        return matching

    def set_device_auth_set_status(self, device_id, auth_set_id, status):
        headers = {"Content-Type": "application/json"}
        headers.update(self.auth.get_auth_token())

        r = requests_retry().put(
            self.get_devauth_base_path()
            + "devices/%s/auth/%s/status" % (device_id, auth_set_id),
            verify=False,
            headers=headers,
            data=json.dumps({"status": status}),
        )
        assert r.status_code == requests.status_codes.codes.no_content

    def check_expected_status(
        self, status, expected_value, max_wait=60 * 60, polling_frequency=1
    ):
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
            pytest.fail(
                "Never found: %s:%s, only seen: %s"
                % (status, expected_value, str(seen))
            )

    def accept_devices(self, expected_devices):
        if len(
            self.get_devices_status("accepted", expected_devices=expected_devices)
        ) == len(get_container_manager().get_mender_clients()):
            return

        # iterate over devices and accept them
        for d in self.get_devices(expected_devices=expected_devices):
            self.set_device_auth_set_status(
                d["id"], d["auth_sets"][0]["id"], "accepted"
            )

        # block until devices are actually accepted
        timeout = time.time() + 30
        while time.time() <= timeout:
            time.sleep(1)
            if (
                len(
                    self.get_devices_status(
                        status="accepted", expected_devices=expected_devices
                    )
                )
                == expected_devices
            ):
                break

        if time.time() > timeout:
            pytest.fail("wasn't able to accept device after 30 seconds")

        logger.info("Successfully bootstrap all clients")

    def preauth(self, device_identity, pubkey):
        path = "https://%s/api/management/v2/devauth/devices" % (
            get_container_manager().get_mender_gateway()
        )
        req = {"identity_data": device_identity, "pubkey": pubkey}
        headers = {"Content-Type": "application/json"}
        headers.update(self.auth.get_auth_token())

        return requests_retry().post(
            path, data=json.dumps(req), headers=headers, verify=False
        )

    def delete_auth_set(self, did, aid):
        path = "https://%s/api/management/v2/devauth/devices/%s/auth/%s" % (
            get_container_manager().get_mender_gateway(),
            did,
            aid,
        )

        headers = {"Content-Type": "application/json"}
        headers.update(self.auth.get_auth_token())

        return requests_retry().delete(path, headers=headers, verify=False)

    def decommission(self, deviceID, expected_http_code=204):
        decommission_path_url = (
            self.get_devauth_base_path() + "devices/" + str(deviceID)
        )
        r = requests_retry().delete(
            decommission_path_url, verify=False, headers=self.auth.get_auth_token()
        )
        assert r.status_code == expected_http_code
        logger.info("device [%s] is decommissioned" % (deviceID))
