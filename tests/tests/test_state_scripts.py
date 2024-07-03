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

import shutil
import time
import os
import subprocess
import pathlib

from flaky import flaky

import pytest

from .. import conftest
from ..common_setup import (
    class_persistent_standard_setup_one_client_bootstrapped,
    class_persistent_enterprise_one_client_bootstrapped,
)
from .common_update import common_update_procedure
from ..helpers import Helpers
from ..MenderAPI import DeviceAuthV2, Deployments, logger, image
from .mendertesting import MenderTesting
from testutils.infra.device import MenderDeviceGroup


@pytest.fixture(scope="class")
def class_persistent_setup_client_state_scripts_update_module(
    class_persistent_standard_setup_one_client_bootstrapped,
):
    device = class_persistent_standard_setup_one_client_bootstrapped.device
    device.put(
        "module-state-scripts-test",
        local_path=pathlib.Path(__file__).parent.parent.absolute(),
        remote_path="/usr/share/mender/modules/v3",
    )

    return class_persistent_standard_setup_one_client_bootstrapped


@pytest.fixture(scope="class")
def class_persistent_enterprise_setup_client_state_scripts_update_module(
    class_persistent_enterprise_one_client_bootstrapped,
):
    device = class_persistent_enterprise_one_client_bootstrapped.device
    device.put(
        "module-state-scripts-test",
        local_path=pathlib.Path(__file__).parent.parent.absolute(),
        remote_path="/usr/share/mender/modules/v3",
    )

    return class_persistent_enterprise_one_client_bootstrapped


