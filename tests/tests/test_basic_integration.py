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
from common import *
from common_setup import *
from helpers import Helpers
from common_update import update_image_successful, update_image_failed
from MenderAPI import adm, deploy, image
from mendertesting import MenderTesting
import shutil

class TestBasicIntegration(MenderTesting):


    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
    def test_double_update(self):
        """Upload a device with two consecutive upgrade images"""

        if not env.host_string:
            execute(self.test_double_update,
                    hosts=get_mender_clients())
            return

        update_image_successful(install_image=conftest.get_valid_image())
        update_image_successful(install_image=conftest.get_valid_image())


    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_with_short_lived_token")
    def test_update_jwt_expired(self):
        """Upload a device with two consecutive upgrade images"""

        if not env.host_string:
            execute(self.test_update_jwt_expired,
                    hosts=get_mender_clients())
            return

        update_image_successful(install_image=conftest.get_valid_image())

    @MenderTesting.fast
    @pytest.mark.usefixtures("setup_failover")
    def test_update_failover_server(self):
        """
        Client is initially set up against server A, and then receives an update
        containing a multi-server configuration, with server B as primary and A
        secondary. Server B does not, however, expect any clients and will trigger
        "failover" to server A.
        To create the necessary configuration I use a state script to modify the
        /etc/mender/mender.conf
        """
        if not env.host_string:
            execute(self.test_update_failover_server,
                    hosts=get_mender_clients())
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

            update_image_successful(install_image=tmp_image)
        finally:
            os.remove(tmp_image)

    @MenderTesting.fast
    @pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
    def test_failed_updated_and_valid_update(self):
        """Upload a device with a broken image, followed by a valid image"""

        if not env.host_string:
            execute(self.test_failed_updated_and_valid_update,
                    hosts=get_mender_clients())
            return

        update_image_failed()
        update_image_successful(install_image=conftest.get_valid_image())

    @pytest.mark.timeout(1000)
    @pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
    def test_forced_update_check_from_client(self):
        """Upload a device with a broken image, followed by a valid image"""

        if not env.host_string:
            execute(self.test_forced_update_check_from_client,
                    hosts=get_mender_clients())
            return

        # Give the image a really large wait interval.
        sedcmd = "sed -i.bak 's/%s/%s/' /etc/mender/mender.conf" % ("\(.*PollInter.*:\)\( *[0-9]*\)", "\\1 1800")
        out = run(sedcmd)
        if out.return_code != 0:
            logger.error(out)
            pytest.fail("failed to set a large polling interval for the client.")
        run("systemctl restart mender")

        def deployment_callback():
            logger.info("Running pre deployment callback function")
            wait_count = 0
            # Match the log template six times to make sure the client is truly sleeping.
            catcmd = "journalctl -u mender --output=cat"
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
            output = run("mender --check-update")
            if output.return_code != 0:
                logger.error(output)
                pytest.fail("Forcing the update check failed")
            logger.info("mender client has forced an update check")

        update_image_successful(install_image=conftest.get_valid_image(), pre_deployment_callback=deployment_callback,
                                deployment_triggered_callback=deployment_triggered_callback)
