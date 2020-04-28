# Copyright 2020 Northern.tech AS
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

import os
import json
import re
import shutil
import tempfile
import time

import pytest

from .. import conftest
from ..common_setup import standard_setup_one_client_bootstrapped
from .common_update import common_update_procedure, update_image_failed
from ..MenderAPI import deploy, logger
from .mendertesting import MenderTesting

DOWNLOAD_RETRY_TIMEOUT_TEST_SETS = [
    # We use "pdate" to be able to match "Update" (2.4.x) and "update" (2.3.x and earlier)
    {"blockAfterStart": False, "logMessageToLookFor": "pdate fetch failed:",},
    {"blockAfterStart": True, "logMessageToLookFor": "Download connection broken:",},
]


class TestFaultTolerance(MenderTesting):
    @staticmethod
    def manipulate_network_connectivity(
        device,
        accessible,
        hosts=["mender-artifact-storage.localhost", "mender-api-gateway"],
    ):
        try:
            for h in hosts:
                gateway_ip = device.run(
                    r"nslookup %s | grep -A1 'Name:' | egrep '^Address( 1)?:'  | grep -oE '((1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])\.){3}(1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])'"
                    % (h),
                    hide=True,
                ).strip()

                if accessible:
                    logger.info("Allowing network communication to %s" % h)
                    device.run(
                        "iptables -D INPUT -s %s -j DROP" % (gateway_ip), hide=True
                    )
                    device.run(
                        "iptables -D OUTPUT -s %s -j DROP" % (gateway_ip), hide=True
                    )
                else:
                    logger.info("Disallowing network communication to %s" % h)
                    device.run(
                        "iptables -I INPUT 1 -s %s -j DROP" % gateway_ip, hide=True
                    )
                    device.run(
                        "iptables -I OUTPUT 1 -s %s -j DROP" % gateway_ip, hide=True
                    )
        except Exception as e:
            logger.info("Exception while messing with network connectivity: %s", str(e))

    @staticmethod
    def wait_for_download_retry_attempts(device, search_string):
        """ Block until logs contain messages related to failed downlaod attempts """

        timeout_time = int(time.time()) + (60 * 10)

        while int(time.time()) < timeout_time:
            output = device.run(
                "journalctl -u %s -l --no-pager | grep 'msg=\".*%s' | wc -l"
                % (device.get_client_service_name(), re.escape(search_string)),
                hide=True,
            )
            time.sleep(2)
            if int(output) >= 2:  # check that some retries have occured
                logger.info(
                    "Looks like the download was retried 2 times, restoring download functionality"
                )
                break

        if timeout_time <= int(time.time()):
            pytest.fail("timed out waiting for download retries")

        # make sure that retries happen after 2 minutes have passed
        assert (
            timeout_time - int(time.time()) >= 2 * 60
        ), "Ooops, looks like the retry happend within less than 5 minutes"
        logger.info("Waiting for system to finish download")

    @MenderTesting.slow
    def test_update_image_breaks_networking(
        self,
        standard_setup_one_client_bootstrapped,
        install_image="core-image-full-cmdline-%s-broken-network.ext4"
        % conftest.machine_name,
    ):
        """
            Install an image without systemd-networkd binary existing.
            The network will not function, mender will not be able to send any logs.

            The expected status is the update will rollback, and be considered a failure
        """

        mender_device = standard_setup_one_client_bootstrapped.device

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(install_image)
            reboot.verify_reboot_performed()  # since the network is broken, two reboots will be performed, and the last one will be detected
            deploy.check_expected_statistics(deployment_id, "failure", 1)

    @MenderTesting.slow
    def test_deployed_during_network_outage(
        self, standard_setup_one_client_bootstrapped, valid_image,
    ):
        """
            Install a valid upgrade image while there is no network availability on the device
            Re-establishing the network connectivity results in the upgrade to be triggered.

            Emulate a flaky network connection, and ensure that the deployment still succeeds.
        """

        mender_device = standard_setup_one_client_bootstrapped.device

        TestFaultTolerance.manipulate_network_connectivity(mender_device, False)

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, expected_yocto_id = common_update_procedure(
                valid_image, verify_status=False
            )
            time.sleep(60)

            for i in range(5):
                time.sleep(5)
                TestFaultTolerance.manipulate_network_connectivity(
                    mender_device, i % 2 == 0
                )
            TestFaultTolerance.manipulate_network_connectivity(mender_device, True)

            logger.info("Network stabilized")
            reboot.verify_reboot_performed()
            deploy.check_expected_statistics(deployment_id, "success", 1)

        assert mender_device.yocto_id_installed_on_machine() == expected_yocto_id

    @MenderTesting.slow
    @pytest.mark.parametrize("test_set", DOWNLOAD_RETRY_TIMEOUT_TEST_SETS)
    def test_image_download_retry_timeout(
        self, standard_setup_one_client_bootstrapped, test_set, valid_image,
    ):
        """
            Install an update, and block storage connection when we detect it's
            being copied over to the inactive parition.

            The test should result in a successful download retry.
        """

        mender_device = standard_setup_one_client_bootstrapped.device

        # make tcp timeout quicker, none persistent changes
        mender_device.run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_time")
        mender_device.run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_intvl")
        mender_device.run("echo 3 > /proc/sys/net/ipv4/tcp_syn_retries")

        # to speed up timeouting client connection
        mender_device.run("echo 1 > /proc/sys/net/ipv4/tcp_keepalive_probes")

        inactive_part = mender_device.get_passive_partition()

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            if test_set["blockAfterStart"]:
                # Block after we start the download.
                deployment_id, new_yocto_id = common_update_procedure(valid_image)
                mender_device.run("fuser -mv %s" % (inactive_part))

            # use iptables to block traffic to storage
            TestFaultTolerance.manipulate_network_connectivity(
                mender_device, False, hosts=["s3.docker.mender.io"]
            )  # disable connectivity

            if not test_set["blockAfterStart"]:
                # Block before we start the download.
                deployment_id, new_yocto_id = common_update_procedure(valid_image)

            # re-enable connectivity after 2 retries
            TestFaultTolerance.wait_for_download_retry_attempts(
                mender_device, test_set["logMessageToLookFor"]
            )
            TestFaultTolerance.manipulate_network_connectivity(
                mender_device, True, hosts=["s3.docker.mender.io"]
            )  # re-enable connectivity

            reboot.verify_reboot_performed()
            deploy.check_expected_status("finished", deployment_id)

            assert mender_device.get_active_partition() == inactive_part
            assert mender_device.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()

    @MenderTesting.slow
    def test_image_download_retry_hosts_broken(
        self, standard_setup_one_client_bootstrapped, valid_image,
    ):
        """
            Block storage host (minio) by modifying the hosts file.
        """

        mender_device = standard_setup_one_client_bootstrapped.device

        inactive_part = mender_device.get_passive_partition()

        mender_device.run(
            "echo '1.1.1.1 s3.docker.mender.io' >> /etc/hosts"
        )  # break s3 connectivity before triggering deployment

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, new_yocto_id = common_update_procedure(valid_image)

            # We use "pdate" to be able to match "Update" (2.4.x) and "update" (2.3.x and earlier)
            TestFaultTolerance.wait_for_download_retry_attempts(
                mender_device, "pdate fetch failed",
            )
            mender_device.run("sed -i.bak '/1.1.1.1/d' /etc/hosts")

            reboot.verify_reboot_performed()
            deploy.check_expected_status("finished", deployment_id)

            assert mender_device.get_active_partition() == inactive_part
            assert mender_device.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()

    def test_rootfs_conf_missing_from_new_update(
        self, standard_setup_one_client_bootstrapped, valid_image
    ):
        """Test that the client is able to reboot to roll back if module or rootfs
        config is missing from the new partition. This only works for cases where a
        reboot restores the state."""

        mender_device = standard_setup_one_client_bootstrapped.device

        output = mender_device.run(
            "test -e /data/mender/mender.conf && echo true", hide=True
        )
        if output.rstrip() != "true":
            pytest.skip("Needs split mender.conf configuration to run this test")

        tmpdir = tempfile.mkdtemp()
        try:
            # With the persistent mender.conf in /data, and the transient
            # mender.conf in /etc, we can simply delete the former (rootfs
            # config) to break the config, and add it back into the transient
            # one to keep the config valid for the existing artifact (but not
            # the new one).
            output = mender_device.run("cat /data/mender/mender.conf")
            persistent_conf = json.loads(output)
            mender_device.run("rm /data/mender/mender.conf")

            output = mender_device.run("cat /etc/mender/mender.conf")
            conf = json.loads(output)

            conf["RootfsPartA"] = persistent_conf["RootfsPartA"]
            conf["RootfsPartB"] = persistent_conf["RootfsPartB"]

            mender_conf = os.path.join(tmpdir, "mender.conf")
            with open(mender_conf, "w") as fd:
                json.dump(conf, fd)
            mender_device.put(
                os.path.basename(mender_conf),
                local_path=os.path.dirname(mender_conf),
                remote_path="/etc/mender",
            )

            host_ip = (
                standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
            )
            update_image_failed(
                mender_device,
                host_ip,
                expected_log_message="Unable to roll back with a stub module, but will try to reboot to restore state",
                install_image=valid_image,
            )

        finally:
            shutil.rmtree(tmpdir)
