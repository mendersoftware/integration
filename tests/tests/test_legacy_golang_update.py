# Copyright 2023 Northern.tech AS
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

from ..common_setup import (
    setup_with_legacy_v3_client,
    enterprise_with_legacy_v3_client,
)
from .common_update import update_image, update_image_failed
from ..MenderAPI import DeviceAuthV2, Deployments, logger
from .mendertesting import MenderTesting


class BaseTestLegacyGolangUpdate(MenderTesting):
    def do_test_migrate_from_legacy_mender_v3_success(
        self, env, valid_image,
    ):
        """
        Start a legacy client (3.6 bundle, the last golang client) and do two successful updates.
        The first one to validate 3.6 to latest upgrade and the following one to validate that
        the updated device is fully capable.
        """

        mender_device = env.device
        host_ip = env.get_virtual_network_host_ip()
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        update_image(
            mender_device,
            host_ip,
            install_image=valid_image,
            devauth=devauth,
            deploy=deploy,
        )

        update_image(
            mender_device,
            host_ip,
            install_image=valid_image,
            devauth=devauth,
            deploy=deploy,
        )

    def do_test_migrate_from_legacy_mender_v3_failure(
        self, env, valid_image, broken_update_image,
    ):
        """
        Start a legacy client (3.6 bundle, the last golang client) and do one failed update followed
        but a successful one.
        """

        mender_device = env.device
        host_ip = env.get_virtual_network_host_ip()
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        # Note that for the failed update, we still expect the v3 log message. See:
        # https://github.com/mendersoftware/integration/commit/5971901131afbaf14cd4d9545d52f58366967fd5
        update_image_failed(
            env.device,
            env.get_virtual_network_host_ip(),
            expected_log_message="Reboot to the new update failed",
            devauth=devauth,
            deploy=deploy,
        )

        update_image(
            mender_device,
            host_ip,
            install_image=valid_image,
            devauth=devauth,
            deploy=deploy,
        )


class TestLegacyGolangUpdateOpenSource(BaseTestLegacyGolangUpdate):
    def test_migrate_from_legacy_mender_v3_success(
        self, setup_with_legacy_v3_client, valid_image
    ):
        self.do_test_migrate_from_legacy_mender_v3_success(
            setup_with_legacy_v3_client, valid_image
        )

    def test_migrate_from_legacy_mender_v3_failure(
        self, setup_with_legacy_v3_client, valid_image, broken_update_image,
    ):
        self.do_test_migrate_from_legacy_mender_v3_failure(
            setup_with_legacy_v3_client, valid_image, broken_update_image,
        )


class TestLegacyGolangUpdateEnterprise(BaseTestLegacyGolangUpdate):
    def test_migrate_from_legacy_mender_v3_success(
        self, enterprise_with_legacy_v3_client, valid_image_with_mender_conf
    ):
        mender_conf = enterprise_with_legacy_v3_client.device.run(
            "cat /etc/mender/mender.conf"
        )
        self.do_test_migrate_from_legacy_mender_v3_success(
            enterprise_with_legacy_v3_client, valid_image_with_mender_conf(mender_conf)
        )

    def test_migrate_from_legacy_mender_v3_failure(
        self,
        enterprise_with_legacy_v3_client,
        valid_image_with_mender_conf,
        broken_update_image,
    ):
        mender_conf = enterprise_with_legacy_v3_client.device.run(
            "cat /etc/mender/mender.conf"
        )
        self.do_test_migrate_from_legacy_mender_v3_failure(
            enterprise_with_legacy_v3_client,
            valid_image_with_mender_conf(mender_conf),
            broken_update_image,
        )
