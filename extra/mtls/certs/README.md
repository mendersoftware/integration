# Example certificates for the mTLS setup

This folder contains the example certificates for the mTLS setup:

* `/server` - example self-signed server cert
* `tenant-ca` - example self-signed tenant certificate authority ( key pass: root)
* `client` - example client certs, using different algorithms, signed by `tenant-ca`

You can create your own certificates following the [Mutual TLS documentation](https://docs.mender.io/2.7/server-integration/mutual-tls-authentication).

## Generation of keys

Use the `generate.sh` script to recreate the crypto materials:

```bash
$ ./generate.sh
```

If running on Mac OS, use the openssl binary installed using brew instead of LibreSSL,
because it doesn't support the ed25519 curve:

```bash
$ OPENSSL=/usr/local/opt/openssl@1.1/bin/openssl ./generate.sh
```
