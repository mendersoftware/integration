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
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from Crypto.Hash import SHA256
from base64 import b64encode, urlsafe_b64decode, urlsafe_b64encode
import json

import api.client

URL_MGMT = api.client.GATEWAY_URL + '/api/management/v1/devauth'
URL_DEVICES = api.client.GATEWAY_URL + '/api/devices/v1/authentication'

URL_LIST_DEVICES = '/devices'
URL_AUTH_REQS = '/auth_requests'

def auth_req(id_data, pubkey, privkey, tenant_token=''):
    payload = {
        "id_data": json.dumps(id_data),
        "tenant_token": tenant_token,
        "pubkey": pubkey,
    }
    signature = sign_data(json.dumps(payload), privkey)
    return payload, {'X-MEN-Signature': signature}

def get_keypair():
    private = RSA.generate(1024)
    public = private.publickey()
    return private.exportKey().decode(), public.exportKey().decode()


def sign_data(data, privkey):
    rsakey = RSA.importKey(privkey)
    signer = PKCS1_v1_5.new(rsakey)
    digest = SHA256.new()
    if type(data) is str:
        data = data.encode()
    digest.update(data)
    sign = signer.sign(digest)
    return b64encode(sign)
