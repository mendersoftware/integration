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
from base64 import b64encode
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric import padding

# enum for EC curve types to avoid naming confusion, e.g.
# NIST P-256 (FIPS 186 standard name) ==
# golang's elliptic.P256 ==
# hazmat's ec.SECP256R1
EC_CURVE_224 = ec.SECP224R1
EC_CURVE_256 = ec.SECP256R1
EC_CURVE_384 = ec.SECP384R1
EC_CURVE_521 = ec.SECP521R1


def compare_keys(a, b):
    """
    Compares the base64 encoded DER structure of the keys
    """
    # Filter removes possible empty lines.
    # We then slice away header and footer.
    a_b64 = "".join(list(filter(None, a.splitlines()))[1:-1])
    b_b64 = "".join(list(filter(None, b.splitlines()))[1:-1])
    return a_b64 == b_b64


def get_keypair_rsa(public_exponent=65537, key_size=1024):
    private_key = rsa.generate_private_key(
        public_exponent=public_exponent, key_size=key_size, backend=default_backend(),
    )

    return keypair_pem(private_key, private_key.public_key())


def get_keypair_ec(curve):
    private_key = ec.generate_private_key(curve=curve, backend=default_backend(),)
    return keypair_pem(private_key, private_key.public_key())


def get_keypair_ed():
    private_key = ed25519.Ed25519PrivateKey.generate()
    return keypair_pem(private_key, private_key.public_key())


def keypair_pem(private_key, public_key):
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


def auth_req_sign_rsa(data, private_key):
    signature = private_key.sign(
        data if isinstance(data, bytes) else data.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return b64encode(signature).decode()


def auth_req_sign_ec(data, private_key):
    signature = private_key.sign(
        data if isinstance(data, bytes) else data.encode(), ec.ECDSA(hashes.SHA256()),
    )
    # signature is already an ANSI-X9-62 DER sequence (as bytes)
    return b64encode(signature).decode()


def auth_req_sign_ed(data, private_key):
    signature = private_key.sign(data if isinstance(data, bytes) else data.encode(),)
    return b64encode(signature).decode()


def auth_req_sign(data, private_key):
    key = serialization.load_pem_private_key(
        private_key if isinstance(private_key, bytes) else private_key.encode(),
        password=None,
        backend=default_backend(),
    )

    if isinstance(key, rsa.RSAPrivateKey):
        return auth_req_sign_rsa(data, key)
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        return auth_req_sign_ec(data, key)
    elif isinstance(key, ed25519.Ed25519PrivateKey):
        return auth_req_sign_ed(data, key)
    else:
        raise RuntimeError("unsupported key type")
