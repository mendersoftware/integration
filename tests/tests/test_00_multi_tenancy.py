# Copyright 2022 Northern.tech AS
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

import uuid
import time

from ..common_setup import enterprise_no_client
from .common_update import update_image, common_update_procedure
from ..MenderAPI import auth, devauth, logger, inv
from .mendertesting import MenderTesting
from testutils.common import new_tenant_client


class TestMultiTenancyEnterprise(MenderTesting):
    def test_token_validity(self, enterprise_no_client):
        """verify that only devices with valid tokens can bootstrap
        successfully to a multitenancy setup"""

        wrong_token = "wrong-token"

        auth.reset_auth_token()
        uuidv4 = str(uuid.uuid4())
        auth.new_tenant(
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "hunter2hunter2",
        )
        token = auth.current_tenant["tenant_token"]

        # create a new client with an incorrect token set
        mender_device = new_tenant_client(
            enterprise_no_client, "mender-client", wrong_token
        )
        mender_device.ssh_is_opened()
        client_service_name = mender_device.get_client_service_name()
        mender_device.run(
            'journalctl -u %s | grep "authentication request rejected server error message: Unauthorized"'
            % client_service_name,
            wait=70,
        )

        for _ in range(5):
            time.sleep(5)
            devauth.get_devices(expected_devices=0)  # make sure device not seen

        # setting the correct token makes the client visible to the backend
        mender_device.run(
            "sed -i 's/%s/%s/g' /etc/mender/mender.conf" % (wrong_token, token)
        )
        mender_device.run("systemctl restart %s" % client_service_name)

        devauth.get_devices(expected_devices=1)

    def test_multi_tenancy_deployment(
        self, enterprise_no_client, valid_image_with_mender_conf
    ):
        """Simply make sure we are able to run the multi tenancy setup and
        bootstrap 2 different devices to different tenants"""

        auth.reset_auth_token()

        uuidv4 = str(uuid.uuid4())
        users = [
            {
                "email": "foo2-%s@example.com" % uuidv4,
                "password": "hunter2hunter2",
                "username": "test.mender.io-" + uuidv4 + "-foo2",
                "container": "mender-client-deployment-1",
            },
            {
                "email": "bar2-%s@example.com" % uuidv4,
                "password": "hunter2hunter2",
                "username": "test.mender.io-" + uuidv4 + "-bar2",
                "container": "mender-client-deployment-2",
            },
        ]

        for user in users:
            auth.new_tenant(user["username"], user["email"], user["password"])
            t = auth.current_tenant["tenant_token"]
            mender_device = new_tenant_client(
                enterprise_no_client, user["container"], t
            )
            devauth.accept_devices(1)
            assert len(inv.get_devices()) == 1

            # By default the valid_image has a tenant_token=dummy in the mender.conf
            # Therefore, replace the 'mender.conf' in the image with the one from the
            # currently running image, which has a valid 'mender.conf'.
            mender_conf = mender_device.run("cat /etc/mender/mender.conf")
            logger.info(
                "Injecting the mender.conf into the update image:\n{conf}\n".format(
                    conf=mender_conf
                )
            )
            update_image_name = valid_image_with_mender_conf(mender_conf)

            host_ip = enterprise_no_client.get_virtual_network_host_ip()
            update_image(
                mender_device, host_ip, install_image=update_image_name,
            )