TEST_SETS = [
    (
        "Normal_success",
        {
            "FailureScript": [],
            "ExpectedStatus": "success",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactInstall_Leave_03",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Enter_11",
                "ArtifactReboot_Leave_01",
                "ArtifactReboot_Leave_89",
                "ArtifactReboot_Leave_99",
                "ArtifactCommit_Enter_01",
                "ArtifactCommit_Enter_05",
                "ArtifactCommit_Leave_01_extra_string",
                "ArtifactCommit_Leave_91",
            ],
        },
    ),
    (
        "Failure_in_Idle_Enter_script",
        {
            "FailureScript": ["Idle_Enter_09"],
            "ExpectedStatus": "success",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",  # Error in this script should not have any effect.
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactInstall_Leave_03",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Enter_11",
                "ArtifactReboot_Leave_01",
                "ArtifactReboot_Leave_89",
                "ArtifactReboot_Leave_99",
                "ArtifactCommit_Enter_01",
                "ArtifactCommit_Enter_05",
                "ArtifactCommit_Leave_01_extra_string",
                "ArtifactCommit_Leave_91",
            ],
        },
    ),
    (
        "Failure_in_Idle_Leave_script",
        {
            "FailureScript": ["Idle_Leave_09"],
            "ExpectedStatus": "success",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",  # Error in this script should not have any effect.
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactInstall_Leave_03",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Enter_11",
                "ArtifactReboot_Leave_01",
                "ArtifactReboot_Leave_89",
                "ArtifactReboot_Leave_99",
                "ArtifactCommit_Enter_01",
                "ArtifactCommit_Enter_05",
                "ArtifactCommit_Leave_01_extra_string",
                "ArtifactCommit_Leave_91",
            ],
        },
    ),
    (
        "Failure_in_Sync_Enter_script",
        {
            "FailureScript": ["Sync_Enter_02"],
            "ExpectedStatus": None,
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Error_15",
                "Sync_Error_16",
            ],
        },
    ),
    (
        "Failure_in_Sync_Leave_script",
        {
            "FailureScript": ["Sync_Leave_15"],
            "ExpectedStatus": None,
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Sync_Error_15",
                "Sync_Error_16",
            ],
        },
    ),
    (
        "Failure_in_Download_Enter_script",
        {
            "FailureScript": ["Download_Enter_12"],
            "ExpectedStatus": None,
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Error_25",
            ],
        },
    ),
    (
        "Failure_in_Download_Leave_script",
        {
            "FailureScript": ["Download_Leave_14"],
            "ExpectedStatus": "failure",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Error_25",
            ],
        },
    ),
    (
        "Failure_in_ArtifactInstall_Enter_script",
        {
            "FailureScript": ["ArtifactInstall_Enter_01"],
            "ExpectedStatus": "failure",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Error_01",
                "ArtifactInstall_Error_02",
                "ArtifactInstall_Error_99",
                "ArtifactRollback_Enter_00",
                "ArtifactRollback_Enter_01",
                "ArtifactRollback_Leave_00",
                "ArtifactRollback_Leave_01",
                "ArtifactRollbackReboot_Enter_00",
                "ArtifactRollbackReboot_Enter_99",
                "ArtifactRollbackReboot_Leave_01",
                "ArtifactRollbackReboot_Leave_99",
                "ArtifactFailure_Enter_22",
                "ArtifactFailure_Enter_33",
                "ArtifactFailure_Leave_44",
                "ArtifactFailure_Leave_55",
            ],
        },
    ),
    (
        "Failure_in_ArtifactCommit_Enter_script",
        {
            "FailureScript": ["ArtifactCommit_Enter_05"],
            "ExpectedStatus": "failure",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactInstall_Leave_03",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Enter_11",
                "ArtifactReboot_Leave_01",
                "ArtifactReboot_Leave_89",
                "ArtifactReboot_Leave_99",
                "ArtifactCommit_Enter_01",
                "ArtifactCommit_Enter_05",
                "ArtifactCommit_Error_91",
                "ArtifactRollback_Enter_00",
                "ArtifactRollback_Enter_01",
                "ArtifactRollback_Leave_00",
                "ArtifactRollback_Leave_01",
                "ArtifactRollbackReboot_Enter_00",
                "ArtifactRollbackReboot_Enter_99",
                "ArtifactRollbackReboot_Leave_01",
                "ArtifactRollbackReboot_Leave_99",
                "ArtifactFailure_Enter_22",
                "ArtifactFailure_Enter_33",
                "ArtifactFailure_Leave_44",
                "ArtifactFailure_Leave_55",
            ],
        },
    ),
    (
        "Failure_in_ArtifactCommit_Leave_script",
        {
            "FailureScript": ["ArtifactCommit_Leave_01_extra_string"],
            "ExpectedStatus": "failure",
            "SwapPartitionExpectation": True,
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactInstall_Leave_03",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Enter_11",
                "ArtifactReboot_Leave_01",
                "ArtifactReboot_Leave_89",
                "ArtifactReboot_Leave_99",
                "ArtifactCommit_Enter_01",
                "ArtifactCommit_Enter_05",
                "ArtifactCommit_Leave_01_extra_string",  # Error in this script should not have any effect.
                "ArtifactCommit_Error_91",
            ],
        },
    ),
    (
        "Corrupted_script_version_in_data",
        {
            "FailureScript": [],
            "ExpectedStatus": "failure",
            "CorruptDataScriptVersionIn": "ArtifactReboot_Enter_11",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactInstall_Leave_03",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Enter_11",
                # since version is corrupted from now on, no more scripts
                # will be executed, but rollback will be performed
            ],
        },
    ),
    (
        "Corrupted_script_version_in_etc",
        {
            "FailureScript": [],
            "ExpectedStatus": "failure",
            "CorruptEtcScriptVersionIn": "ArtifactReboot_Leave_99",
            "RestoreEtcScriptVersionIn": "ArtifactRollbackReboot_Leave_99",
            "ScriptOrder": [
                "Idle_Enter_08_testing",
                "Idle_Enter_09",
                "Idle_Leave_09",
                "Idle_Leave_10",
                "Sync_Enter_02",
                "Sync_Enter_03",
                "Sync_Leave_04",
                "Sync_Leave_15",
                "Download_Enter_12",
                "Download_Enter_13",
                "Download_Leave_14",
                "Download_Leave_25",
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactInstall_Leave_03",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Enter_11",
                "ArtifactReboot_Leave_01",
                "ArtifactReboot_Leave_89",
                "ArtifactReboot_Leave_99",
                "ArtifactCommit_Enter_01",
                "ArtifactCommit_Enter_05",
                "ArtifactCommit_Error_91",
                "ArtifactRollback_Enter_00",
                "ArtifactRollback_Enter_01",
                "ArtifactRollback_Leave_00",
                "ArtifactRollback_Leave_01",
                "ArtifactRollbackReboot_Enter_00",
                "ArtifactRollbackReboot_Enter_99",
                "ArtifactRollbackReboot_Leave_01",
                "ArtifactRollbackReboot_Leave_99",
                "ArtifactFailure_Enter_22",
                "ArtifactFailure_Enter_33",
                "ArtifactFailure_Leave_44",
                "ArtifactFailure_Leave_55",
            ],
        },
    ),
]


