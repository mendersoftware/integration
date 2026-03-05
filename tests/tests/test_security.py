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

import subprocess
import contextlib
import ssl
import socket
import time

import pytest

from ..common_setup import (
    running_custom_production_setup,
    standard_setup_with_short_lived_token,
    enterprise_with_short_lived_token,
)
from ..helpers import Helpers
from ..MenderAPI import DeviceAuthV2, Deployments, logger
from .common_update import common_update_procedure
from .mendertesting import MenderTesting


class BaseTestSecurity(MenderTesting):
    def do_test_token_token_expiration(self, env, valid_image_with_mender_conf):
        """verify that an expired token is handled correctly (client gets a new, valid one)
        and that deployments are still received by the client
        """
        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        Helpers.check_log_is_authenticated(mender_device)

        # this call verifies that the deployment process goes into an "inprogress" state
        # which is only possible when the client has a valid token.
        mender_conf = mender_device.run("cat /etc/mender/mender.conf")
        common_update_procedure(
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
        )


class TestSecurityOpenSource(BaseTestSecurity):
    def test_token_token_expiration(
        self, standard_setup_with_short_lived_token, valid_image_with_mender_conf
    ):
        self.do_test_token_token_expiration(
            standard_setup_with_short_lived_token, valid_image_with_mender_conf
        )


class TestSecurityEnterprise(BaseTestSecurity):
    def test_token_token_expiration(
        self, enterprise_with_short_lived_token, valid_image_with_mender_conf
    ):
        self.do_test_token_token_expiration(
            enterprise_with_short_lived_token, valid_image_with_mender_conf
        )
