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
from base64 import b64encode
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import padding


def rsa_compare_keys(a, b):
    """
    Compares the base64 encoded DER structure of the keys
    """
    # Filter removes possible empty lines.
    # We then slice away header and footer.
    a_b64 = "".join(list(filter(None, a.splitlines()))[1:-1])
    b_b64 = "".join(list(filter(None, b.splitlines()))[1:-1])
    return a_b64 == b_b64


def rsa_get_keypair():
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=1024, backend=default_backend()
    )
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem.decode(), public_pem.decode()


def rsa_sign_data(data, private_key):
    _private_key = serialization.load_pem_private_key(
        private_key if isinstance(private_key, bytes) else private_key.encode(),
        password=None,
        backend=default_backend(),
    )
    signature = _private_key.sign(
        data if isinstance(data, bytes) else data.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return b64encode(signature).decode()
