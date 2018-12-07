#!/usr/bin/python
# Copyright 2018 Mender Software AS
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
from Crypto.Hash import SHA256
from Crypto.Signature import PKCS1_v1_5
from base64 import b64encode, urlsafe_b64decode, urlsafe_b64encode

def rsa_compare_keys(a,b):
    ai = RSA.importKey(a)
    bi = RSA.importKey(b)

    return ai.exportKey().decode() == bi.exportKey().decode()

def rsa_get_keypair():
    private = RSA.generate(1024)
    public = private.publickey()
    return private.exportKey().decode(), public.exportKey().decode()

def rsa_sign_data(data, privkey):
    rsakey = RSA.importKey(privkey)
    signer = PKCS1_v1_5.new(rsakey)
    digest = SHA256.new()
    if type(data) is str:
        data = data.encode()
    digest.update(data)
    sign = signer.sign(digest)
    return b64encode(sign)
