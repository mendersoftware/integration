# Copyright 2020 Northern.tech AS
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

from testutils.api.client import ApiClient as _ApiClient

HOST = "mender-tenantadm:8080"
URL_INTERNAL = "/api/internal/v1/tenantadm"
URL_MGMT = "/api/management/v1/tenantadm"

URL_INTERNAL_SUSPEND = "/tenants/{tid}/status"
URL_INTERNAL_TENANTS = "/tenants"
URL_MGMT_TENANTS = "/tenants"
URL_MGMT_THIS_TENANT = "/user/tenant"


def req_status(status):
    return {"status": status}


class InternalApiClient(_ApiClient):
    def __init__(self, host=HOST, scheme="http://"):
        super().__init__(URL_INTERNAL, host, scheme)


class ManagementApiClient(_ApiClient):
    def __init__(self, host=HOST, scheme="http://"):
        super().__init__(URL_MGMT, host, scheme)
