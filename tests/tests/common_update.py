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

from common_docker import *
from common import *
from helpers import Helpers
from MenderAPI import adm, deploy, image, logger
import random
from fabric.api import *
import tempfile
from tests import artifact_lock
import pytest


def common_update_procedure(install_image,
                            regenerate_image_id=True,
                            device_type="vexpress-qemu",
                            broken_image=False,
                            verify_status=True,
                            signed=False,
                            devices=None,
                            scripts=[]):

    with artifact_lock:
        if broken_image:
            artifact_id = "broken_image_" + str(random.randint(0, 999999))
        elif regenerate_image_id:
            artifact_id = Helpers.artifact_id_randomize(install_image)
            logger.debug("randomized image id: " + artifact_id)
        else:
            artifact_id = Helpers.yocto_id_from_ext4(install_image)

        # create atrifact
        with tempfile.NamedTemporaryFile() as artifact_file:
            created_artifact = image.make_artifact(install_image, device_type, artifact_id, artifact_file, signed=signed, scripts=scripts)

            if created_artifact:
                deploy.upload_image(created_artifact)
                if devices is None:
                    devices = list(set([device["device_id"] for device in adm.get_devices_status("accepted")]))
                deployment_id = deploy.trigger_deployment(name="New valid update",
                                                          artifact_name=artifact_id,
                                                          devices=devices)
            else:
                logger.warn("failed to create artifact")
                pytest.fail("error creating artifact")

    # wait until deployment is in correct state
    if verify_status:
        deploy.check_expected_status("inprogress", deployment_id)

    return deployment_id, artifact_id

def update_image_successful(install_image, regenerate_image_id=True, signed=False, skip_reboot_verification=False, expected_mender_clients=1):
    """
        Perform a successful upgrade, and assert that deployment status/logs are correct.

        A reboot is performed, and running partitions have been swapped.
        Deployment status will be set as successful for device.
        Logs will not be retrieved, and result in 404.
    """

    previous_inactive_part = Helpers.get_passive_partition()
    with Helpers.RebootDetector() as reboot:
        deployment_id, expected_image_id = common_update_procedure(install_image,
                                                                   regenerate_image_id,
                                                                   signed=signed)
        reboot.verify_reboot_performed()

    with Helpers.RebootDetector() as reboot:
        try:
            assert Helpers.get_active_partition() == previous_inactive_part
        except AssertionError:
            logs = []
            for d in adm.get_devices():
                logs.append(deploy.get_logs(d["device_id"], deployment_id))

            pytest.fail("device did not flip partitions during update, here are the device logs:\n\n %s" % (logs))


        deploy.check_expected_statistics(deployment_id, "success", expected_mender_clients)

        for d in adm.get_devices():
            deploy.get_logs(d["device_id"], deployment_id, expected_status=404)

        if not skip_reboot_verification:
            reboot.verify_reboot_not_performed()

    assert Helpers.yocto_id_installed_on_machine() == expected_image_id

    deploy.check_expected_status("finished", deployment_id)

    # make sure backend recognizes signed and unsigned images
    artifact_id = deploy.get_deployment(deployment_id)["artifacts"][0]
    artifact_info = deploy.get_artifact_details(artifact_id)
    assert artifact_info["signed"] is signed, "image was not correct recognized as signed/unsigned"

    return deployment_id


def update_image_failed(install_image="broken_update.ext4", expected_mender_clients=1):
    """
        Perform a upgrade using a broken image (random data)
        The device will reboot, uboot will detect this is not a bootable image, and revert to the previous partition.
        The resulting upgrade will be considered a failure.
    """

    devices_accepted = get_mender_clients()
    original_image_id = Helpers.yocto_id_installed_on_machine()

    previous_active_part = Helpers.get_active_partition()
    with Helpers.RebootDetector() as reboot:
        deployment_id, _ = common_update_procedure(install_image, broken_image=True)
        reboot.verify_reboot_performed()

    with Helpers.RebootDetector() as reboot:
        assert Helpers.get_active_partition() == previous_active_part

        deploy.check_expected_statistics(deployment_id, "failure", expected_mender_clients)

        for d in adm.get_devices():
            assert "running rollback image" in deploy.get_logs(d["device_id"], deployment_id)

        assert Helpers.yocto_id_installed_on_machine() == original_image_id
        reboot.verify_reboot_not_performed()

    deploy.check_expected_status("finished", deployment_id)
