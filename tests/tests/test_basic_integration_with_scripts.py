#!/usr/bin/python
# Copyright 2016 Mender Software AS
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
from common_update import update_image_successful, update_image_failed, update_image_successful_scripts, update_image_failed_scripts
from MenderAPI import adm, deploy
from mendertesting import MenderTesting


@pytest.mark.usefixtures("standard_setup_one_client_bootstrapped")
class TestBasicIntegrationWithScripts(MenderTesting):

    @MenderTesting.fast
    def test_failed_updated_and_valid_update(self):
        """Upload a device with a broken image, followed by a valid image"""

        if not env.host_string:
            execute(self.test_failed_updated_and_valid_update,
                    hosts=get_mender_clients())
            return

        scripts = ["ArtifactInstall_Enter_01", "ArtifactInstall_Leave_01", "ArtifactInstall_Leave_03", "ArtifactInstall_Error_21", 
                   "ArtifactReboot_Enter_01", "ArtifactReboot_Leave_01", "ArtifactReboot_Leave_99", "ArtifactReboot_Leave_89", "ArtifactReboot_Error_05", 
                   "ArtifactCommit_Enter_01", "ArtifactCommit_Leave_01", "ArtifactCommit_Error_05", "ArtifactCommit_Error_06", 
                   "ArtifactRollback_Enter_01", "ArtifactRollback_Leave_01", "ArtifactRollback_Error_01", 
                   "ArtifactRollbackReboot_Enter_01", "ArtifactRollbackReboot_Leave_01", "ArtifactRollbackReboot_Error_04", 
                   "ArtifactError_Enter_01", "ArtifactError_Leave_01"]


        update_image_failed_scripts(scripts=scripts)
        update_image_successful_scripts(scripts=scripts)

        executed = Helpers.get_executed_scripts()
        expected = """ArtifactInstall_Enter_01
ArtifactInstall_Leave_01
ArtifactInstall_Leave_03
ArtifactReboot_Enter_01
ArtifactReboot_Error_05
ArtifactError_Enter_01
ArtifactError_Leave_01
ArtifactInstall_Enter_01
ArtifactInstall_Leave_01
ArtifactInstall_Leave_03
ArtifactReboot_Enter_01
ArtifactReboot_Leave_01
ArtifactReboot_Leave_89
ArtifactReboot_Leave_99
ArtifactCommit_Enter_01
ArtifactCommit_Leave_01"""

        assert executed == expected

        rm = Helpers.remove_executed_scripts()

    @MenderTesting.fast
    def test_double_update(self):
        """Upload a device with two consecutive upgrade images"""

        if not env.host_string:
            execute(self.test_double_update,
                    hosts=get_mender_clients())
            return

        scripts = ["ArtifactInstall_Enter_01", "ArtifactInstall_Leave_01", "ArtifactInstall_Leave_03", "ArtifactInstall_Error_21", 
                   "ArtifactReboot_Enter_01", "ArtifactReboot_Leave_01", "ArtifactReboot_Leave_99", "ArtifactReboot_Leave_89", "ArtifactReboot_Error_05", 
                   "ArtifactCommit_Enter_01", "ArtifactCommit_Leave_01", "ArtifactCommit_Error_05", "ArtifactCommit_Error_06", 
                   "ArtifactRollback_Enter_01", "ArtifactRollback_Leave_01", "ArtifactRollback_Error_01", 
                   "ArtifactRollbackReboot_Enter_01", "ArtifactRollbackReboot_Leave_01", "ArtifactRollbackReboot_Error_04", 
                   "ArtifactError_Enter_01", "ArtifactError_Leave_01"]


        update_image_successful_scripts(scripts=scripts)
        update_image_successful_scripts(scripts=scripts)

        executed = Helpers.get_executed_scripts()
        expected = """ArtifactInstall_Enter_01
ArtifactInstall_Leave_01
ArtifactInstall_Leave_03
ArtifactReboot_Enter_01
ArtifactReboot_Leave_01
ArtifactReboot_Leave_89
ArtifactReboot_Leave_99
ArtifactCommit_Enter_01
ArtifactCommit_Leave_01
ArtifactInstall_Enter_01
ArtifactInstall_Leave_01
ArtifactInstall_Leave_03
ArtifactReboot_Enter_01
ArtifactReboot_Leave_01
ArtifactReboot_Leave_89
ArtifactReboot_Leave_99
ArtifactCommit_Enter_01
ArtifactCommit_Leave_01"""

        assert executed == expected

        rm = Helpers.remove_executed_scripts()
 

