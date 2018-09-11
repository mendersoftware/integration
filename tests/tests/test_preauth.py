#!/usr/bin/python
# Copyright 2017 Northern.tech AS
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
from mendertesting import MenderTesting
from common_setup import *
from MenderAPI import adm, deviceauth, inv
import pytest
import json
import logging

from Crypto.PublicKey import RSA

import time


class TestPreauthBase(MenderTesting):
    def do_test_ok_preauth_and_bootstrap(self):
        """
            Test the happy path from preauthorizing a device to a successful bootstrap.
            Verify that the device/auth set appear correctly in admission API results.
        """
        client = get_mender_clients()[0]

        # we'll use the same pub key for the preauth'd device, so get it
        res = execute(Client.get_pub_key, hosts=client)
        preauth_key = res[client].exportKey()

        # stick an extra newline on the key - this is how a device would send it
        preauth_key += '\n'

        # preauthorize a new device
        preauth_iddata = {"mac": "mac-preauth"}
        # serialize manually to avoid an extra space (id data helper doesn't insert one)
        preauth_iddata_str = "{\"mac\":\"mac-preauth\"}"

        r = adm.preauth(preauth_iddata_str, preauth_key)
        assert r.status_code == 201

        # verify the device appears correctly in api results
        devs = adm.get_devices(2)

        dev_preauth = [d for d in devs if d['status'] == 'preauthorized']
        assert len(dev_preauth) == 1
        dev_preauth = dev_preauth[0]
        assert dev_preauth['device_identity'] == preauth_iddata_str
        assert dev_preauth['key'] == preauth_key

        # make one of the existing devices the preauthorized device
        # by substituting id data and restarting
        res = execute(Client.substitute_id_data, preauth_iddata, hosts=client)
        res = execute(Client.restart, hosts=client)

        # verify api results - after some time the device should be 'accepted'
        for _ in range(120):
            time.sleep(15)
            dev_accepted = adm.get_devices_status(status="accepted", expected_devices=2)
            if len([d for d in dev_accepted if d['status'] == 'accepted']) == 1:
                break


        logging.info("devices: " + str(dev_accepted))
        dev_accepted = [d for d in dev_accepted if d['status'] == 'accepted']
        logging.info("accepted devices: " + str(dev_accepted))

        execute(Client.get_logs, hosts=client)

        assert len(dev_accepted) == 1, "looks like the device was never accepted"
        dev_accepted = dev_accepted[0]
        logging.info("accepted device: " + str(dev_accepted))

        assert dev_accepted['device_identity'] == preauth_iddata_str
        assert dev_accepted['key'] == preauth_key

        # verify device was issued a token
        res = execute(Client.have_authtoken, hosts=client)
        assert res[client]

    def do_test_ok_preauth_and_remove(self):
        """
            Test the removal of a preauthorized auth set, verify it's gone from all API results.
        """
        # preauthorize
        preauth_iddata = "{\"mac\":\"preauth-mac\"}"
        preauth_key = '''-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzogVU7RGDilbsoUt/DdH
VJvcepl0A5+xzGQ50cq1VE/Dyyy8Zp0jzRXCnnu9nu395mAFSZGotZVr+sWEpO3c
yC3VmXdBZmXmQdZqbdD/GuixJOYfqta2ytbIUPRXFN7/I7sgzxnXWBYXYmObYvdP
okP0mQanY+WKxp7Q16pt1RoqoAd0kmV39g13rFl35muSHbSBoAW3GBF3gO+mF5Ty
1ddp/XcgLOsmvNNjY+2HOD5F/RX0fs07mWnbD7x+xz7KEKjF+H7ZpkqCwmwCXaf0
iyYyh1852rti3Afw4mDxuVSD7sd9ggvYMc0QHIpQNkD4YWOhNiE1AB0zH57VbUYG
UwIDAQAB
-----END PUBLIC KEY-----
'''

        r = adm.preauth(preauth_iddata, preauth_key)
        assert r.status_code == 201

        devs = adm.get_devices(2)

        dev_preauth = [d for d in devs if d['device_identity'] == preauth_iddata]
        assert len(dev_preauth) == 1
        dev_preauth = dev_preauth[0]

        # remove from admission
        r = adm.delete_auth_set(dev_preauth['id'])
        assert r.status_code == 204

        # verify removed from admission
        devs = adm.get_devices(1)
        dev_removed = [d for d in devs if d['device_identity'] == preauth_iddata]
        assert len(dev_removed) == 0

        # verify removed from deviceauth
        r = deviceauth.get_device(dev_preauth['id'])
        assert r.status_code == 404

        # verify removed from inventory
        r = inv.get_device(dev_preauth['id'])
        assert r.status_code == 404

    def do_test_fail_preauth_existing(self):
        """
           Test 'conflict' response when an identity data set already exists.
        """
        # wait for the device to appear
        devs = adm.get_devices(1)
        dev = devs[0]

        # try to preauthorize the same id data, new key
        preauth_key = '''-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzogVU7RGDilbsoUt/DdH
VJvcepl0A5+xzGQ50cq1VE/Dyyy8Zp0jzRXCnnu9nu395mAFSZGotZVr+sWEpO3c
yC3VmXdBZmXmQdZqbdD/GuixJOYfqta2ytbIUPRXFN7/I7sgzxnXWBYXYmObYvdP
okP0mQanY+WKxp7Q16pt1RoqoAd0kmV39g13rFl35muSHbSBoAW3GBF3gO+mF5Ty
1ddp/XcgLOsmvNNjY+2HOD5F/RX0fs07mWnbD7x+xz7KEKjF+H7ZpkqCwmwCXaf0
iyYyh1852rti3Afw4mDxuVSD7sd9ggvYMc0QHIpQNkD4YWOhNiE1AB0zH57VbUYG
UwIDAQAB
-----END PUBLIC KEY-----
'''
        r = adm.preauth(dev['device_identity'], preauth_key)
        assert r.status_code == 409


