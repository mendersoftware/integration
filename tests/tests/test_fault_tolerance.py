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

import json
import os
import pytest
import shutil
import tempfile
import time

from .. import conftest
from ..common_setup import (
    standard_setup_one_client_bootstrapped,
    enterprise_one_client_bootstrapped,
)
from .common_update import common_update_procedure, update_image_failed
from ..MenderAPI import DeviceAuthV2, Deployments, logger
from .mendertesting import MenderTesting


class BasicTestFaultTolerance(MenderTesting):
    def manipulate_network_connectivity(
        self,
        device,
        accessible,
        hosts=["mender-artifact-storage.localhost", "mender-api-gateway"],
    ):
        try:
            for h in hosts:
                if h == "s3.docker.mender.io":
                    self.block_by_domain(device, accessible, h)
                else:
                    self.block_by_ip(device, accessible, h)
        except Exception as e:
            logger.info("Exception while messing with network connectivity: %s", str(e))

    def block_by_ip(self, device, accessible, host):
        """Get IP of host and block by that."""
        gateway_ip = device.run(
            r"nslookup %s | grep -A1 'Name:' | grep -E '^Address( 1)?:'  | grep -oE '((1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])\.){3}(1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])'"
            % (host),
            hide=True,
        ).strip()

        if accessible:
            logger.info("Allowing network communication to %s" % host)
            device.run("iptables -D INPUT -s %s -j DROP" % (gateway_ip), hide=True)
            device.run("iptables -D OUTPUT -s %s -j DROP" % (gateway_ip), hide=True)
        else:
            logger.info("Disallowing network communication to %s" % host)
            device.run("iptables -I INPUT 1 -s %s -j DROP" % gateway_ip, hide=True)
            device.run("iptables -I OUTPUT 1 -s %s -j DROP" % gateway_ip, hide=True)

    def block_by_domain(self, device, accessible, host):
        """Some services shouldn't be blocked by ip, because they share it with other services.
        (example: s3 is the same IP as gateway as a whole).
        Block these by host/domain name instead (using iptables string matching).
        """

        # extra modules for iptables string matching
        device.run("modprobe xt_string")
        device.run("modprobe ts-bm")

        if accessible:
            logger.info("Allowing network communication to %s" % host)
            device.run(
                "iptables -D INPUT -p tcp -m string --algo bm --string %s -j REJECT --reject-with tcp-reset"
                % host
            )

            device.run(
                "iptables -D OUTPUT -p tcp -m string --algo bm --string %s -j REJECT --reject-with tcp-reset"
                % host
            )
        else:
            logger.info("Disallowing network communication to %s" % host)
            device.run(
                "iptables -I INPUT -p tcp -m string --algo bm --string %s -j REJECT --reject-with tcp-reset"
                % host,
                hide=True,
            )
            device.run(
                "iptables -I OUTPUT -p tcp -m string --algo bm --string %s -j REJECT --reject-with tcp-reset"
                % host,
                hide=True,
            )

    def wait_for_download_retry_attempts(
        self, device, search_string, num_retries=2, timeout=10
    ):
        """ Block until logs contain messages related to failed download attempts """

        timeout_time = int(time.time()) + (
            timeout * 90
        )  # 90s per each 60s retry to give time for a connection timeout to occur each time
        start_time = int(time.time())
        num_retries_attempted = 0

        while int(time.time()) < timeout_time:
            output = device.run(
                f'journalctl --unit mender-updated --full --no-pager | grep -E \'name="http_resumer:client" msg=".*{search_string}\' | wc -l',
                hide=True,
            )
            time.sleep(2)
            if int(output) >= num_retries:  # check that some retries have occurred
                logger.info(
                    f"Looks like the download was retried {num_retries} times, restoring download functionality"
                )
                num_retries_attempted = int(output)
                break
            num_retries_attempted = int(output)

        # if num_retries expected is smaller then timeout, we expect success.
        # if it's bigger, then we expect a timeout
        if num_retries < timeout:
            if timeout_time <= int(time.time()):
                pytest.fail("timed out waiting for download retries")
            # make sure that retries happen after 'num_retries' minutes have passed
            assert (
                int(time.time()) - start_time
                > (num_retries - 1)
                * 60  # need to decrease by 1 because the first retry happens almost immediately, not after a minute
            ), f"Ooops, looks like the retry happened within less than {num_retries} minutes"

        logger.info("Waiting for system to finish download")
        return num_retries_attempted

    def do_test_update_image_breaks_networking(
        self, env, broken_network_image,
    ):
        """
        Install an image without systemd-networkd binary existing.
        The network will not function, mender will not be able to send any logs.

        The expected status is the update will rollback, and be considered a failure
        """

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            deployment_id, _ = common_update_procedure(
                broken_network_image, devauth=devauth, deploy=deploy
            )
            reboot.verify_reboot_performed()  # since the network is broken, two reboots will be performed, and the last one will be detected
            deploy.check_expected_statistics(deployment_id, "failure", 1)

    def do_test_deployed_during_network_outage(
        self, env, valid_image_with_mender_conf,
    ):
        """
        Install a valid upgrade image while there is no network availability on the device
        Re-establishing the network connectivity results in the upgrade to be triggered.

        Emulate a flaky network connection, and ensure that the deployment still succeeds.
        """

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        self.manipulate_network_connectivity(mender_device, False)

        host_ip = env.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            mender_conf = mender_device.run("cat /etc/mender/mender.conf")
            deployment_id, expected_yocto_id = common_update_procedure(
                valid_image_with_mender_conf(mender_conf),
                verify_status=False,
                devauth=devauth,
                deploy=deploy,
            )
            time.sleep(60)

            for i in range(5):
                time.sleep(5)
                self.manipulate_network_connectivity(mender_device, i % 2 == 0)
            self.manipulate_network_connectivity(mender_device, True)

            logger.info("Network stabilized")
            reboot.verify_reboot_performed()
            deploy.check_expected_statistics(deployment_id, "success", 1)

        assert mender_device.yocto_id_installed_on_machine() == expected_yocto_id

    def do_test_image_download_retry_timeout(
        self, env, valid_image_with_mender_conf,
    ):
        """
        Install an update, and block storage connection when we detect it's
        being copied over to the inactive partition.

        The test should result in a successful download retry.

        NOTE: storage and gateway share an ip, so disabling connectivity
        is tricky - we must alternate between blocking by the whole ip and blocking
        just by domain
        """

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        # make tcp timeout quicker, none persistent changes
        mender_device.run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_time")
        mender_device.run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_intvl")
        mender_device.run("echo 3 > /proc/sys/net/ipv4/tcp_syn_retries")

        # to speed up timeouting client connection
        mender_device.run("echo 1 > /proc/sys/net/ipv4/tcp_keepalive_probes")

        inactive_part = mender_device.get_passive_partition()

        host_ip = env.get_virtual_network_host_ip()

        blocked_service = None

        with mender_device.get_reboot_detector(host_ip) as reboot:
            # Block after we start the download.
            mender_conf = mender_device.run("cat /etc/mender/mender.conf")
            deployment_id, new_yocto_id = common_update_procedure(
                valid_image_with_mender_conf(mender_conf),
                devauth=devauth,
                deploy=deploy,
            )
            mender_device.run(
                "start=$(date -u +%s);"
                + 'output="";'
                + 'while [ -z "$output" ]; do '
                + "sleep 0.1;"
                + 'output="$(fuser -mv %s)";' % inactive_part
                + "now=$(date -u +%s);"
                + "if [ $(($now - $start)) -gt 600 ]; then "
                + "exit 1;"
                + "fi;"
                + "done",
                wait=10 * 60,
            )

            # storage must be blocked by ip to kill an ongoing connection
            # so block the whole gateway
            blocked_service = "docker.mender.io"

            self.manipulate_network_connectivity(
                mender_device, False, hosts=[blocked_service]
            )

            # re-enable connectivity after 2 retries
            self.wait_for_download_retry_attempts(mender_device, "Connection timed out")

            self.manipulate_network_connectivity(
                mender_device, True, hosts=[blocked_service]
            )

            reboot.verify_reboot_performed()
            deploy.check_expected_status("finished", deployment_id)

            assert mender_device.get_active_partition() == inactive_part
            assert mender_device.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()

    def do_test_image_download_retry_download_count(
        self,
        env,
        valid_image_with_mender_conf,
        max_retries,
        unsuccessful_retries,
        success,
    ):
        """
        Install an update, and block storage connection when we detect it's
        being copied over to the inactive partition - parametrized number of times equal to "unsuccessful_retries"

        The test should result in a successful download retry if "max_retries" >= "unsuccessful_retries".

        NOTE: storage and gateway share an ip, so disabling connectivity
        is tricky - we must alternate between blocking by the whole ip and blocking
        just by domain
        """

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        # modify device config with our number of retries
        try:
            tmpdir = tempfile.mkdtemp()
            # retrieve the original configuration file
            output = mender_device.run("cat /etc/mender/mender.conf")
            config = json.loads(output)
            # add RetryDownloadCount value, modifying the default "10"
            config["RetryDownloadCount"] = max_retries
            mender_conf = os.path.join(tmpdir, "mender.conf")
            with open(mender_conf, "w") as fd:
                json.dump(config, fd)
            env.device.put(
                os.path.basename(mender_conf),
                local_path=os.path.dirname(mender_conf),
                remote_path="/etc/mender",
            )
        finally:
            shutil.rmtree(tmpdir)

        # start the Mender client
        logger.info("Restarting the client with updated configuration.")
        env.device.run("systemctl restart mender-updated")
        # end of client config modification

        # make tcp timeout quicker, none persistent changes
        mender_device.run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_time")
        mender_device.run("echo 2 > /proc/sys/net/ipv4/tcp_keepalive_intvl")
        mender_device.run("echo 3 > /proc/sys/net/ipv4/tcp_syn_retries")

        # to speed up timeouting client connection
        mender_device.run("echo 1 > /proc/sys/net/ipv4/tcp_keepalive_probes")

        active_part = mender_device.get_active_partition()
        inactive_part = mender_device.get_passive_partition()
        old_yocto_id = mender_device.yocto_id_installed_on_machine()

        host_ip = env.get_virtual_network_host_ip()

        blocked_service = None

        with mender_device.get_reboot_detector(host_ip) as reboot:
            # Block after we start the download.
            mender_conf = mender_device.run("cat /etc/mender/mender.conf")
            deployment_id, new_yocto_id = common_update_procedure(
                valid_image_with_mender_conf(mender_conf),
                devauth=devauth,
                deploy=deploy,
            )
            mender_device.run(
                "start=$(date -u +%s);"
                + 'output="";'
                + 'while [ -z "$output" ]; do '
                + "sleep 0.1;"
                + 'output="$(fuser -mv %s)";' % inactive_part
                + "now=$(date -u +%s);"
                + "if [ $(($now - $start)) -gt 600 ]; then "
                + "exit 1;"
                + "fi;"
                + "done",
                wait=10 * 60,
            )

            # storage must be blocked by ip to kill an ongoing connection
            # so block the whole gateway
            blocked_service = "docker.mender.io"

            self.manipulate_network_connectivity(
                mender_device, False, hosts=[blocked_service]
            )

            # re-enable connectivity after "unsuccessful_retries" retries
            # wait for >= unusccessful_retries retries. If max_retries is smaller, it will timeout as expected
            retries_attempted = self.wait_for_download_retry_attempts(
                mender_device,
                "Resuming download after",
                unsuccessful_retries,
                max_retries,
            )
            if max_retries > unsuccessful_retries:
                assert retries_attempted == unsuccessful_retries
            else:
                assert retries_attempted == max_retries

            self.manipulate_network_connectivity(
                mender_device, True, hosts=[blocked_service]
            )

            if success:
                reboot.verify_reboot_performed()
                deploy.check_expected_status("finished", deployment_id)

                assert mender_device.get_active_partition() == inactive_part
                assert mender_device.yocto_id_installed_on_machine() == new_yocto_id
                reboot.verify_reboot_not_performed()
            else:
                reboot.verify_reboot_not_performed()
                deploy.check_expected_status("inprogress", deployment_id)

                assert mender_device.get_active_partition() == active_part
                assert mender_device.yocto_id_installed_on_machine() == old_yocto_id

    def do_test_image_download_retry_hosts_broken(
        self, env, valid_image_with_mender_conf,
    ):
        """
        Block storage host (minio) by modifying the hosts file.
        """

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        inactive_part = mender_device.get_passive_partition()

        mender_device.run(
            "echo '1.1.1.1 s3.docker.mender.io' >> /etc/hosts"
        )  # break s3 connectivity before triggering deployment

        host_ip = env.get_virtual_network_host_ip()
        with mender_device.get_reboot_detector(host_ip) as reboot:
            mender_conf = mender_device.run("cat /etc/mender/mender.conf")
            deployment_id, new_yocto_id = common_update_procedure(
                valid_image_with_mender_conf(mender_conf),
                devauth=devauth,
                deploy=deploy,
            )

            self.wait_for_download_retry_attempts(
                mender_device, "Resuming download after ",
            )
            mender_device.run("sed -i.bak '/1.1.1.1/d' /etc/hosts")

            reboot.verify_reboot_performed()
            deploy.check_expected_status("finished", deployment_id)

            assert mender_device.get_active_partition() == inactive_part
            assert mender_device.yocto_id_installed_on_machine() == new_yocto_id
            reboot.verify_reboot_not_performed()

    def do_test_rootfs_conf_missing_from_new_update(
        self, env, valid_image_with_mender_conf
    ):
        """Test that the client is able to reboot to roll back if module or rootfs
        config is missing from the new partition. This only works for cases where a
        reboot restores the state."""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

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

            host_ip = env.get_virtual_network_host_ip()
            update_image_failed(
                mender_device,
                host_ip,
                expected_log_message="Cannot parse RootfsPartA/B in any configuration file!",
                install_image=valid_image_with_mender_conf(output),
                devauth=devauth,
                deploy=deploy,
            )

        finally:
            shutil.rmtree(tmpdir)


