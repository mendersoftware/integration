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

import shutil
import os

from fabric.api import *
import pytest

from .. import conftest
from ..common import *
from ..common_setup import standard_setup_one_rofs_client_bootstrapped, \
                           standard_setup_with_short_lived_token, setup_failover, \
                           standard_setup_one_client_bootstrapped
from .common_update import update_image_successful, update_image_failed
from ..MenderAPI import image, inv, logger
from .mendertesting import MenderTesting

class TestBasicIntegration(MenderTesting):


    @MenderTesting.fast
    @pytest.mark.skipif(not os.path.exists("mender-image-full-cmdline-rofs-%s.ext4" % conftest.machine_name),
                        reason="Thud branch and older from Yocto does not have R/O rootfs support")
    def test_double_update_rofs(self, standard_setup_one_rofs_client_bootstrapped):
        """Upgrade a device with two consecutive R/O images using different compression algorithms"""

        mender_clients = standard_setup_one_rofs_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_double_update_rofs,
                    standard_setup_one_rofs_client_bootstrapped,
                    hosts=mender_clients)
            return

        # Verify that partition is read-only as expected
        run("mount | fgrep 'on / ' | fgrep '(ro,'")

        host_ip = standard_setup_one_rofs_client_bootstrapped.get_virtual_network_host_ip()
        update_image_successful(host_ip,
                                install_image="mender-image-full-cmdline-rofs-%s.ext4" % conftest.machine_name,
                                compression_type="gzip")
        run("mount | fgrep 'on / ' | fgrep '(ro,'")

        update_image_successful(host_ip,
                                install_image="mender-image-full-cmdline-rofs-%s.ext4" % conftest.machine_name,
                                compression_type="lzma")
        run("mount | fgrep 'on / ' | fgrep '(ro,'")


    @MenderTesting.fast
    def test_update_jwt_expired(self, standard_setup_with_short_lived_token):
        """Update a device with a short lived JWT token"""

        mender_clients = standard_setup_with_short_lived_token.get_mender_clients()

        if not env.host_string:
            execute(self.test_update_jwt_expired,
                    standard_setup_with_short_lived_token,
                    hosts=mender_clients)
            return

        host_ip = standard_setup_with_short_lived_token.get_virtual_network_host_ip()
        update_image_successful(host_ip, install_image=conftest.get_valid_image())

    @MenderTesting.fast
    def test_update_failover_server(self, setup_failover):
        """
        Client is initially set up against server A, and then receives an update
        containing a multi-server configuration, with server B as primary and A
        secondary. Server B does not, however, expect any clients and will trigger
        "failover" to server A.
        To create the necessary configuration I use a state script to modify the
        /etc/mender/mender.conf
        """

        mender_clients = setup_failover.get_mender_clients()

        if not env.host_string:
            execute(self.test_update_failover_server,
                    setup_failover,
                    hosts=mender_clients)
            return

        valid_image = conftest.get_valid_image()
        tmp_image = valid_image.split(".")[0] + "-failover-image.ext4"
        try:
            logger.info("Creating failover sample image.")
            shutil.copy(valid_image, tmp_image)
            conf = image.get_mender_conf(tmp_image)

            if conf == None:
                raise SystemExit("Could not retrieve mender.conf")

            conf["Servers"] = [{"ServerURL": "https://docker.mender-failover.io"}, \
                               {"ServerURL": conf["ServerURL"]}]
            conf.pop("ServerURL")
            image.replace_mender_conf(tmp_image, conf)

            host_ip = setup_failover.get_virtual_network_host_ip()
            update_image_successful(host_ip, install_image=tmp_image)
        finally:
            os.remove(tmp_image)

    @MenderTesting.fast
    def test_failed_updated_and_valid_update(self, standard_setup_one_client_bootstrapped):
        """Upload a device with a broken image, followed by a valid image"""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_failed_updated_and_valid_update,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients)
            return

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        update_image_failed(host_ip)
        update_image_successful(host_ip, install_image=conftest.get_valid_image())

    def test_update_no_compression(self, standard_setup_one_client_bootstrapped):
        """Uploads an uncompressed artifact, and runs the whole udpate process."""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_update_no_compression,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients)
            return

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        update_image_successful(host_ip, install_image=conftest.get_valid_image(), compression_type="none")



    def test_forced_update_check_from_client(self, standard_setup_one_client_bootstrapped):
        """Upload a device with a broken image, followed by a valid image"""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_forced_update_check_from_client,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients)
            return

        # Give the image a really large wait interval.
        sedcmd = "sed -i.bak 's/%s/%s/' /etc/mender/mender.conf" % ("\(.*PollInter.*:\)\( *[0-9]*\)", "\\1 1800")
        out = run(sedcmd)
        if out.return_code != 0:
            logger.error(out)
            pytest.fail("failed to set a large polling interval for the client.")
        run("systemctl restart mender-client")

        def deployment_callback():
            logger.info("Running pre deployment callback function")
            wait_count = 0
            # Match the log template six times to make sure the client is truly sleeping.
            catcmd = "journalctl -u mender-client --output=cat"
            template = run(catcmd)
            while True:
                logger.info("sleeping...")
                logger.info("wait_count: %d" % wait_count)
                time.sleep(10)
                out = run(catcmd)
                if out == template:
                    wait_count += 1
                    # Only return if the client has been idling in check-wait for a minute.
                    if wait_count == 6:
                        return
                    continue
                # Update the matching template
                template = run(catcmd)
                wait_count = 0

        def deployment_triggered_callback():
            output = run("mender -check-update")
            if output.return_code != 0:
                logger.error(output)
                pytest.fail("Forcing the update check failed")
            logger.info("mender client has forced an update check")

        host_ip = standard_setup_one_client_bootstrapped.get_virtual_network_host_ip()
        update_image_successful(host_ip,
                                install_image=conftest.get_valid_image(),
                                pre_deployment_callback=deployment_callback,
                                deployment_triggered_callback=deployment_triggered_callback)

    @pytest.mark.timeout(1000)
    def test_forced_inventory_update_from_client(self, standard_setup_one_client_bootstrapped):
        """Forces an inventory update from an idling client."""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_forced_inventory_update_from_client,
                    standard_setup_one_client_bootstrapped,
                    hosts=mender_clients)
            return

        # Give the image a really large wait interval.
        sedcmd = "sed -i.bak 's/%s/%s/' /etc/mender/mender.conf" % ("\(.*PollInter.*:\)\( *[0-9]*\)", "\\1 1800")
        out = run(sedcmd)
        run("systemctl restart mender-client")

        logger.info("Running pre deployment callback function")
        wait_count = 0
        # Match the log template six times to make sure the client is truly sleeping.
        catcmd = "journalctl -u mender-client --output=cat"
        template = run(catcmd)
        while True:
            logger.info("sleeping...")
            logger.info("wait_count: %d" % wait_count)
            time.sleep(10)
            out = run(catcmd)
            if out == template:
                wait_count += 1
                # Only return if the client has been idling in check-wait for a minute.
                if wait_count == 6:
                    break
                continue
            # Update the matching template.
            template = run(catcmd)
            wait_count = 0

        # Create some new inventory data from an inventory script.
        output = run("cd /usr/share/mender/inventory && echo '#!/bin/sh\necho host=foobar' > mender-inventory-test && chmod +x mender-inventory-test")

        # Now that the client has settled into the wait-state, run the command, and check if it does indeed exit the wait state,
        # and send inventory.
        output = run("mender -send-inventory")
        logger.info("mender client has forced an inventory update")

        # Give the client some time to send the inventory.
        time.sleep(5)

        # Check that the updated inventory value is now present.
        invJSON = inv.get_devices()
        for element in invJSON[0]["attributes"]:
            if element["name"] == "host" and element["value"] == "foobar":
                return
        pytest.fail("The inventory was not updated")