class TestPreauth(TestPreauthBase):
    @pytest.mark.skip(reason="there is a problem with this test: MEN-1797")
    @pytest.mark.usefixtures("standard_setup_one_client")
    def test_ok_preauth_and_bootstrap(self):
        self.do_test_ok_preauth_and_bootstrap()

    @pytest.mark.usefixtures("standard_setup_one_client")
    def test_ok_preauth_and_remove(self):
        self.do_test_ok_preauth_and_remove()

    @pytest.mark.usefixtures("standard_setup_one_client")
    def test_fail_preauth_existing(self):
        self.do_test_fail_preauth_existing()


class TestPreauthMultiTenant(TestPreauthBase):
    @pytest.mark.skip(reason="there is a problem with this test: MEN-1797")
    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_ok_preauth_and_bootstrap(self):
        self.__create_tenant_and_container()
        self.do_test_ok_preauth_and_bootstrap()

    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_ok_preauth_and_remove(self):
        self.__create_tenant_and_container()
        self.do_test_ok_preauth_and_remove()

    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_fail_preauth_existing(self):
        self.__create_tenant_and_container()
        self.do_test_fail_preauth_existing()

    def __create_tenant_and_container(self):
        auth.new_tenant("admin", "admin@tenant.com", "hunter2hunter2")
        token = auth.current_tenant["tenant_token"]

        new_tenant_client("tenant-container", token)
        client = get_mender_clients()[0]
        ssh_is_opened(client)

class Client:
    """Wraps various actions on the client, performed via SSH (inside fabric.execute())."""

    ID_HELPER = '/usr/share/mender/identity/mender-device-identity'
    PRIV_KEY = '/data/mender/mender-agent.pem'
    MENDER_STORE = '/data/mender/mender-store'

    KEYGEN_TIMEOUT = 300
    DEVICE_ACCEPTED_TIMEOUT = 600
    MENDER_STORE_TIMEOUT = 600


    @staticmethod
    def get_logs():
        output_from_journalctl = run("journalctl -u mender -l")
        logging.info(output_from_journalctl)

    @staticmethod
    def get_pub_key():
        """Extract the device's public key from its private key."""

        Client.__wait_for_keygen()
        keystr = run('cat {}'.format(Client.PRIV_KEY))
        key = RSA.importKey(keystr)
        return key.publickey()

    @staticmethod
    def substitute_id_data(id_data_dict):
        """Change the device's identity by substituting it's id data helper script."""

        id_data = '#!/bin/sh\n'
        for k,v in id_data_dict.items():
            id_data += 'echo {}={}\n'.format(k,v)

        cmd = 'echo "{}" > {}'.format(id_data, Client.ID_HELPER)
        run(cmd)

    @staticmethod
    def restart():
        """Restart the mender service."""

        run('systemctl restart mender.service')

    @staticmethod
    def have_authtoken():
        """Verify that the device was authenticated by checking its data store for the authtoken."""
        sleepsec = 0
        while sleepsec < Client.MENDER_STORE_TIMEOUT:
            try:
                out = run('strings {} | grep authtoken'.format(Client.MENDER_STORE))
                return out != ''
            except:
                output_from_journalctl = run("journalctl -u mender -l")
                logging.info("Logs from client: " + output_from_journalctl)

                time.sleep(10)
                sleepsec += 10
                logging.info("waiting for mender-store file, sleepsec: {}".format(sleepsec))

        assert sleepsec <= Client.MENDER_STORE_TIMEOUT, "timeout for mender-store file exceeded"

    @staticmethod
    def __wait_for_keygen():
        sleepsec = 0
        while sleepsec < Client.KEYGEN_TIMEOUT:
            try:
                run('stat {}'.format(Client.PRIV_KEY))
            except:
                time.sleep(10)
                sleepsec += 10
                logging.info("waiting for key gen, sleepsec: {}".format(sleepsec))
            else:
                time.sleep(5)
                break

        assert sleepsec <= Client.KEYGEN_TIMEOUT, "timeout for key generation exceeded"

