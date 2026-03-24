# Copyright 2026 Northern.tech AS
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

import shutil
import os
import subprocess

import pytest

from .. import conftest
from .common_update import common_update_procedure
from ..helpers import Helpers
from ..MenderAPI import DeviceAuthV2, Deployments, logger, image
from .mendertesting import MenderTesting
from testutils.infra.device import MenderDeviceGroup

from ..common_setup import (
    class_persistent_standard_setup_one_client_bootstrapped,
    class_persistent_enterprise_one_client_bootstrapped,
)
from .test_state_scripts import (
    class_persistent_setup_client_state_scripts_update_module,
    class_persistent_enterprise_setup_client_state_scripts_update_module,
)


class BaseTestCorruptDeploymentLog(MenderTesting):
    def do_test_corrupt_deployment_log(self, env):
        """Test that corrupted deployment log is sanitized and successfully
        uploaded to the server."""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        work_dir = "test_corrupt_depl_log.%s" % mender_device.host_string
        deployment_id = None
        try:
            artifact_script_dir = os.path.join(work_dir, "artifact-scripts")
            os.makedirs(artifact_script_dir)
            with open(
                os.path.join(
                    artifact_script_dir, "ArtifactInstall_Leave_01_corrupt-depl-log"
                ),
                "w",
            ) as fd:
                fd.write(
                    """#!/bin/sh
    log_file=$(ls /var/lib/mender/deployments.0000.*.log)
    echo break >> $log_file
    sync $log_file
    exit 1
    """
                )

            # Callback for our custom artifact maker
            def make_artifact(filename, artifact_name):
                return image.make_module_artifact(
                    "module-state-scripts-test",
                    conftest.machine_name,
                    artifact_name,
                    filename,
                    scripts=[artifact_script_dir],
                )

            # Now create the artifact, and make the deployment.
            device_id = Helpers.ip_to_device_id_map(
                MenderDeviceGroup([mender_device.host_string]), devauth=devauth,
            )[mender_device.host_string]
            deployment_id = common_update_procedure(
                verify_status=False,
                devices=[device_id],
                scripts=[artifact_script_dir],
                make_artifact=make_artifact,
                devauth=devauth,
                deploy=deploy,
            )[0]

            deploy.check_expected_statistics(deployment_id, "failure", 1)
            logs = deploy.get_logs(device_id, deployment_id)
            assert "(THE ORIGINAL LOGS CONTAINED INVALID ENTRIES)" in logs
        except:
            output = mender_device.run(
                "cat /data/mender/deployment*.log", warn_only=True
            )
            logger.info(output)
            raise
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            if deployment_id:
                try:
                    deploy.abort(deployment_id)
                except:
                    pass


class TestStateScriptsOpenSource(BaseTestCorruptDeploymentLog):
    def test_corrupt_deployment_log(
        self, class_persistent_setup_client_state_scripts_update_module,
    ):
        self.do_test_corrupt_deployment_log(
            class_persistent_setup_client_state_scripts_update_module,
        )


class TestStateScriptsEnterprise(BaseTestCorruptDeploymentLog):
    def test_corrupt_deployment_log(
        self, class_persistent_enterprise_setup_client_state_scripts_update_module,
    ):
        self.do_test_corrupt_deployment_log(
            class_persistent_enterprise_setup_client_state_scripts_update_module,
        )
