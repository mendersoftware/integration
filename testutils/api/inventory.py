# Copyright 2019 Northern.tech AS
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
import testutils.api.client

URL_MGMT = testutils.api.client.GATEWAY_URL + "/api/management/v1/inventory"
URL_DEV = testutils.api.client.GATEWAY_URL + "/api/devices/v1/inventory"

URL_DEVICE = "/devices/{id}"
URL_DEVICES = "/devices"
URL_DEVICE_GROUP = "/devices/{id}/group"
URL_GROUPS = "/devices/groups"
URL_GROUP = "/devices/group/{name}/devices"

URL_DEVICE_ATTRIBUTES = "/device/attributes"

URL_FILTERS = "/filters"
