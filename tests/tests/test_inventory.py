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

import json
import tempfile
import time

import pytest

from .. import conftest
from ..common_setup import (
    standard_setup_one_client_bootstrapped,
    enterprise_one_client_bootstrapped,
)
from ..MenderAPI import DeviceAuthV2, Deployments, Inventory, logger
from .common_artifact import get_script_artifact
from .mendertesting import MenderTesting


def make_script_artifact(artifact_name, device_type, output_path, extra_args):
    script = b"""\
#!/bin/bash
exit 0
"""
    return get_script_artifact(
        script, artifact_name, device_type, output_path, extra_args
    )


class BaseTestInventory(MenderTesting):
    def do_test_inventory(self, env):
        """
        Test that device reports inventory after having bootstrapped and performed
        an application update using a dummy script artifact.
        """
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        inv = Inventory(env.auth)

        def deploy_simple_artifact(artifact_name, extra_args):
            # create a simple artifact (script) which doesn't do anything
            with tempfile.NamedTemporaryFile() as tf:
                artifact = make_script_artifact(
                    artifact_name,
                    conftest.machine_name,
                    tf.name,
                    extra_args=extra_args,
                )
                deploy.upload_image(artifact)

            # deploy the artifact above
            device_ids = [device["id"] for device in devauth.get_devices()]
            deployment_id = deploy.trigger_deployment(
                artifact_name, artifact_name=artifact_name, devices=device_ids,
            )

            # now just wait for the update to succeed
            deploy.check_expected_statistics(deployment_id, "success", 1)
            deploy.check_expected_status("finished", deployment_id)

        deploy_simple_artifact(
            "simple-artifact-1",
            "--software-name swname --software-version v1"
            + " --provides rootfs-image.swname.custom_field:value"
            + " --provides rootfs-image.custom_field:value",
        )
        deploy_simple_artifact(
            "simple-artifact-2", "--software-name swname --software-version v2"
        )

        # verify the inventory
        latest_exception = None
        for _ in range(10):
            try:
                inv_json = inv.get_devices()
                assert len(inv_json) > 0

                auth_json = devauth.get_devices()
                auth_ids = [device["id"] for device in auth_json]

                for device in inv_json:
                    try:
                        # Check that authentication and inventory agree.
                        assert device["id"] in auth_ids
                        attrs = device["attributes"]

                        # Extract name and value only, to make tests more resilient
                        attrs = [
                            {"name": x.get("name"), "value": x.get("value")}
                            for x in attrs
                        ]

                        # Check individual attributes.
                        network_interfaces = [
                            elem
                            for elem in attrs
                            if elem["name"] == "network_interfaces"
                        ]
                        assert len(network_interfaces) == 1
                        network_interfaces = network_interfaces[0]
                        if type(network_interfaces["value"]) is str:
                            assert any(
                                network_interfaces["value"] == iface
                                for iface in ["eth0", "enp0s3"]
                            )
                        else:
                            assert any(
                                iface in network_interfaces["value"]
                                for iface in ["eth0", "enp0s3"]
                            )
                        assert (
                            json.loads(
                                '{"name": "hostname", "value": "%s"}'
                                % conftest.machine_name
                            )
                            in attrs
                        )
                        assert (
                            json.loads(
                                '{"name": "device_type", "value": "%s"}'
                                % conftest.machine_name
                            )
                            in attrs
                        )
                        # Should be in inventory because it comes with artifact.
                        assert (
                            json.loads(
                                '{"name": "rootfs-image.swname.version", "value": "v2"}'
                            )
                            in attrs
                        )
                        # Should not be in inventory because the default is to
                        # clear inventory attributes in the same namespace.
                        assert (
                            json.loads(
                                '{"name": "rootfs-image.swname.custom_field", "value": "value"}'
                            )
                            not in attrs
                        )
                        # Should be in inventory because the default is to keep
                        # inventory attributes in different namespaces.
                        assert (
                            json.loads(
                                '{"name": "rootfs-image.custom_field", "value": "value"}'
                            )
                            in attrs
                        )

                        if conftest.machine_name == "qemux86-64":
                            bootloader_integration = "uefi_grub"
                        elif conftest.machine_name == "vexpress-qemu":
                            bootloader_integration = "uboot"
                        else:
                            pytest.fail(
                                "Unknown machine_name. Please add an expected bootloader_integration for this machine_name"
                            )
                        assert (
                            json.loads(
                                '{"name": "mender_bootloader_integration", "value": "%s"}'
                                % bootloader_integration
                            )
                            in attrs
                        )

                        # Check that all known keys are present.
                        keys = [str(attr["name"]) for attr in attrs]
                        expected_keys = [
                            "hostname",
                            "network_interfaces",
                            "cpu_model",
                            "mem_total_kB",
                            "device_type",
                            [
                                "ipv4_enp0s3",
                                "ipv6_enp0s3",
                                "ipv4_eth0",
                            ],  # Multiple possibilities
                            ["mac_enp0s3", "mac_eth0"],
                            "mender_client_version",
                            "artifact_name",
                            "kernel",
                            "os",
                        ]
                        for key in expected_keys:
                            if type(key) is list:
                                assert any([subkey in keys for subkey in key])
                            else:
                                assert key in keys
                    except:
                        logger.info("Exception caught, 'device' json: %s" % device)
                        raise
            except Exception as e:
                latest_exception = e
                time.sleep(5)
            else:
                return
        raise latest_exception

    def do_test_inventory_update_after_successful_deployment(self, env):
        """
        Test that device reports inventory after a new successful deployment,
        and not simply after a boot.
        """

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        inv = Inventory(env.auth)

        # Give the image a larger wait interval.
        sedcmd = "sed -i.bak 's/%s/%s/' /etc/mender/mender.conf" % (
            r"\(InventoryPollInter.*:\)\( *[0-9]*\)",
            "\\1 300",
        )
        mender_device.run(sedcmd)
        mender_device.run("systemctl restart mender-updated")

        # Get the inventory sent after first boot
        initial_inv_json = inv.get_devices()
        assert len(initial_inv_json) > 0
        assert "rootfs-image.swname.version" not in str(
            initial_inv_json
        ), "The initial inventory is not clean"

        def deploy_simple_artifact(artifact_name, extra_args):
            # create a simple artifact (script) which doesn't do anything
            with tempfile.NamedTemporaryFile() as tf:
                artifact = make_script_artifact(
                    artifact_name,
                    conftest.machine_name,
                    tf.name,
                    extra_args=extra_args,
                )
                deploy.upload_image(artifact)

            # deploy the artifact above
            device_ids = [device["id"] for device in devauth.get_devices()]
            deployment_id = deploy.trigger_deployment(
                artifact_name, artifact_name=artifact_name, devices=device_ids,
            )

            # now just wait for the update to succeed
            deploy.check_expected_statistics(deployment_id, "success", 1)
            deploy.check_expected_status("finished", deployment_id)

        deploy_simple_artifact(
            "simple-artifact-1",
            "--software-name swname --software-version v1"
            + " --provides rootfs-image.swname.custom_field:value",
        )

        # Give the client a little bit of time to do the update
        time.sleep(15)

        post_deployment_inv_json = inv.get_devices()
        assert len(post_deployment_inv_json) > 0
        assert "rootfs-image.swname.version" in str(
            post_deployment_inv_json
        ), "The device has not updated the inventory after the udpate"


class TestInventoryOpenSource(BaseTestInventory):
    @MenderTesting.fast
    def test_inventory(self, standard_setup_one_client_bootstrapped):
        self.do_test_inventory(standard_setup_one_client_bootstrapped)

    @MenderTesting.fast
    def test_inventory_update_after_successful_deployment(
        self, standard_setup_one_client_bootstrapped
    ):
        self.do_test_inventory_update_after_successful_deployment(
            standard_setup_one_client_bootstrapped
        )


class TestInventoryEnterprise(BaseTestInventory):
    @MenderTesting.fast
    def test_inventory(self, enterprise_one_client_bootstrapped):
        self.do_test_inventory(enterprise_one_client_bootstrapped)

    @MenderTesting.fast
    def test_inventory_update_after_successful_deployment(
        self, enterprise_one_client_bootstrapped
    ):
        self.do_test_inventory_update_after_successful_deployment(
            enterprise_one_client_bootstrapped
        )
