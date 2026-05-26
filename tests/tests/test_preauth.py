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

import json
import time
import uuid

import redo
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from ..common_setup import standard_setup_one_client, enterprise_no_client
from .mendertesting import MenderTesting
from ..MenderAPI import auth, devauth, logger
from ..helpers import Helpers
from testutils.infra.device import MenderDevice


class TestPreauthBase(MenderTesting):
    def do_test_ok_preauth_and_bootstrap(self, container_manager):
        """
        Test the happy path from preauthorizing a device to a successful bootstrap.
        Verify that the device/auth set appear correctly in devauth API results.
        """
        mender_device = container_manager.device

        # we'll use the same pub key for the preauth'd device, so get it
        preauth_key = Client.get_pub_key(mender_device)

        # preauthorize a new device
        preauth_iddata = {"mac": "mac-preauth"}
        # serialize manually to avoid an extra space (id data helper doesn't insert one)
        preauth_iddata_str = '{"mac":"mac-preauth"}'

        r = devauth.preauth(json.loads(preauth_iddata_str), preauth_key)
        assert r.status_code == 201

        # verify the device appears correctly in api results
        devs = devauth.get_devices(2)

        dev_preauth = [d for d in devs if d["status"] == "preauthorized"]
        assert len(dev_preauth) == 1
        dev_preauth = dev_preauth[0]
        logger.info("dev_prauth_map: " + str(dev_preauth))
        assert dev_preauth["identity_data"] == preauth_iddata
        assert len(dev_preauth["auth_sets"]) == 1
        assert dev_preauth["auth_sets"][0]["pubkey"] == preauth_key

        # make one of the existing devices the preauthorized device
        # by substituting id data script
        Client.substitute_id_data(mender_device, preauth_iddata)

        # verify api results - after some time the device should be 'accepted'
        dev_accepted = []
        for _ in redo.retrier(attempts=40, sleeptime=15):
            dev_accepted = devauth.get_devices_status(
                status="accepted", expected_devices=2
            )
            if len([d for d in dev_accepted if d["status"] == "accepted"]) == 1:
                break

        logger.info("devices: " + str(dev_accepted))
        dev_accepted = [d for d in dev_accepted if d["status"] == "accepted"]
        logger.info("accepted devices: " + str(dev_accepted))

        Client.get_logs(mender_device)

        assert len(dev_accepted) == 1, "looks like the device was never accepted"
        dev_accepted = dev_accepted[0]
        logger.info("accepted device: " + str(dev_accepted))

        assert dev_accepted["identity_data"] == preauth_iddata
        assert len(dev_preauth["auth_sets"]) == 1
        assert dev_accepted["auth_sets"][0]["pubkey"] == preauth_key

        # verify device was issued a token
        Helpers.check_log_is_authenticated(mender_device)


class TestPreauth(TestPreauthBase):
    def test_ok_preauth_and_bootstrap(self, standard_setup_one_client):
        self.do_test_ok_preauth_and_bootstrap(standard_setup_one_client)


class TestPreauthEnterprise(TestPreauthBase):
    def test_ok_preauth_and_bootstrap(self, enterprise_no_client):
        self.__create_tenant_and_container(enterprise_no_client)
        self.do_test_ok_preauth_and_bootstrap(enterprise_no_client)

    def __create_tenant_and_container(self, container_manager):
        uuidv4 = str(uuid.uuid4())
        auth.new_tenant(
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "hunter2hunter2",
        )
        token = auth.current_tenant["tenant_token"]

        container_manager.new_tenant_client("tenant-container", token)
        mender_device = MenderDevice(container_manager.get_mender_clients()[0])
        mender_device.ssh_is_opened()
        container_manager.device = mender_device


class Client:
    """Wraps various actions on the client, performed via SSH (inside fabric.execute())."""

    ID_HELPER = "/usr/share/mender/identity/mender-device-identity"
    PRIV_KEY = "/data/mender/mender-agent.pem"

    KEYGEN_TIMEOUT = 300

    @staticmethod
    def get_logs(device):
        output_from_journalctl = device.run("journalctl --unit mender-updated --full")
        logger.info(output_from_journalctl)

    @staticmethod
    def get_pub_key(device):
        """Extract the device's public key from its private key."""

        Client.__wait_for_keygen(device)
        keystr = device.run("cat {}".format(Client.PRIV_KEY))
        private_key = serialization.load_pem_private_key(
            data=keystr.encode() if isinstance(keystr, str) else keystr,
            password=None,
            backend=default_backend(),
        )
        public_key = private_key.public_key()
        return public_key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

    @staticmethod
    def substitute_id_data(device, id_data_dict):
        """Change the device's identity by substituting it's id data helper script."""

        id_data = "#!/bin/sh\n"
        for k, v in id_data_dict.items():
            id_data += "echo {}={}\n".format(k, v)

        cmd = 'echo "{}" > {}'.format(id_data, Client.ID_HELPER)
        device.run(cmd)

    @staticmethod
    def __wait_for_keygen(device):
        attempts = Client.KEYGEN_TIMEOUT // 10
        for _ in redo.retrier(attempts=attempts, sleeptime=10):
            try:
                device.run("stat {}".format(Client.PRIV_KEY))
                break
            except Exception:
                logger.info("waiting for key gen...")
