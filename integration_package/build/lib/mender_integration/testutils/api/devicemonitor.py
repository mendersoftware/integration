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

HOST = "mender-devicemonitor:8080"

URL_DEVICES = "/api/devices/v1/devicemonitor"
URL_INTERNAL = "/api/internal/v1/devicemonitor"
URL_MGMT = "/api/management/v1/devicemonitor"

URL_ALERT = "/alert"
URL_DEVICE_ALERTS = lambda device_id: f"/devices/{id}/alerts".format(id=device_id)