class TestFaultToleranceOpenSource(BasicTestFaultTolerance):
    @MenderTesting.slow
    def test_update_image_breaks_networking(
        self, standard_setup_one_client_bootstrapped, broken_network_image,
    ):
        self.do_test_update_image_breaks_networking(
            standard_setup_one_client_bootstrapped, broken_network_image,
        )

    @MenderTesting.slow
    def test_deployed_during_network_outage(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_deployed_during_network_outage(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
        )

    @MenderTesting.slow
    def test_image_download_retry_timeout(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_image_download_retry_timeout(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
        )

    @pytest.mark.parametrize(
        "max_retries, unsuccessful_retries, success",
        [(5, 2, True), (5, 7, False), (15, 12, True), (11, 15, False)],
        ids=[
            "reducedRetriesSuccess",
            "reducedRetriesFailure",
            "increasedRetriesSuccess",
            "increasedRetriesFailure",
        ],
    )
    @MenderTesting.slow
    def test_image_download_retry_download_count(
        self,
        standard_setup_one_client_bootstrapped,
        valid_image_with_mender_conf,
        max_retries,
        unsuccessful_retries,
        success,
    ):
        self.do_test_image_download_retry_download_count(
            standard_setup_one_client_bootstrapped,
            valid_image_with_mender_conf,
            max_retries,
            unsuccessful_retries,
            success,
        )

    @MenderTesting.slow
    def test_image_download_retry_hosts_broken(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_image_download_retry_hosts_broken(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
        )

    def test_rootfs_conf_missing_from_new_update(
        self, standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_rootfs_conf_missing_from_new_update(
            standard_setup_one_client_bootstrapped, valid_image_with_mender_conf
        )


class TestFaultToleranceEnterprise(BasicTestFaultTolerance):
    @MenderTesting.slow
    def test_update_image_breaks_networking(
        self, enterprise_one_client_bootstrapped, broken_network_image,
    ):
        self.do_test_update_image_breaks_networking(
            enterprise_one_client_bootstrapped, broken_network_image,
        )

    @MenderTesting.slow
    def test_deployed_during_network_outage(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_deployed_during_network_outage(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )

    @MenderTesting.slow
    def test_image_download_retry_timeout(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_image_download_retry_timeout(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )

    @MenderTesting.slow
    def test_image_download_retry_hosts_broken(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf,
    ):
        self.do_test_image_download_retry_hosts_broken(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )

    def test_rootfs_conf_missing_from_new_update(
        self, enterprise_one_client_bootstrapped, valid_image_with_mender_conf
    ):
        self.do_test_rootfs_conf_missing_from_new_update(
            enterprise_one_client_bootstrapped, valid_image_with_mender_conf
        )
