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

import os
import json
import re
import shutil
import tempfile
import time

import pytest
from fabric.api import *

from .. import conftest
from ..common import *
from ..common_setup import standard_setup_one_client_bootstrapped
from .common_update import common_update_procedure, update_image_failed
from ..helpers import Helpers
from ..MenderAPI import deploy
from .mendertesting import MenderTesting

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
    def test_update_image_breaks_networking(self, standard_setup_one_client_bootstrapped, install_image="core-image-full-cmdline-%s-broken-network.ext4" % conftest.machine_name):
        """
            Install an image without systemd-networkd binary existing.
            The network will not function, mender will not be able to send any logs.

            The expected status is the update will rollback, and be considered a failure
        """

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_update_image_breaks_networking,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients,
                    install_image=install_image)
            return

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(install_image)
            reboot.verify_reboot_performed() # since the network is broken, two reboots will be performed, and the last one will be detected
            deploy.check_expected_statistics(deployment_id, "failure", len(mender_clients))

    @MenderTesting.slow
    def test_deployed_during_network_outage(self, standard_setup_one_client_bootstrapped, install_image=conftest.get_valid_image()):
        """
            Install a valid upgrade image while there is no network availability on the device
            Re-establishing the network connectivity results in the upgrade to be triggered.

            Emulate a flaky network connection, and ensure that the deployment still succeeds.
        """

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_deployed_during_network_outage,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients,
                    install_image=install_image)
            return

        Helpers.gateway_connectivity(False)

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot:
            deployment_id, expected_yocto_id = common_update_procedure(install_image, verify_status=False)
            time.sleep(60)

            for i in range(5):
                time.sleep(5)
                Helpers.gateway_connectivity(i % 2 == 0)
            Helpers.gateway_connectivity(True)

            logging.info("Network stabilized")
            reboot.verify_reboot_performed()
            deploy.check_expected_statistics(deployment_id, "success", len(mender_clients))

        assert Helpers.yocto_id_installed_on_machine() == expected_yocto_id

    @MenderTesting.slow
    @pytest.mark.parametrize("test_set", DOWNLOAD_RETRY_TIMEOUT_TEST_SETS)
    def test_image_download_retry_timeout(self, standard_setup_one_client_bootstrapped, test_set, install_image=conftest.get_valid_image()):
        """
            Install an update, and block storage connection when we detect it's
            being copied over to the inactive parition.

            The test should result in a successful download retry.
        """

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_image_download_retry_timeout,
                    standard_setup_one_client_bootstrapped,
                    test_set,
                    hosts=mender_clients,
                    install_image=install_image)
            return

        # make tcp timeout quicker, none persistent changes
        run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_time")
        run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_intvl")
        run("echo 3 > /proc/sys/net/ipv4/tcp_syn_retries")

        # to speed up timeouting client connection
        run("echo 1 > /proc/sys/net/ipv4/tcp_keepalive_probes")

        inactive_part = Helpers.get_passive_partition()

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot:
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
            deploy.check_expected_status("finished", deployment_id)

            assert Helpers.get_active_partition() == inactive_part
            assert Helpers.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()

    @MenderTesting.slow
    def test_image_download_retry_hosts_broken(self, standard_setup_one_client_bootstrapped, install_image=conftest.get_valid_image()):
        """
            Block storage host (minio) by modifying the hosts file.
        """

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_image_download_retry_hosts_broken,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients,
                    install_image=install_image)
            return

        inactive_part = Helpers.get_passive_partition()

        run("echo '1.1.1.1 s3.docker.mender.io' >> /etc/hosts")  # break s3 connectivity before triggering deployment

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot:
            deployment_id, new_yocto_id = common_update_procedure(install_image)

            self.wait_for_download_retry_attempts("update fetch failed")
            run("sed -i.bak '/1.1.1.1/d' /etc/hosts")

            reboot.verify_reboot_performed()
            deploy.check_expected_status("finished", deployment_id)

            assert Helpers.get_active_partition() == inactive_part
            assert Helpers.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()


    def test_rootfs_conf_missing_from_new_update(self, standard_setup_one_client_bootstrapped):
        """Test that the client is able to reboot to roll back if module or rootfs
        config is missing from the new partition. This only works for cases where a
        reboot restores the state."""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_rootfs_conf_missing_from_new_update,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients)
            return

        with settings(warn_only=True):
            output = run("test -e /data/mender/mender.conf")
            if output.return_code != 0:
                pytest.skip("Needs split mender.conf configuration to run this test")

        tmpdir = tempfile.mkdtemp()
        try:
            orig_image = conftest.get_valid_image()
            image_name = os.path.join(tmpdir, os.path.basename(orig_image))
            shutil.copyfile(orig_image, image_name)

            # With the persistent mender.conf in /data, and the transient
            # mender.conf in /etc, we can simply delete the former (rootfs
            # config) to break the config, and add it back into the transient
            # one to keep the config valid for the existing artifact (but not
            # the new one).
            output = run("cat /data/mender/mender.conf")
            persistent_conf = json.loads(output)
            run("rm /data/mender/mender.conf")

            output = run("cat /etc/mender/mender.conf")
            conf = json.loads(output)

            conf["RootfsPartA"] = persistent_conf["RootfsPartA"]
            conf["RootfsPartB"] = persistent_conf["RootfsPartB"]

            mender_conf = os.path.join(tmpdir, "mender.conf")
            with open(mender_conf, "w") as fd:
                json.dump(conf, fd)
            put(os.path.basename(mender_conf), local_path=os.path.dirname(mender_conf), remote_path="/etc/mender")

            host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
            update_image_failed(host_ip, install_image=image_name,
                                expected_log_message="Unable to roll back with a stub module, but will try to reboot to restore state")

        finally:
            shutil.rmtree(tmpdir)
