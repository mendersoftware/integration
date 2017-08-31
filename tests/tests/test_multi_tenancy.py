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
from common_docker import *
from common_setup import *
from helpers import Helpers
from MenderAPI import auth, adm, deploy, image, logger
from common_update import update_image_successful
from mendertesting import MenderTesting


@pytest.mark.skipif(conftest.mt_docker_compose_file is None,
                    reason="set --mt-docker-compose-file to run test")
class TestMultiTenancy(MenderTesting):
    def perform_update(self):
        if not env.host_string:
            execute(self.perform_update,
                    hosts=get_mender_clients())
            return

        update_image_successful(install_image=conftest.get_valid_image())

    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_token_validity(self):
        """ verify that only devices with valid tokens can bootstrap
            successfully to a multitenancy setup """

        wrong_token = "wrong-token"

        def wait_until_bootstrap_attempt():
            if not env.host_string:
                return execute(wait_until_bootstrap_attempt,
                               hosts=get_mender_clients())
            ssh_is_opened()

            for i in range(1, 20):
                    with settings(hide('everything'), warn_only=True):
                        out = run('journalctl -u mender | grep "bootstrapped -> authorize-wait"')
                        if out.succeeded:
                            return True
                        time.sleep(20/i)
            return False

        def set_correct_tenant_token(token):
            if not env.host_string:
                return execute(set_correct_tenant_token,
                               token,
                               hosts=get_mender_clients())

            run("sed -i 's/%s/%s/g' /etc/mender/mender.conf" % (wrong_token, token))
            run("systemctl restart mender")

        auth.reset_auth_token()
        auth.new_tenant("bob@bob.com", "hunter2hunter2")
        token = auth.current_tenant["tenant_token"]

        # create a new client with an incorrect token set
        new_tenant_client("mender-client", wrong_token)

        if wait_until_bootstrap_attempt():
            for _ in range(5):
                time.sleep(5)
                adm.get_devices(expected_devices=0)  # make sure device not seen
        else:
            pytest.fail("failed to bootstrap device")

        # setting the correct token makes the client visible to the backend
        set_correct_tenant_token(token)
        adm.get_devices(expected_devices=1)

    @pytest.mark.skip(reason="MT-1357")
    @pytest.mark.usefixtures("multitenancy_setup_without_client")
    def test_multi_tenancy_setup(self):
        """ Simply make sure we are able to run the multi tenancy setup and
           bootstrap 2 different devices to different tenants """

        auth.reset_auth_token()

        users = [
            {"email": "greg@greg.com", "password": "astrongpassword12345", "container": "mender-client"},
            {"email": "bob@bob.com", "password": "hunter2hunter2", "container": "client2"},
        ]

        for user in users:
            auth.new_tenant(user["email"], user["password"])
            t = auth.current_tenant["tenant_token"]
            new_tenant_client(user["container"], t)

            print "sleeping"
            time.sleep(1000)

            adm.accept_devices(1)
            print adm.get_devices()

            self.perform_update()


        # deploy to each device
        for user in users:
            auth.set_tenant(user["email"], user["password"])
            t = auth.current_tenant["tenant_token"]
            adm.accept_devices(1)
