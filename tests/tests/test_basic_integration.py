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

import shutil
import os
import time

import pytest

from ..common_setup import (
    standard_setup_one_rofs_client_bootstrapped,
    standard_setup_with_short_lived_token,
    setup_failover,
    standard_setup_one_client_bootstrapped,
    enterprise_one_client_bootstrapped,
    enterprise_one_rofs_client_bootstrapped,
    enterprise_with_short_lived_token,
)
from .common_update import update_image, update_image_failed
from ..MenderAPI import (
    image,
    logger,
    devauth,
    DeviceAuthV2,
    Deployments,
    Inventory,
    get_container_manager,
)
from .mendertesting import MenderTesting
from ..helpers import Helpers


class DeviceAuthFailover(DeviceAuthV2):
    def __init__(self, devauth):
        self.auth = devauth.auth

    def get_devauth_base_path(self):
        return "https://%s/api/management/v2/devauth/" % (
            get_container_manager().get_ip_of_service("mender-api-gateway-2")[0]
        )


class BaseTestBasicIntegration(MenderTesting):
    def do_test_double_update_rofs(self, env, valid_image_rofs_with_mender_conf):
        """Upgrade a device with two consecutive R/O images using different compression algorithms"""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        mender_conf = mender_device.run("cat /etc/mender/mender.conf")
        valid_image_rofs = valid_image_rofs_with_mender_conf(mender_conf)
        if valid_image_rofs is None:
            pytest.skip(
                "Thud branch and older from Yocto does not have R/O rootfs support"
            )

        # Verify that partition is read-only as expected
        mender_device.run("mount | fgrep 'on / ' | fgrep '(ro,'")

        host_ip = env.get_virtual_network_host_ip()
        update_image(
            mender_device,
            host_ip,
            install_image=valid_image_rofs,
            compression_type="gzip",
            devauth=devauth,
            deploy=deploy,
        )
        mender_device.run("mount | fgrep 'on / ' | fgrep '(ro,'")

        update_image(
            mender_device,
            host_ip,
            install_image=valid_image_rofs,
            compression_type="lzma",
            devauth=devauth,
            deploy=deploy,
        )
        mender_device.run("mount | fgrep 'on / ' | fgrep '(ro,'")

    def do_test_update_jwt_expired(self, env, valid_image_with_mender_conf):
        """Update a device with a short lived JWT token"""
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        mender_conf = env.device.run("cat /etc/mender/mender.conf")
        update_image(
            env.device,
            env.get_virtual_network_host_ip(),
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
        )

    def do_test_failed_updated_and_valid_update(
        self, env, valid_image_with_mender_conf
    ):
        """Upload a device with a broken image, followed by a valid image"""
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        mender_device = env.device
        host_ip = env.get_virtual_network_host_ip()

        update_image_failed(mender_device, host_ip, devauth=devauth, deploy=deploy)
        mender_conf = mender_device.run("cat /etc/mender/mender.conf")
        update_image(
            mender_device,
            host_ip,
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
        )

    def do_test_update_no_compression(self, env, valid_image_with_mender_conf):
        """Uploads an uncompressed artifact, and runs the whole update process."""
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        mender_device = env.device
        mender_conf = mender_device.run("cat /etc/mender/mender.conf")

        update_image(
            env.device,
            env.get_virtual_network_host_ip(),
            install_image=valid_image_with_mender_conf(mender_conf),
            compression_type="none",
            devauth=devauth,
            deploy=deploy,
        )

    def do_test_update_zstd_compression(self, env, valid_image_with_mender_conf):
        """Uploads a zstd-compressed artifact, and runs the whole update process."""
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        mender_device = env.device
        mender_conf = mender_device.run("cat /etc/mender/mender.conf")

        update_image(
            env.device,
            env.get_virtual_network_host_ip(),
            install_image=valid_image_with_mender_conf(mender_conf),
            compression_type="zstd_best",
            devauth=devauth,
            deploy=deploy,
        )

    def do_test_forced_update_check_from_client(
        self, env, valid_image_with_mender_conf
    ):
        """Upload a device with a broken image, followed by a valid image"""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        # Give the image a really large wait interval.
        sedcmd = "sed -i.bak 's/%s/%s/' /etc/mender/mender.conf" % (
            r"\(.*PollInter.*:\)\( *[0-9]*\)",
            "\\1 1800",
        )
        mender_device.run(sedcmd)
        client_service_name = mender_device.get_client_service_name()
        mender_device.run("systemctl restart %s" % client_service_name)

        def deployment_callback():
            logger.info("Running pre deployment callback function")
            wait_count = 0
            # Match the log template six times to make sure the client is truly sleeping.
            catcmd = "journalctl -u %s --output=cat" % client_service_name
            template = mender_device.run(catcmd)
            while True:
                logger.info("sleeping...")
                logger.info("wait_count: %d" % wait_count)
                time.sleep(10)
                out = mender_device.run(catcmd)
                if out == template:
                    wait_count += 1
                    # Only return if the client has been idling in check-wait for a minute.
                    if wait_count == 6:
                        return
                    continue
                # Update the matching template
                template = mender_device.run(catcmd)
                wait_count = 0

        def deployment_triggered_callback():
            mender_device.run("mender-update check-update")
            logger.info("mender client has forced an update check")

        mender_conf = mender_device.run("cat /etc/mender/mender.conf")
        update_image(
            mender_device,
            env.get_virtual_network_host_ip(),
            install_image=valid_image_with_mender_conf(mender_conf),
            pre_deployment_callback=deployment_callback,
            deployment_triggered_callback=deployment_triggered_callback,
            devauth=devauth,
            deploy=deploy,
        )

    def do_test_forced_inventory_update_from_client(self, env):
        """Forces an inventory update from an idling client."""

        mender_device = env.device
        inv = Inventory(env.auth)

        # Give the image a really large wait interval.
        sedcmd = "sed -i.bak 's/%s/%s/' /etc/mender/mender.conf" % (
            r"\(.*PollInter.*:\)\( *[0-9]*\)",
            "\\1 1800",
        )
        mender_device.run(sedcmd)
        client_service_name = mender_device.get_client_service_name()
        mender_device.run("systemctl restart %s" % client_service_name)

        logger.info("Running pre deployment callback function")
        wait_count = 0
        # Match the log template six times to make sure the client is truly sleeping.
        catcmd = "journalctl -u %s --output=cat" % client_service_name
        template = mender_device.run(catcmd)
        while True:
            logger.info("sleeping...")
            logger.info("wait_count: %d" % wait_count)
            time.sleep(10)
            out = mender_device.run(catcmd)
            if out == template:
                wait_count += 1
                # Only return if the client has been idling in check-wait for a minute.
                if wait_count == 6:
                    break
                continue
            # Update the matching template.
            template = mender_device.run(catcmd)
            wait_count = 0

        # Create some new inventory data from an inventory script.
        mender_device.run(
            "cd /usr/share/mender/inventory && echo '#!/bin/sh\necho host=foobar' > mender-inventory-test && chmod +x mender-inventory-test"
        )

        # Now that the client has settled into the wait-state, run the command, and check if it does indeed exit the wait state,
        # and send inventory.
        mender_device.run("mender-update send-inventory")
        logger.info("mender client has forced an inventory update")

        for i in range(10):
            # Check that the updated inventory value is now present.
            invJSON = inv.get_devices()
            for element in invJSON[0]["attributes"]:
                if element["name"] == "host" and element["value"] == "foobar":
                    return
            time.sleep(10)

        pytest.fail("The inventory was not updated")


