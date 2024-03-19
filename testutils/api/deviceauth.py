# Copyright 2024 Northern.tech AS
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
import json
from typing import Dict, Tuple

import testutils.util.crypto

HOST = "mender-device-auth:8080"

URL_DEVICES = "/api/devices/v1/authentication"
URL_INTERNAL = "/api/internal/v1/devauth"
URL_MGMT = "/api/management/v2/devauth"

URL_AUTH_REQS = "/auth_requests"

URL_AUTHSET = "/devices/{did}/auth/{aid}"
URL_AUTHSET_STATUS = "/devices/{did}/auth/{aid}/status"

URL_MGMT_DEVICES = "/devices"

URL_DEVICE = "/devices/{id}"
URL_DEVICES_COUNT = "/devices/count"

URL_LIMITS_MAX_DEVICES = "/limits/max_devices"
URL_INTERNAL_LIMITS_MAX_DEVICES = "/tenant/{tid}/limits/max_devices"


def preauth_req(id_data, pubkey, force=False):
    if force:
        return {"force": True, "identity_data": id_data, "pubkey": pubkey}
    else:
        return {"identity_data": id_data, "pubkey": pubkey}


def req_status(status):
    return {"status": status}


def auth_req(id_data, pubkey, privkey, tenant_token="") -> Tuple[Dict, Dict]:
    payload = {
        "id_data": json.dumps(id_data),
        "tenant_token": tenant_token,
        "pubkey": pubkey,
    }
    signature = testutils.util.crypto.auth_req_sign(json.dumps(payload), privkey)
    return payload, {"X-MEN-Signature": signature}
