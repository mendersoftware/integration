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

HOST = "mender-inventory:8080"

URL_MGMT = "/api/management/v2/inventory"
URL_INTERNAL = "/api/internal/v2/inventory"

URL_SEARCH = "/filters/search"
URL_FILTERS = "/filters"
URL_SAVED_FILTERS = "/filters"
URL_SAVED_FILTER = "/filters/{id}"
URL_SAVED_FILTER_SEARCH = "/filters/{id}/search"

URL_SEARCH_INTERNAL = "/tenants/{tenant_id}/filters/search"
