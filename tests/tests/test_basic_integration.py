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
from MenderAPI import adm, deploy
from mendertesting import MenderTesting


@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestBasicIntegration(MenderTesting):


    @MenderTesting.fast
    def test_double_update(self):
        """Upload a device with two consecutive upgrade images"""

        if not env.host_string:
            execute(self.test_double_update,
                    hosts=get_mender_clients())
            return

        update_image_successful(install_image=conftest.get_valid_image())
        update_image_successful(install_image=conftest.get_valid_image())


    @MenderTesting.fast
    def test_failed_updated_and_valid_update(self):
        """Upload a device with a broken image, followed by a valid image"""

        if not env.host_string:
            execute(self.test_failed_updated_and_valid_update,
                    hosts=get_mender_clients())
            return

        update_image_failed()
        update_image_successful(install_image=conftest.get_valid_image())
