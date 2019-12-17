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

import logging
import shutil
import time
import os
import subprocess

from fabric.api import *
import pytest

from .. import conftest
from ..common import *
from ..common_setup import standard_setup_one_client_bootstrapped
from .common_update import common_update_procedure
from ..helpers import Helpers
from ..MenderAPI import deploy
from .mendertesting import MenderTesting

logger = logging.getLogger("root")

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
                "Idle_Enter_09", # Error in this script should not have any effect.
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
                "Idle_Leave_09", # Error in this script should not have any effect.
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
                "ArtifactCommit_Leave_01_extra_string", # Error in this script should not have any effect.
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
            "CorruptEtcScriptVersionInUpdate": True,
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
            "RebootScripts": [
                "ArtifactInstall_Enter_01",
            ],
            "ExpectedFinalPartition": ["OriginalPartition"],
            "ScriptOrder": [
                "ArtifactInstall_Enter_01",
                "ArtifactInstall_Leave_01",
                "ArtifactReboot_Enter_01",
                "ArtifactReboot_Leave_01",
                "ArtifactFailure_Enter_01",
                "ArtifactFailure_Leave_89",
            ],
            "ExpectedScriptFlow": [
                "ArtifactInstall_Enter_01",  # kill!
                "ArtifactFailure_Enter_01",  # run failure scripts
                "ArtifactFailure_Leave_89"
            ],
        },
    ),
    # (
    #     "simulate_powerloss_in_commit_enter",
    #     {
    #         "RebootScripts": ["ArtifactCommit_Enter_89"],
    #         "DoubleReboot": [True],
    #         "ExpectedFinalPartition": ["OriginalPartition"],
    #         "ScriptOrder": [
    #             "ArtifactInstall_Enter_01",
    #             "ArtifactInstall_Leave_01",
    #             "ArtifactReboot_Enter_01",
    #             "ArtifactReboot_Leave_01",
    #             "ArtifactCommit_Enter_89",
    #             "ArtifactRollback_Enter_00",
    #             "ArtifactRollbackReboot_Enter_89",
    #             "ArtifactFailure_Enter_89",
    #             "ArtifactFailure_Leave_09",
    #         ],
    #         "ExpectedScriptFlow": [
    #             "ArtifactInstall_Enter_01",
    #             "ArtifactInstall_Leave_01",
    #             "ArtifactReboot_Enter_01",
    #             "ArtifactReboot_Leave_01",  # on second partition, stop mender client
    #             "ArtifactCommit_Enter_89",  # sync and kill!
    #             "ArtifactRollback_Enter_00",
    #             "ArtifactRollbackReboot_Enter_89",
    #             "ArtifactFailure_Enter_89",  # run failure scripts on the committed (old) partition
    #             "ArtifactFailure_Leave_09",
    #         ],
    #     },
    # ),
    # (
    #     "simulate_powerloss_in_artifact_commit_leave",
    #     {
    #         "RebootOnceScripts": ["ArtifactCommit_Leave_01"],
    #         "DoubleReboot": [True],
    #         "ExpectedFinalPartition": ["OtherPartition"],
    #         "ScriptOrder": [
    #             "ArtifactInstall_Enter_01",
    #             "ArtifactInstall_Leave_01",
    #             "ArtifactReboot_Enter_01",
    #             "ArtifactReboot_Leave_01",
    #             "ArtifactCommit_Enter_89",
    #             "ArtifactCommit_Leave_01",
    #             "ArtifactCommit_Leave_02",
    #         ],
    #         "ExpectedScriptFlow": [
    #             "ArtifactInstall_Enter_01",
    #             "ArtifactInstall_Leave_01",
    #             "ArtifactReboot_Enter_01",
    #             "ArtifactReboot_Leave_01",
    #             "ArtifactCommit_Enter_89",
    #             "ArtifactCommit_Leave_01",  # kill!
    #             "ArtifactCommit_Leave_01",  # rerun
    #             "ArtifactCommit_Leave_02",
    #         ],
    #     },
    # ),
]



