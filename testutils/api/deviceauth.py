# Copyright 2018 Northern.tech AS
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
import json

import testutils.api.client
import testutils.util.crypto

URL_DEVICES = testutils.api.client.GATEWAY_URL + "/api/devices/v1/authentication"
URL_INTERNAL = "http://mender-device-auth:8080/api/internal/v1/devauth"

URL_AUTH_REQS = "/auth_requests"
URL_LIMITS_MAX_DEVICES = "/tenant/{tid}/limits/max_devices"


def auth_req(id_data, pubkey, privkey, tenant_token=""):
    payload = {
        "id_data": json.dumps(id_data),
        "tenant_token": tenant_token,
        "pubkey": pubkey,
    }
    signature = testutils.util.crypto.rsa_sign_data(json.dumps(payload), privkey)
    return payload, {"X-MEN-Signature": signature}
