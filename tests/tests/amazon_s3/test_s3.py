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
from tests import MenderTesting
from tests import common_update

@MenderTesting.fast
@MenderTesting.aws_s3
@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped_with_s3")
class TestBasicIntegrationWithS3(MenderTesting):

    def test_update_image_with_aws_s3(self,
                                      install_image=conftest.get_valid_image(),
                                      name=None,
                                      regenerate_image_id=True):
        """
            Perform a successful upgrade using AWS S3
        """

        if not env.host_string:
            execute(self.test_update_image_with_aws_s3,
                    hosts=get_mender_clients())
            return

        common_update.update_image_successful(install_image=conftest.get_valid_image())
