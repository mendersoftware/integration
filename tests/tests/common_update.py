# Copyright 2022 Northern.tech AS
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

import tempfile
import random

import pytest

from .. import conftest
from ..MenderAPI import devauth, deploy, image, logger
from . import artifact_lock


def common_update_procedure(
    install_image=None,
    device_type=conftest.machine_name,
    verify_status=True,
    signed=False,
    devices=None,
    scripts=[],
    pre_upload_callback=lambda: None,
    pre_deployment_callback=lambda: None,
    deployment_triggered_callback=lambda: None,
    make_artifact=None,
    compression_type="gzip",
    version=None,
    devauth=devauth,
    deploy=deploy,
    autogenerate_delta=False,
):

    with artifact_lock:
        artifact_name = "mender-%s" % str(random.randint(0, 99999999))
        logger.debug("randomized image id: " + artifact_name)

        # create artifact
        with tempfile.NamedTemporaryFile() as artifact_file:
            if make_artifact:
                created_artifact = make_artifact(artifact_file.name, artifact_name)
            else:
                compression_arg = "--compression " + compression_type
                created_artifact = image.make_rootfs_artifact(
                    install_image,
                    device_type,
                    artifact_name,
                    artifact_file.name,
                    signed=signed,
                    scripts=scripts,
                    global_flags=compression_arg,
                    version=version,
                )

            if created_artifact:
                pre_upload_callback()
                deploy.upload_image(created_artifact)
                if devices is None:
                    devices = list(
                        set(
                            [
                                device["id"]
                                for device in devauth.get_devices_status("accepted")
                            ]
                        )
                    )
                pre_deployment_callback()
                deployment_id = deploy.trigger_deployment(
                    name="New valid update",
                    artifact_name=artifact_name,
                    devices=devices,
                    autogenerate_delta=autogenerate_delta,
                )
            else:
                logger.warn("failed to create artifact")
                pytest.fail("error creating artifact")

    deployment_triggered_callback()
    # wait until deployment is in correct state
    if verify_status:
        deploy.check_not_in_status("pending", deployment_id)

    return deployment_id, artifact_name


def update_image(
    device,
    host_ip,
    expected_mender_clients=1,
    install_image=None,
    signed=False,
    devices=None,
    scripts=[],
    pre_upload_callback=lambda: None,
    pre_deployment_callback=lambda: None,
    deployment_triggered_callback=lambda: None,
    make_artifact=None,
    compression_type="gzip",
    version=None,
    devauth=devauth,
    deploy=deploy,
    autogenerate_delta=False,
):
    """
        Perform a successful upgrade, and assert that deployment status/logs are correct.

        A reboot is performed, and running partitions have been swapped.
        Deployment status will be set as successful for device.
        Logs will not be retrieved, and result in 404.
    """

    previous_inactive_part = device.get_passive_partition()
    with device.get_reboot_detector(host_ip) as reboot:
        deployment_id, expected_image_id = common_update_procedure(
            install_image,
            signed=signed,
            devices=devices,
            scripts=scripts,
            pre_upload_callback=pre_upload_callback,
            pre_deployment_callback=pre_deployment_callback,
            deployment_triggered_callback=deployment_triggered_callback,
            make_artifact=make_artifact,
            compression_type=compression_type,
            version=version,
            devauth=devauth,
            deploy=deploy,
            autogenerate_delta=autogenerate_delta,
        )
        reboot.verify_reboot_performed()

        try:
            # In the test_migrate_from_legacy_mender_v1_* tests, the storage
            # device changes name from one image to the next, so only compare
            # the index, not the device itself.
            assert device.get_active_partition()[-1] == previous_inactive_part[-1]
        except AssertionError:
            logs = []
            for d in devauth.get_devices():
                logs.append(deploy.get_logs(d["id"], deployment_id))

            pytest.fail(
                "device did not flip partitions during update, here are the device logs:\n\n %s"
                % (logs)
            )

        deploy.check_expected_statistics(
            deployment_id, "success", expected_mender_clients
        )

        for d in devauth.get_devices():
            deploy.get_logs(d["id"], deployment_id, expected_status=404)

    assert device.yocto_id_installed_on_machine() == expected_image_id

    deploy.check_expected_status("finished", deployment_id)

    # make sure backend recognizes signed and unsigned images
    artifact_name = deploy.get_deployment(deployment_id)["artifacts"][0]
    artifact_info = deploy.get_artifact_details(artifact_name)
    assert (
        artifact_info["signed"] is signed
    ), "image was not correct recognized as signed/unsigned"

    return deployment_id


def update_image_failed(
    device,
    host_ip,
    expected_mender_clients=1,
    expected_log_message="ArtifactVerifyReboot: Process exited with status 1",
    install_image="broken_update.ext4",
    make_artifact=None,
    expected_number_of_reboots=2,
    devauth=devauth,
    deploy=deploy,
):
    """
        Perform a upgrade using a broken image (random data)
        The device will reboot, uboot will detect this is not a bootable image, and revert to the previous partition.
        The resulting upgrade will be considered a failure.
    """

    original_image_id = device.yocto_id_installed_on_machine()

    previous_active_part = device.get_active_partition()
    with device.get_reboot_detector(host_ip) as reboot:
        deployment_id, _ = common_update_procedure(
            install_image, make_artifact=make_artifact, devauth=devauth, deploy=deploy,
        )
        # It will reboot twice. Once into the failed update, which the
        # bootloader will roll back, and therefore we will end up on the
        # original partition. Then once more because of the
        # ArtifactRollbackReboot step. Previously this rebooted only once,
        # because we only supported rootfs images, and could make assumptions
        # about where we would end up. However, with update modules we prefer to
        # be conservative, and reboot one more time after the rollback to make
        # *sure* we are in the correct partition.
        reboot.verify_reboot_performed(number_of_reboots=expected_number_of_reboots)

    with device.get_reboot_detector(host_ip) as reboot:
        assert device.get_active_partition() == previous_active_part

        deploy.check_expected_statistics(
            deployment_id, "failure", expected_mender_clients
        )

        for d in devauth.get_devices():
            assert expected_log_message in deploy.get_logs(d["id"], deployment_id)

        assert device.yocto_id_installed_on_machine() == original_image_id
        reboot.verify_reboot_not_performed()

    deploy.check_expected_status("finished", deployment_id)
