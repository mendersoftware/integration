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

from ..common_setup import enterprise_no_client
from ..MenderAPI import auth, devauth, logger, inv
from .common_update import update_image
from .mendertesting import MenderTesting
from mender_testkit.testutils.common import new_tenant_client
from flaky import flaky


# Retry the intermittent "Device never rebooted" infra flake: the QEMU VM
# sometimes does not come back after an update-triggered reboot. A flaky rerun
# tears down the dead VM and boots a fresh one.
@flaky(max_runs=3)
class TestMultiTenancyEnterprise(MenderTesting):
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
                mender_device,
                host_ip,
                install_image=update_image_name,
            )
