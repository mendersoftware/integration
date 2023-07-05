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

HOST = "mender-reporting:8080"

URL_INTERNAL = "/api/internal/v1/reporting"
URL_INTERNAL_DEVICES_SEARCH = "/tenants/{tenant_id}/devices/search"

URL_MGMT = "/api/management/v1/reporting"
URL_MGMT_DEVICES_SEARCH = "/devices/search"
URL_MGMT_DEPLOYMENTS_DEVICES_SEARCH = "/deployments/devices/search"

REPORTING_DATA_PROPAGATION_SLEEP_TIME_SECS = 4.0

OPENSEARCH_DELETE_URL = (
    "http://mender-opensearch:9200/devices/_delete_by_query?conflicts=proceed"
)
