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

class Admission():
    auth = None

    def __init__(self, auth):
        self.reset()
        self.auth = auth

    def reset(self):
        # Reset all temporary values.
        pass

    def get_admission_base_path(self):
        return "https://%s/api/management/%s/admission/" % (get_mender_gateway(), api_version)

    def get_devices(self, expected_devices=1):
        return self.get_devices_status(expected_devices=expected_devices)

    # return devices with the specified status
    def get_devices_status(self, status=None, expected_devices=1):
        device_status_path = self.get_admission_base_path() + "devices"
        devices = None
        max_wait = 60*60
        starttime = time.time()
        sleeptime = 5

        while starttime + max_wait >= time.time():
            time.sleep(sleeptime)
            # Linear backoff
            sleeptime += 5
            try:
                logger.info("getting all devices from :%s" % (device_status_path))
                devices = requests.get(device_status_path, headers=self.auth.get_auth_token(), verify=False)
                assert devices.status_code == requests.status_codes.codes.ok
                assert len(devices.json()) == expected_devices
                break
            except AssertionError:
                if devices is not None and getattr(devices, "text"):
                    logger.info("fail to get devices (payload: %s), will try for at least %d more seconds"
                                % (devices.text, starttime + max_wait - time.time()))
                else:
                    logger.info("failed to get devices, will try for at least %d more seconds"
                                % (starttime + max_wait - time.time()))
                continue
        else:
            assert False, "Not able to get devices"

        devices_json = devices.json()

        if not status:
            return devices_json

        matching = []
        for d in devices_json:
            if d["status"] == status:
                matching.append(d)
        return matching

    def set_device_status(self, device_id, status):
        headers = {"Content-Type": "application/json"}
        headers.update(self.auth.get_auth_token())

        r = requests.put(self.get_admission_base_path() + "devices/%s/status" % device_id,
                         verify=False,
                         headers=headers,
                         data=json.dumps({"status": status}))
        assert r.status_code == requests.status_codes.codes.ok

    def check_expected_status(self, status, expected_value, max_wait=60*60, polling_frequency=1):
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

    def accept_devices(self, expected_devices):
        if len(self.get_devices_status("accepted", expected_devices=expected_devices)) == len(get_mender_clients()):
            return

        # iterate over devices and accept them
        for d in self.get_devices(expected_devices=expected_devices):
            self.set_device_status(d["id"], "accepted")

        logger.info("Successfully bootstrap all clients")
