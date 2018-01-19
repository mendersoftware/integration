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

from fabric.api import *
import pytest
import re
import time
from common import *
from common_setup import *
from helpers import Helpers
from MenderAPI import adm, deploy, image, logger
from common_update import common_update_procedure
from mendertesting import MenderTesting

DOWNLOAD_RETRY_TIMEOUT_TEST_SETS = [
    {
        "blockAfterStart": False,
        "logMessageToLookFor": "update fetch failed:",
    },
    {
        "blockAfterStart": True,
        "logMessageToLookFor": "Download connection broken:",
    },
]

@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestFaultTolerance(MenderTesting):

    def wait_for_download_retry_attempts(self, search_string):
        """ Block until logs contain messages related to failed downlaod attempts """

        timeout_time = int(time.time()) + (60 * 10)

        while int(time.time()) < timeout_time:
            with quiet():
                output = run("journalctl -u mender -l --no-pager | grep 'msg=\".*%s' | wc -l"
                             % re.escape(search_string))
                time.sleep(2)
                if int(output) >= 2:  # check that some retries have occured
                    logging.info("Looks like the download was retried 2 times, restoring download functionality")
                    break

        if timeout_time <= int(time.time()):
            pytest.fail("timed out waiting for download retries")

        # make sure that retries happen after 2 minutes have passed
        assert timeout_time - int(time.time()) >= 2 * 60, "Ooops, looks like the retry happend within less than 5 minutes"
        logging.info("Waiting for system to finish download")

    @MenderTesting.slow
    def test_update_image_breaks_networking(self, install_image="core-image-full-cmdline-vexpress-qemu-broken-network.ext4"):
        """
            Install an image without systemd-networkd binary existing.
            The network will not function, mender will not be able to send any logs.

            The expected status is the update will rollback, and be considered a failure
        """
        if not env.host_string:
            execute(self.test_update_image_breaks_networking,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        with Helpers.RebootDetector() as reboot:
            deployment_id, _ = common_update_procedure(install_image)
            reboot.verify_reboot_performed() # since the network is broken, two reboots will be performed, and the last one will be detected
            deploy.check_expected_statistics(deployment_id, "failure", len(get_mender_clients()))

    @MenderTesting.fast
    def test_update_image_recovery(self, install_image=conftest.get_valid_image()):
        """
            Install an update, and reboot the system when we detect it's being copied over to the inactive parition.

            The test should result in a failure.
        """
        if not env.host_string:
            execute(self.test_update_image_recovery,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        installed_yocto_id = Helpers.yocto_id_installed_on_machine()

        inactive_part = Helpers.get_passive_partition()
        with Helpers.RebootDetector() as reboot:
            deployment_id, _ = common_update_procedure(install_image)
            active_part = Helpers.get_active_partition()

            for i in range(60):
                time.sleep(0.5)
                with quiet():
                    # make sure we are writing to the inactive partition
                    output = run("fuser -mv %s" % (inactive_part))
                if output.return_code == 0:
                    run("killall -s 9 mender")
                    with settings(warn_only=True):
                        run("( sleep 3 ; reboot ) 2>/dev/null >/dev/null &")
                    break

            logging.info("Waiting for system to finish reboot")
            reboot.verify_reboot_performed()
            assert Helpers.get_active_partition() == active_part
            deploy.check_expected_statistics(deployment_id, "failure", len(get_mender_clients()))
            reboot.verify_reboot_not_performed()

        assert Helpers.yocto_id_installed_on_machine() == installed_yocto_id

    @MenderTesting.slow
    def test_deployed_during_network_outage(self, install_image=conftest.get_valid_image()):
        """
            Install a valid upgrade image while there is no network availability on the device
            Re-establishing the network connectivity results in the upgrade to be triggered.

            Emulate a flaky network connection, and ensure that the deployment still succeeds.
        """
        if not env.host_string:
            execute(self.test_deployed_during_network_outage,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        Helpers.gateway_connectivity(False)
        with Helpers.RebootDetector() as reboot:
            deployment_id, expected_yocto_id = common_update_procedure(install_image, verify_status=False)
            time.sleep(60)

            for i in range(5):
                time.sleep(5)
                Helpers.gateway_connectivity(i % 2 == 0)
            Helpers.gateway_connectivity(True)

            logging.info("Network stabilized")
            reboot.verify_reboot_performed()
            deploy.check_expected_statistics(deployment_id, "success", len(get_mender_clients()))

        assert Helpers.yocto_id_installed_on_machine() == expected_yocto_id

    @MenderTesting.slow
    @pytest.mark.parametrize("test_set", DOWNLOAD_RETRY_TIMEOUT_TEST_SETS)
    def test_image_download_retry_timeout(self, test_set, install_image=conftest.get_valid_image()):
        """
            Install an update, and block storage connection when we detect it's
            being copied over to the inactive parition.

            The test should result in a successful download retry.
        """
        if not env.host_string:
            execute(self.test_image_download_retry_timeout,
                    test_set,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        # make tcp timeout quicker, none persistent changes
        run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_time")
        run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_intvl")
        run("echo 3 > /proc/sys/net/ipv4/tcp_syn_retries")

        # to speed up timeouting client connection
        run("echo 1 > /proc/sys/net/ipv4/tcp_keepalive_probes")

        inactive_part = Helpers.get_passive_partition()

        with Helpers.RebootDetector() as reboot:
            if test_set['blockAfterStart']:
                # Block after we start the download.
                deployment_id, new_yocto_id = common_update_procedure(install_image)
                for _ in range(60):
                    time.sleep(0.5)
                    with quiet():
                        # make sure we are writing to the inactive partition
                        output = run("fuser -mv %s" % (inactive_part))
                    if output.return_code == 0:
                        break
                else:
                    pytest.fail("Download never started?")

            # use iptables to block traffic to storage
            Helpers.gateway_connectivity(False, hosts=["s3.docker.mender.io"])  # disable connectivity

            if not test_set['blockAfterStart']:
                # Block before we start the download.
                deployment_id, new_yocto_id = common_update_procedure(install_image)

            # re-enable connectivity after 2 retries
            self.wait_for_download_retry_attempts(test_set['logMessageToLookFor'])
            Helpers.gateway_connectivity(True, hosts=["s3.docker.mender.io"])  # re-enable connectivity

            reboot.verify_reboot_performed()
            assert Helpers.get_active_partition() == inactive_part
            assert Helpers.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()

    @MenderTesting.nightly
    def test_image_download_retry_hosts_broken(self, install_image=conftest.get_valid_image()):
        """
            Block storage host (minio) by modifying the hosts file.
        """

        if not env.host_string:
            execute(self.test_image_download_retry_hosts_broken,
                    hosts=get_mender_clients(),
                    install_image=install_image)
            return

        inactive_part = Helpers.get_passive_partition()

        run("echo '1.1.1.1 s3.docker.mender.io' >> /etc/hosts")  # break s3 connectivity before triggering deployment
        with Helpers.RebootDetector() as reboot:
            deployment_id, new_yocto_id = common_update_procedure(install_image)

            self.wait_for_download_retry_attempts()
            run("sed -i.bak '/1.1.1.1/d' /etc/hosts")

            reboot.verify_reboot_performed()
            assert Helpers.get_active_partition() == inactive_part
            assert Helpers.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()