REBOOT_TEST_SET = [
    (
        "simulate_powerloss_artifact_install_enter",
        {
            "RebootScripts": ["ArtifactInstall_Enter_02"],
            "ExpectedFinalPartition": ["OriginalPartition"],
            "ScriptOrder": [
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Enter_02",
                "ArtifactInstall_Leave_01",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Leave_01",
                "ArtifactFailure_Enter_01",
                "ArtifactFailure_Leave_89",
            ],
            "ExpectedScriptFlow": [
                "ArtifactInstall_Enter_01",  # run one script to init log
                "ArtifactInstall_Enter_02",  # kill!
                "ArtifactFailure_Enter_01",  # run failure scripts
                "ArtifactFailure_Leave_89",
            ],
        },
    ),
    (
        "simulate_powerloss_in_commit_enter",
        {
            "RebootScripts": ["ArtifactCommit_Enter_89"],
            "ExpectedFinalPartition": ["OriginalPartition"],
            "ScriptOrder": [
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Leave_01",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Leave_01",
                "ArtifactCommit_Enter_89",
                "ArtifactRollback_Enter_00",
                "ArtifactRollbackReboot_Enter_89",
                "ArtifactFailure_Enter_89",
                "ArtifactFailure_Leave_09",
            ],
            "ExpectedScriptFlow": [
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Leave_01",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Leave_01",  # on second partition, stop mender client
                "ArtifactCommit_Enter_89",  # sync and kill!
                "ArtifactRollback_Enter_00",
                "ArtifactRollbackReboot_Enter_89",
                "ArtifactFailure_Enter_89",  # run failure scripts on the committed (old) partition
                "ArtifactFailure_Leave_09",
            ],
        },
    ),
    (
        "simulate_powerloss_in_artifact_commit_leave",
        {
            "RebootOnceScripts": ["ArtifactCommit_Leave_01"],
            "ExpectedFinalPartition": ["OtherPartition"],
            "ScriptOrder": [
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Leave_01",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Leave_01",
                "ArtifactCommit_Enter_89",
                "ArtifactCommit_Leave_01",
                "ArtifactCommit_Leave_02",
            ],
            "ExpectedScriptFlow": [
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Leave_01",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Leave_01",
                "ArtifactCommit_Enter_89",
                "ArtifactCommit_Leave_01",  # kill!
                "ArtifactCommit_Leave_01",  # rerun
                "ArtifactCommit_Leave_02",
            ],
        },
    ),
]