class TestStateScripts(MenderTesting):
    scripts = [
        "Idle_Enter_08_testing",
        "Idle_Enter_09",
        "Idle_Enter_100", # Invalid script, should never be run.
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
        "ArtifactRollback_Error_15", # Error for this state doesn't exist, should never run.
        "ArtifactRollbackReboot_Enter_00",
        "ArtifactRollbackReboot_Enter_99",
        "ArtifactRollbackReboot_Leave_01",
        "ArtifactRollbackReboot_Leave_99",
        "ArtifactRollbackReboot_Error_88", # Error for this state doesn't exist, should never run.
        "ArtifactRollbackReboot_Error_99", # Error for this state doesn't exist, should never run.
        "ArtifactFailure_Enter_22",
        "ArtifactFailure_Enter_33",
        "ArtifactFailure_Leave_44",
        "ArtifactFailure_Leave_55",
        "ArtifactFailure_Error_55", # Error for this state doesn't exist, should never run.
    ]

    @pytest.mark.parametrize("description,test_set", REBOOT_TEST_SET)
    def test_reboot_recovery(self, standard_setup_one_client_bootstrapped, description, test_set):

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(
                self.test_reboot_recovery,
                standard_setup_one_client_bootstrapped,
                description,
                test_set,
                hosts=mender_clients)
            return

        client = env.host_string
        work_dir = "test_state_scripts.%s" % client

        script_content = '#!/bin/sh\n\necho "$(basename $0)" >> /data/test_state_scripts.log\n'

        script_failure_content = script_content + 'sync\necho b > /proc/sysrq-trigger\n' # flush to disk before killing

        # This is only needed in the case: die commit-leave,
        # otherwise the device will get stuck in a boot-reboot loop
        script_reboot_once =(
        '''#!/bin/sh
        if [ $(grep -c $(basename $0) /data/test_state_scripts.log) -eq 0 ]; then
            echo "$(basename $0)" >> /data/test_state_scripts.log && sync && echo b > /proc/sysrq-trigger
        fi
        echo "$(basename $0)" >> /data/test_state_scripts.log
        exit 0''')
        script_error_content = script_content + "exit 1"

        # Put artifact-scripts in the artifact.
        artifact_script_dir = os.path.join(work_dir, "artifact-scripts")

        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)

        os.mkdir(work_dir)
        os.mkdir(artifact_script_dir)

        new_rootfs = os.path.join(work_dir, "rootfs.ext4")
        shutil.copy(conftest.get_valid_image(), new_rootfs)

        ps = subprocess.Popen(
            ["debugfs", "-w", new_rootfs], stdin=subprocess.PIPE)
        ps.stdin.write("cd /etc/mender\n" "mkdir scripts\n" "cd scripts\n")
        ps.stdin.close()
        ps.wait()

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
        device_id = Helpers.ip_to_device_id_map([client])[client]

        host_ip = standard_setup_one_client_bootstrapped.docker_get_docker_host_ip()
        with Helpers.RebootDetector(host_ip) as reboot_detector:

            deployment_id = common_update_procedure(
                install_image=new_rootfs,
                verify_status=True,
                devices=[device_id],
                scripts=[artifact_script_dir])[0]

            try:

                orig_part = Helpers.get_active_partition()

                # handle case where the client has not finished the update
                # path on the committed partition, but new partition is installed,
                # thus we will not get a valid entrypoint into the uncommitted parition(reboot_leave)
                # and the client will thus reboot straight after starting, and u-boot will
                # fall back to the committed partition
                if test_set.get("DoubleReboot", False):
                    reboot_detector.verify_reboot_performed(number_of_reboots=2)
                else:
                    reboot_detector.verify_reboot_performed()

                # wait until the last script has been run
                logger.debug("waint until the last script has been run")
                script_logs = ""
                timeout = time.time() + 60*60
                while timeout >= time.time():
                    time.sleep(3)
                    script_logs = run("cat /data/test_state_scripts.log")
                    if test_set.get("ExpectedScriptFlow")[-1] in script_logs:
                        break

                # make sure the client ended up on the right partition
                if "OtherPartition" in test_set.get("ExpectedFinalPartition", []):
                    assert orig_part != Helpers.get_active_partition()
                else:
                    assert orig_part == Helpers.get_active_partition()

                assert script_logs.split() == test_set.get("ExpectedScriptFlow")

            except:
                with settings(warn_only=True):
                    output = run("cat /data/mender/deployment*.log")
                    logger.info(output)
                raise

            finally:
                run("systemctl stop mender && "
                                + "rm -f /data/test_state_scripts.log && "
                                + "rm -rf /etc/mender/scripts && "
                                + "rm -rf /data/mender/scripts && "
                                + "systemctl start mender")





    @MenderTesting.slow
    @pytest.mark.parametrize("description,test_set", TEST_SETS)
    def test_state_scripts(self, standard_setup_one_client_bootstrapped, description, test_set):
        """Test that state scripts are executed in right order, and that errors
        are treated like they should."""

        mender_clients = standard_setup_one_client_bootstrapped.get_mender_clients()

        if not env.host_string:
            execute(self.test_state_scripts,
                    standard_setup_one_client_bootstrapped,
                    description,
                    test_set,
                    hosts=mender_clients)
            return

        client = env.host_string

        work_dir = "test_state_scripts.%s" % client
        deployment_id = None
        try:
            script_content = '#!/bin/sh\n\necho "`date --rfc-3339=seconds` $(basename $0)" >> /data/test_state_scripts.log\n'
            script_failure_content = script_content + "exit 1\n"

            old_active = Helpers.get_active_partition()

            # Make rootfs-scripts and put them in rootfs image.
            rootfs_script_dir = os.path.join(work_dir, "rootfs-scripts")
            shutil.rmtree(work_dir, ignore_errors=True)
            os.mkdir(work_dir)
            os.mkdir(rootfs_script_dir)

            new_rootfs = os.path.join(work_dir, "rootfs.ext4")
            shutil.copy(conftest.get_valid_image(), new_rootfs)
            ps = subprocess.Popen(["debugfs", "-w", new_rootfs], stdin=subprocess.PIPE)
            ps.stdin.write("cd /etc/mender\n"
                           "mkdir scripts\n"
                           "cd scripts\n")

            with open(os.path.join(rootfs_script_dir, "version"), "w") as fd:
                if test_set.get('CorruptEtcScriptVersionInUpdate'):
                    fd.write("1000")
                else:
                    fd.write("2")
            ps.stdin.write("rm version\n")
            ps.stdin.write("write %s version\n" % os.path.join(rootfs_script_dir, "version"))
            for script in self.scripts:
                if script.startswith("Artifact"):
                    # This is a script for the artifact, skip this one.
                    continue
                with open(os.path.join(rootfs_script_dir, script), "w") as fd:
                    if script in test_set['FailureScript']:
                        fd.write(script_failure_content)
                    else:
                        fd.write(script_content)
                    os.fchmod(fd.fileno(), 0755)
                ps.stdin.write("write %s %s\n" % (os.path.join(rootfs_script_dir, script), script))

            ps.stdin.close()
            ps.wait()

            # Write this again in case it was corrupted above.
            with open(os.path.join(rootfs_script_dir, "version"), "w") as fd:
                fd.write("2")

            # Then copy them to QEMU host.
            # Zip them all up to avoid having to copy each and every file, which is
            # quite slow.
            subprocess.check_call(["tar", "czf", "../rootfs-scripts.tar.gz", "."], cwd=rootfs_script_dir)
            # Stop client first to avoid race conditions.
            run("systemctl stop mender")
            try:
                put(os.path.join(work_dir, "rootfs-scripts.tar.gz"),
                    remote_path="/")
                run("mkdir -p cd /etc/mender/scripts && "
                    + "cd /etc/mender/scripts && "
                    + "tar xzf /rootfs-scripts.tar.gz && "
                    + "rm -f /rootfs-scripts.tar.gz")
            finally:
                run("systemctl start mender")

            # Put artifact-scripts in the artifact.
            artifact_script_dir = os.path.join(work_dir, "artifact-scripts")
            os.mkdir(artifact_script_dir)
            for script in self.scripts:
                if not script.startswith("Artifact"):
                    # Not an artifact script, skip this one.
                    continue
                with open(os.path.join(artifact_script_dir, script), "w") as fd:
                    if script in test_set['FailureScript']:
                        fd.write(script_failure_content)
                    else:
                        fd.write(script_content)
                    if test_set.get("CorruptDataScriptVersionIn") == script:
                        fd.write("printf '1000' > /data/mender/scripts/version\n")

            # Now create the artifact, and make the deployment.
            device_id = Helpers.ip_to_device_id_map([client])[client]
            deployment_id = common_update_procedure(install_image=new_rootfs,
                                                    verify_status=False,
                                                    devices=[device_id],
                                                    scripts=[artifact_script_dir])[0]
            if test_set['ExpectedStatus'] is None:
                # In this case we don't expect the deployment to even be
                # attempted, presumably due to failing Idle/Sync/Download
                # scripts on the client. So no deployment checking. Just wait
                # until there is at least one Error script in the log, which
                # will always be the case if ExpectedStatus is none (since one
                # of them is preventing the update from being attempted).
                def fetch_info(cmd_list):
                    all_output = ""
                    for cmd in cmd_list:
                        with settings(warn_only=True):
                            output = run(cmd)
                        logger.error("%s:\n%s" % (cmd, output))
                        all_output += "%s\n" % output
                    return all_output
                info_query = [
                    "cat /data/test_state_scripts.log 1>&2",
                    "journalctl -u mender",
                    "top -n5 -b",
                    "ls -l /proc/`pgrep mender`/fd",
                    "for fd in /proc/`pgrep mender`/fdinfo/*; do echo $fd:; cat $fd; done",
                ]
                starttime = time.time()
                while starttime + 60*60 >= time.time():
                    with settings(warn_only=True):
                        result = run("grep Error /data/test_state_scripts.log")
                        if result.succeeded:
                            # If it succeeds, stop.
                            break
                        else:
                            fetch_info(info_query)
                            time.sleep(10)
                            continue
                else:
                    info = fetch_info(info_query)
                    pytest.fail('Waited too long for "Error" to appear in log:\n%s' % info)
            else:
                deploy.check_expected_statistics(deployment_id, test_set['ExpectedStatus'], 1)

            # Always give the client a little bit of time to settle in the base
            # state after an update.
            time.sleep(10)

            output = run("cat /data/test_state_scripts.log")
            self.verify_script_log_correct(test_set, output.split('\n'))

            new_active = Helpers.get_active_partition()
            should_switch_partition = (test_set['ExpectedStatus'] == "success")

            if test_set.get('SwapPartitionExpectation'):
                should_switch_partition = not should_switch_partition

            if should_switch_partition:
                assert old_active != new_active, "Device did not switch partition as expected!"
            else:
                assert old_active == new_active, "Device switched partition which was not expected!"

        except:
            with settings(warn_only=True):
                output = run("cat /data/mender/deployment*.log")
                logger.info(output)
            raise

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            if deployment_id:
                try:
                    deploy.abort(deployment_id)
                except:
                    pass
            run("systemctl stop mender && "
                + "rm -f /data/test_state_scripts.log && "
                + "rm -rf /etc/mender/scripts && "
                + "rm -rf /data/mender/scripts && "
                + "systemctl start mender")

    def verify_script_log_correct(self, test_set, log_orig):
        expected_order = test_set['ScriptOrder']

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

                if (log_pos < len(log)
                    and log[log_pos - 1].startswith("Sync_")
                    and log[log_pos].startswith("Idle_")
                    and not expected_order[expected_pos].startswith("Idle_")):
                    # The Idle/Sync sequence is allowed to "wrap around" and start
                    # over, because it may take a few rounds of checking before the
                    # deployment is ready for the client.
                    expected_pos = 0

            # Test cases with an expectation of success/failure shall do only 1 iteration
            # Test cases with None expectation will loop through the error sequence in a loop, but still
            # we want to make sure that it is reasonable (i.e. looping with the correct time intervals).
            # For these cases we set a max. of 50 iterations to accomodate for slow running of the framework
            if test_set['ExpectedStatus'] is not None:
                assert num_iterations == 1
            else:
                assert num_iterations < 50

        except:
            logger.error("Exception in verify_script_log_correct: log of scripts = '%s'"
                  % "\n".join(log_orig))
            logger.error("scripts we expected = '%s'"
                  % "\n".join(expected_order))
            raise
