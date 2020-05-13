POC for an mTLS ambassador
==============================================

## Intro

For background and details see the [presentation](https://docs.google.com/presentation/d/1_B7oea6WfBulF65yEDJFpeZrCFFPwYFZ6KrMN-9N5sc/edit#slide=id.g780337f567_0_236)
 
## Setup

The POC spans a couple services, pull these PRs first:
- https://github.com/mendersoftware/tenantadm/pull/148
- https://github.com/mendersoftware/deviceauth/pull/339
- https://github.com/mendersoftware/mender-api-gateway-docker/pull/127

Rebuild docker images for those under temporary names (see compose 
files diff). Then start the enterprise setup as usual.

## Trying it out

There's a bunch of scripts that'll help you a lot - grouped in a separate commit. 
These are for creating tenants/users, generating tenant CA certs and signing client certs, 
there's also a modified mender bash client by MirzaK which is mTLS-aware.

Note that these helpers exchange data through the `tls-poc-generated` dir - stuff like certs, tenant tokens, needed for subsequent commands. This is based on a naming
convention.

Basic workflow:

1. Create a tenant and user

   `./create-tenant foo user@foo.com`

    The password for each created user is 'correcthorse'.

2. Enable mTLS verification for tenant

    Generate a CA cert for the tenant:

    `./gen-ca-cert foo`

    It will be dumped into the shared dir.

    Grab the ambassador's ip from the running docker setup, then do:
    `./enable-tenant-mtls --tenant foo --proxy-ip <ip>`

    This will:
    - make the tenant's CA cert available to the ambassador
    - enable client TLS verification for this tenant in tenantadm

3. Start a non-mTLS device 

    Run a tenant's device as usual, against the Mender gateway:

    `./run-bash-client --tenant foo --gateway default`

    This device can't ever get through, because it tries normal communication
    to an mTLS-enabled tenant. It's 401 forever, and it won't show up in the UI.

    You could inspect tenantadm's logs for an error message about it:

    `level=error msg="mTLS is on, requests only accepted from designated gateway"`

4. Make the device mTLS-aware

   First generate a client cert, signed by the tenant's CA:

   `./gen-client-cert foo <devid>`

   Tenant `foo`'s CA will be picked to sign the new cert.
   `devid` is just for the purpose of this demo, to distinguish between tenant's devices.

   From now on, the bash client will be ran with this cert.

5. Run the mTLS-ready device

   The device will now be ran against the mTLS ambassador, which will check 
   the cert against known CA certs.

   The auth request will be forwarded to the regular gateway only on success.

   `./run-bash-client --tenant foo --gateway mtls --client-cert <devid>`

   The device will now appear in the UI for acceptance.

6. Try the device with an invalid cert

   To see how the mTLS ambassador denies traffic if the certificate
   is not signed by a known CA, try:

   `./gen-ca-cert other-tenant`

   `./gen-client-cert other-tenant some-device`

   Replace the valid cert/key with the invalid one:

   `cp tls-poc-generated/other-tenant.client.some-device.crt tls-poc-generated/foo.client.<devid>.crt`

   `cp tls-poc-generated/other-tenant.client.some-device.key tls-poc-generated/foo.client.<devid>.key`

   Then run the bash client again:

   `./run-bash-client --tenant foo --gateway mtls --client-cert <devid>`

   The client presents a well formed cert, but it's not signed by any CA known
   to the mTLS ambassador.

   Bash client's logs will indicate TLS errors, check traefik as well.