class BaseTestStateScripts(MenderTesting):
    scripts = [
        "Idle_Enter_08_testing",
        "Idle_Enter_09",
        "Idle_Enter_100",  # Invalid script, should never be run.
        "Idle_Leave_09",
        "Idle_Leave_10",
        "Idle_Error_00",
        "Sync_Enter_02",
        "Sync_Enter_03",
        "Sync_Leave_04",
        "Sync_Leave_15",
        "Sync_Error_15",
        "Sync_Error_16",
        "Download_Enter_12",
        "Download_Enter_13",
        "Download_Leave_14",
        "Download_Leave_25",
        "Download_Error_25",
        "ArtifactInstall_Enter_01",
        "ArtifactInstall_Enter_02",
        "ArtifactInstall_Leave_01",
        "ArtifactInstall_Leave_03",
        "ArtifactInstall_Error_01",
        "ArtifactInstall_Error_02",
        "ArtifactInstall_Error_99",
        "ArtifactReboot_Enter_01",
        "ArtifactReboot_Enter_11",
        "ArtifactReboot_Leave_01",
        "ArtifactReboot_Leave_89",
        "ArtifactReboot_Leave_99",
        "ArtifactReboot_Error_97",
        "ArtifactReboot_Error_98",
        "ArtifactCommit_Enter_01",
        "ArtifactCommit_Enter_05",
        "ArtifactCommit_Leave_01_extra_string",
        "ArtifactCommit_Leave_91",
        "ArtifactCommit_Error_91",
        "ArtifactRollback_Enter_00",
        "ArtifactRollback_Enter_01",
        "ArtifactRollback_Leave_00",
        "ArtifactRollback_Leave_01",
        "ArtifactRollback_Error_15",  # Error for this state doesn't exist, should never run.
        "ArtifactRollbackReboot_Enter_00",
        "ArtifactRollbackReboot_Enter_99",
        "ArtifactRollbackReboot_Leave_01",
        "ArtifactRollbackReboot_Leave_99",
        "ArtifactRollbackReboot_Error_88",  # Error for this state doesn't exist, should never run.
        "ArtifactRollbackReboot_Error_99",  # Error for this state doesn't exist, should never run.
        "ArtifactFailure_Enter_22",
        "ArtifactFailure_Enter_33",
        "ArtifactFailure_Leave_44",
        "ArtifactFailure_Leave_55",
        "ArtifactFailure_Error_55",  # Error for this state doesn't exist, should never run.
    ]

    def do_test_reboot_recovery(
        self, env, description, test_set,
    ):

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        work_dir = "test_state_scripts.%s" % mender_device.host_string

        script_content = (
            '#!/bin/sh\n\necho "$(basename $0)" >> /data/test_state_scripts.log\n'
        )

        script_failure_content = (
            script_content + "sync\necho b > /proc/sysrq-trigger\n"
        )  # flush to disk before killing

        # This is only needed in the case: die commit-leave,
        # otherwise the device will get stuck in a boot-reboot loop
        script_reboot_once = """#!/bin/sh
        if [ $(grep -c $(basename $0) /data/test_state_scripts.log) -eq 0 ]; then
            echo "$(basename $0)" >> /data/test_state_scripts.log && sync && echo b > /proc/sysrq-trigger
        fi
        echo "$(basename $0)" >> /data/test_state_scripts.log
        exit 0"""

        # Put artifact-scripts in the artifact.
        artifact_script_dir = os.path.join(work_dir, "artifact-scripts")

        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)

        os.mkdir(work_dir)
        os.mkdir(artifact_script_dir)

        for script in test_set.get("ScriptOrder"):
            if not script.startswith("Artifact"):
                # Not an artifact script, skip this one.
                continue
            with open(os.path.join(artifact_script_dir, script), "w") as fd:
                if script in test_set.get("RebootScripts", []):
                    fd.write(script_failure_content)
                if script in test_set.get("RebootOnceScripts", []):
                    fd.write(script_reboot_once)
                else:
                    fd.write(script_content)

        # Now create the artifact, and make the deployment.
        device_id = Helpers.ip_to_device_id_map(
            MenderDeviceGroup([mender_device.host_string]), devauth=devauth,
        )[mender_device.host_string]

        host_ip = env.get_virtual_network_host_ip()

        def make_artifact(filename, artifact_name):
            return image.make_module_artifact(
                "module-state-scripts-test",
                conftest.machine_name,
                artifact_name,
                filename,
                scripts=[artifact_script_dir],
            )

        with mender_device.get_reboot_detector(host_ip) as reboot_detector:

            common_update_procedure(
                verify_status=True,
                devices=[device_id],
                scripts=[artifact_script_dir],
                make_artifact=make_artifact,
                devauth=devauth,
                deploy=deploy,
            )

            try:
                reboot_detector.verify_reboot_performed()

                # wait until the last script has been run
                logger.debug("Wait until the last script has been run")
                script_logs = ""
                timeout = time.time() + 10 * 60
                while timeout >= time.time():
                    time.sleep(3)
                    try:
                        script_logs = mender_device.run(
                            "cat /data/test_state_scripts.log"
                        )
                        if test_set.get("ExpectedScriptFlow")[-1] in script_logs:
                            break
                    except EOFError:
                        # In some cases the SSH connection raises here EOF due to the
                        # client simulating powerloss. The test will just retry
                        pass
                else:
                    pytest.fail(
                        "Timeout waiting for ExpectedScriptFlow in state scripts. Expected %s, got %s"
                        % (
                            test_set.get("ExpectedScriptFlow"),
                            ", ".join(script_logs.rstrip().split("\n")),
                        )
                    )

                assert script_logs.split() == test_set.get("ExpectedScriptFlow")

            except:
                output = mender_device.run(
                    "cat /data/mender/deployment*.log", warn_only=True
                )
                logger.info(output)
                raise

            finally:
                mender_device.run(
                    "systemctl stop mender-updated && "
                    + "rm -f /data/test_state_scripts.log && "
                    + "rm -rf /etc/mender/scripts && "
                    + "rm -rf /data/mender/scripts && "
                    + "systemctl start mender-updated"
                )

    def do_test_state_scripts(
        self, env, description, test_set,
    ):
        """Test that state scripts are executed in right order, and that errors
        are treated like they should."""

        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        work_dir = "test_state_scripts.%s" % mender_device.host_string
        deployment_id = None
        try:
            script_content = '#!/bin/sh\n\necho "`date --rfc-3339=seconds` $(basename $0)" >> /data/test_state_scripts.log\n'
            script_failure_content = script_content + "exit 1\n"

            # Make rootfs-scripts and put them in rootfs image.
            rootfs_script_dir = os.path.join(work_dir, "rootfs-scripts")
            shutil.rmtree(work_dir, ignore_errors=True)
            os.mkdir(work_dir)
            os.mkdir(rootfs_script_dir)

            for script in self.scripts:
                if script.startswith("Artifact"):
                    # This is a script for the artifact, skip this one.
                    continue
                with open(os.path.join(rootfs_script_dir, script), "w") as fd:
                    if script in test_set["FailureScript"]:
                        fd.write(script_failure_content)
                    else:
                        fd.write(script_content)
                    os.fchmod(fd.fileno(), 0o0755)

            # Write this again in case it was corrupted above.
            with open(os.path.join(rootfs_script_dir, "version"), "w") as fd:
                fd.write("3")

            # Then zip and copy them to QEMU host.
            subprocess.check_call(
                ["tar", "czf", "../rootfs-scripts.tar.gz", "."], cwd=rootfs_script_dir
            )
            # Stop client first to avoid race conditions.
            mender_device.run("systemctl stop mender-updated")
            try:
                mender_device.put(
                    os.path.join(work_dir, "rootfs-scripts.tar.gz"), remote_path="/"
                )
                mender_device.run(
                    "mkdir -p cd /etc/mender/scripts && "
                    + "cd /etc/mender/scripts && "
                    + "tar xzf /rootfs-scripts.tar.gz && "
                    + "rm -f /rootfs-scripts.tar.gz"
                )
            finally:
                mender_device.run("systemctl start mender-updated")

            # Put artifact-scripts in the artifact.
            artifact_script_dir = os.path.join(work_dir, "artifact-scripts")
            os.mkdir(artifact_script_dir)
            for script in self.scripts:
                if not script.startswith("Artifact"):
                    # Not an artifact script, skip this one.
                    continue
                with open(os.path.join(artifact_script_dir, script), "w") as fd:
                    if script in test_set["FailureScript"]:
                        fd.write(script_failure_content)
                    else:
                        fd.write(script_content)
                    if test_set.get("CorruptDataScriptVersionIn") == script:
                        fd.write("printf '1000' > /data/mender/scripts/version\n")
                    if test_set.get("CorruptEtcScriptVersionIn") == script:
                        fd.write("printf '1000' > /etc/mender/scripts/version\n")
                    if test_set.get("RestoreEtcScriptVersionIn") == script:
                        fd.write("printf '3' > /etc/mender/scripts/version\n")

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
            if test_set["ExpectedStatus"] is None:
                # In this case we don't expect the deployment to even be
                # attempted, presumably due to failing Idle/Sync/Download
                # scripts on the client. So no deployment checking. Just wait
                # until there is at least one Error script in the log, which
                # will always be the case if ExpectedStatus is none (since one
                # of them is preventing the update from being attempted).
                def fetch_info(cmd_list):
                    all_output = ""
                    for cmd in cmd_list:
                        output = mender_device.run(cmd, warn_only=True)
                        logger.error("%s:\n%s" % (cmd, output))
                        all_output += "%s\n" % output
                    return all_output

                info_query = [
                    "cat /data/test_state_scripts.log 1>&2",
                    "journalctl --unit mender-updated",
                    "top -n5 -b",
                    "ls -l /proc/`pgrep mender-update`/fd",
                    "for fd in /proc/`pgrep mender-update`/fdinfo/*; do echo $fd:; cat $fd; done",
                ]
                starttime = time.time()
                while starttime + 10 * 60 >= time.time():
                    output = mender_device.run(
                        "grep Error /data/test_state_scripts.log", warn_only=True
                    )
                    if output.rstrip() != "":
                        # If it succeeds, stop.
                        break
                    else:
                        fetch_info(info_query)
                        time.sleep(10)
                        continue
                else:
                    info = fetch_info(info_query)
                    pytest.fail(
                        'Waited too long for "Error" to appear in log:\n%s' % info
                    )
            else:
                deploy.check_expected_statistics(
                    deployment_id, test_set["ExpectedStatus"], 1
                )

            # Always give the client a little bit of time to settle in the base
            # state after an update.
            time.sleep(10)

            output = mender_device.run("cat /data/test_state_scripts.log")
            self.verify_script_log_correct(test_set, output.split("\n"))

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
            mender_device.run(
                "systemctl stop mender-updated && "
                + "rm -f /data/test_state_scripts.log && "
                + "rm -rf /etc/mender/scripts && "
                + "rm -rf /data/mender/scripts && "
                + "systemctl start mender-updated"
            )

    def verify_script_log_correct(self, test_set, log_orig):
        expected_order = test_set["ScriptOrder"]

        # First remove timestamps from the log
        log = [l.split(" ")[-1] for l in log_orig]

        # Iterate down the list of expected scripts, and make sure that the log
        # follows the same list.

        # Position in log list.
        log_pos = 0
        # Position in script list from test_set.
        expected_pos = 0
        # Iterations around the full expected_order list
        num_iterations = 0
        try:
            while log_pos < len(log):

                if len(log[log_pos]) > 0:
                    # Make sure we are at right script.
                    assert expected_order[expected_pos] == log[log_pos]

                log_pos = log_pos + 1
                expected_pos = expected_pos + 1

                if expected_pos == len(expected_order):
                    # We completed the expected sequence, we count as one full iteration
                    # and restart the index for the next iteration
                    num_iterations = num_iterations + 1
                    expected_pos = 0

                if (
                    log_pos < len(log)
                    and log[log_pos - 1].startswith("Sync_")
                    and log[log_pos].startswith("Idle_")
                    and not expected_order[expected_pos].startswith("Idle_")
                ):
                    # The Idle/Sync sequence is allowed to "wrap around" and start
                    # over, because it may take a few rounds of checking before the
                    # deployment is ready for the client.
                    expected_pos = 0

            # Test cases with an expectation of success/failure shall do only 1 iteration
            # Test cases with None expectation will loop through the error sequence in a loop, but still
            # we want to make sure that it is reasonable (i.e. looping with the correct time intervals).
            # For these cases we set a max. of 50 iterations to accomodate for slow running of the framework
            if test_set["ExpectedStatus"] is not None:
                assert num_iterations == 1
            else:
                assert num_iterations < 50

        except:
            logger.error(
                "Exception in verify_script_log_correct: log of scripts = '%s'"
                % "\n".join(log_orig)
            )
            logger.error("scripts we expected = '%s'" % "\n".join(expected_order))
            raise


