# Copyright 2023 Northern.tech AS
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

URL_MGMT = "/api/management/v1/deployments"
URL_DEVICES = "/api/devices/v1/deployments"

URL_NEXT = "/device/deployments/next"
URL_LOG = "/device/deployments/{id}/log"
URL_STATUS = "/device/deployments/{id}/status"
URL_DEPLOYMENTS = "/deployments"
URL_DEPLOYMENTS_GROUP = "/deployments/group/{name}"
URL_DEPLOYMENTS_ID = "/deployments/{id}"
URL_DEPLOYMENTS_DEVICES = "/deployments/{id}/devices"
URL_DEPLOYMENTS_STATISTICS = "/deployments/{id}/statistics"
URL_DEPLOYMENTS_ARTIFACTS = "/artifacts"
URL_DEPLOYMENTS_ARTIFACTS_GET = "/artifacts/{id}"
URL_DEPLOYMENTS_ARTIFACTS_DOWNLOAD = "/artifacts/{id}/download"
URL_DEPLOYMENTS_ARTIFACTS_GENERATE = "/artifacts/generate"