class TestBasicIntegrationOpenSource(BaseTestBasicIntegration):
    @MenderTesting.fast
    def test_update_failover_server(self, setup_failover, valid_image):
        """
        Client is initially set up against server A, and then receives an update
        containing a multi-server configuration, with server B as primary and A
        secondary. Server B does not, however, expect any clients and will trigger
        "failover" to server A.
        To create the necessary configuration I use a state script to modify the
        /etc/mender/mender.conf
        """

        mender_device = setup_failover.device

        tmp_image = valid_image.split(".")[0] + "-failover-image.ext4"
        try:
            logger.info("Creating failover sample image.")
            shutil.copy(valid_image, tmp_image)
            conf = image.get_mender_conf(tmp_image)

            if conf is None:
                raise SystemExit("Could not retrieve mender.conf")

            conf["Servers"] = [
                {"ServerURL": "https://failover.docker.mender.io"},
                {"ServerURL": conf["ServerURL"]},
            ]
            conf.pop("ServerURL")
            image.replace_mender_conf(tmp_image, conf)

            host_ip = setup_failover.get_virtual_network_host_ip()
            update_image(mender_device, host_ip, install_image=tmp_image)

            # Now try to decommission the device from server A and have it
            # accepted in server B.
            devices = devauth.get_devices_status()
            assert len(devices) == 1
            devauth.decommission(devices[0]["id"])

            # Journalctl has resolution of one second, so wait one second to
            # avoid race conditions when detecting below.
            time.sleep(1)
            date = mender_device.run('date "+%Y-%m-%d %H:%M:%S"').strip()

            devauth_failover = DeviceAuthFailover(devauth)

            devices = devauth_failover.get_devices_status(status="pending")
            assert len(devices) == 1

            devauth_failover.accept_devices(1)
            Helpers.check_log_is_authenticated(mender_device, date)

            # Old server should have no devices now.
            devices = devauth.get_devices_status(status="accepted")
            assert len(devices) == 0

        finally:
            os.remove(tmp_image)

    @MenderTesting.fast
    def test_double_update_rofs(
        self,
        standard_setup_one_rofs_client_bootstrapped,
        valid_image_rofs_with_mender_conf,
    ):
        self.do_test_double_update_rofs(
            standard_setup_one_rofs_client_bootstrapped,
            valid_image_rofs_with_mender_conf,
        )

    @MenderTesting.fast
    def test_update_jwt_expired(
        self, standard_setup_with_short_lived_token, valid_image_with_mender_conf
    ):
        self.do_test_update_jwt_expired(
            standard_setup_with_short_lived_token, valid_image_with_mender_conf
        )

    @MenderTesting.fast
    def test_failed_updated_and_valid_update(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_failed_updated_and_valid_update(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
        )

    def test_update_no_compression(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_update_no_compression(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
        )

    def test_update_zstd_compression(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_update_zstd_compression(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
        )

    def test_forced_update_check_from_client(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_forced_update_check_from_client(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
        )

    @pytest.mark.timeout(1000)
    def test_forced_inventory_update_from_client(
        self, standard_setup_one_client_bootstrapped
    ):
        self.do_test_forced_inventory_update_from_client(
            standard_setup_one_client_bootstrapped
        )


class TestBasicIntegrationEnterprise(BaseTestBasicIntegration):
    @MenderTesting.fast
    def test_double_update_rofs(
        self,
        enterprise_one_rofs_client_bootstrapped,
        valid_image_rofs_with_mender_conf,
    ):
        self.do_test_double_update_rofs(
            enterprise_one_rofs_client_bootstrapped, valid_image_rofs_with_mender_conf,
        )

    @MenderTesting.fast
    def test_update_jwt_expired(
        self, enterprise_with_short_lived_token, valid_image_with_mender_conf
    ):
        self.do_test_update_jwt_expired(
            enterprise_with_short_lived_token, valid_image_with_mender_conf
        )

    @MenderTesting.fast
    def test_failed_updated_and_valid_update(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_failed_updated_and_valid_update(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )

    def test_update_no_compression(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_update_no_compression(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
        )

    def test_update_zstd_compression(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_update_zstd_compression(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
        )

    def test_forced_update_check_from_client(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_forced_update_check_from_client(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )

    @pytest.mark.timeout(1000)
    def test_forced_inventory_update_from_client(
        self, enterprise_one_client_bootstrapped
    ):
        self.do_test_forced_inventory_update_from_client(
            enterprise_one_client_bootstrapped
        )