class TestStateScriptsOpenSource(BaseTestStateScripts):
    @pytest.mark.parametrize("description,test_set", REBOOT_TEST_SET)
    def test_reboot_recovery(
        self,
        class_persistent_setup_client_state_scripts_update_module,
        description,
        test_set,
    ):
        self.do_test_reboot_recovery(
            class_persistent_setup_client_state_scripts_update_module,
            description,
            test_set,
        )

    @flaky(max_runs=3)
    @MenderTesting.slow
    @pytest.mark.parametrize("description,test_set", TEST_SETS)
    def test_state_scripts(
        self,
        class_persistent_setup_client_state_scripts_update_module,
        description,
        test_set,
    ):
        self.do_test_state_scripts(
            class_persistent_setup_client_state_scripts_update_module,
            description,
            test_set,
        )


class TestStateScriptsEnterprise(BaseTestStateScripts):
    @pytest.mark.parametrize("description,test_set", REBOOT_TEST_SET)
    def test_reboot_recovery(
        self,
        class_persistent_enterprise_setup_client_state_scripts_update_module,
        description,
        test_set,
    ):
        self.do_test_reboot_recovery(
            class_persistent_enterprise_setup_client_state_scripts_update_module,
            description,
            test_set,
        )

    @flaky(max_runs=3)
    @MenderTesting.slow
    @pytest.mark.parametrize("description,test_set", TEST_SETS)
    def test_state_scripts(
        self,
        class_persistent_enterprise_setup_client_state_scripts_update_module,
        description,
        test_set,
    ):
        self.do_test_state_scripts(
            class_persistent_enterprise_setup_client_state_scripts_update_module,
            description,
            test_set,
        )
