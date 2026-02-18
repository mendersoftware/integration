# Copyright 2025 Northern.tech AS
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

import os
import re
import time
import uuid
import pytest
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass

from ..common_setup import standard_setup_extended
from .common_update import common_update_procedure
from ..MenderAPI import DeviceAuthV2, Deployments, logger
from .mendertesting import MenderTesting
from testutils.common import requests_get


@pytest.fixture(scope="session")
def artifact_gen_script():
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "gen_docker-compose")

        tag_pattern = re.compile(r"^\d+\.\d+\.\d+(?:-build\d+)?$")
        version = os.environ.get("MENDER_CONTAINER_MODULES_VERSION", "main")

        base_url = "https://raw.githubusercontent.com/mendersoftware/mender-container-modules/refs"
        file_path = "src/gen_docker-compose"

        if tag_pattern.match(version):
            ref_path = f"tags/{version}"
        elif version.startswith("pull/"):
            ref_path = version
        else:
            ref_path = f"heads/{version}"

        url = f"{base_url}/{ref_path}/{file_path}"

        req = requests_get(url)
        with open(script_path, "w") as f:
            f.write(req.text)

        os.chmod(script_path, 0o755)
        yield script_path


@dataclass
class DockerService:
    name: str
    image: str
    base_image: str = "busybox:latest"
    build_image: bool = True


@contextmanager
def create_test_manifest(services):
    """Create Docker images and compose manifest for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        manifests_dir = os.path.join(temp_dir, "manifests")
        images_dir = os.path.join(temp_dir, "images")
        os.makedirs(manifests_dir)
        os.makedirs(images_dir)

        # Build and save images for each service that needs it
        for service in services:
            if service.build_image:
                dockerfile = os.path.join(temp_dir, f"Dockerfile.{service.name}")
                with open(dockerfile, "w") as f:
                    # Add a uuid to to each Dockerfile to generate unique images (mainly we can check proper cleanup)
                    f.write(
                        f'FROM {service.base_image}\nRUN echo "{uuid.uuid4()}" > /image_id\nCMD ["sleep", "infinity"]\n'
                    )
                subprocess.check_call(
                    ["docker", "build", "-t", service.image, "-f", dockerfile, temp_dir]
                )
                subprocess.check_call(
                    [
                        "docker",
                        "save",
                        "-o",
                        os.path.join(images_dir, f"{service.image}.tar"),
                        service.image,
                    ]
                )

        with open(os.path.join(manifests_dir, "docker-compose.yml"), "w") as f:
            f.write("services:\n")
            for service in services:
                f.write(f"  {service.name}:\n")
                f.write(f"    image: {service.image}\n")
                f.write(f"    network_mode: bridge\n")

        yield manifests_dir, images_dir


def make_docker_compose_artifact(
    artifact_gen_script, manifests_dir, project_name, images_dir, extra_args=None
):
    def make_artifact(filename, artifact_name):
        cmd = [
            artifact_gen_script,
            "--artifact-name",
            artifact_name,
            "--device-type",
            "qemux86-64",
            "--output-path",
            filename,
            "--manifests-dir",
            manifests_dir,
            "--images-dir",
            images_dir,
            "--project-name",
            project_name,
        ]
        if extra_args:
            cmd.extend(extra_args)
        subprocess.check_call(cmd)
        return filename

    return make_artifact


class TestDockerCompose(MenderTesting):
    def test_successful_rollback(self, standard_setup_extended, artifact_gen_script):
        env = standard_setup_extended
        mender_device = env.device

        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        devices = devauth.get_devices_status("accepted")
        assert len(devices) == 1
        device_id = devices[0]["id"]

        services = [
            DockerService(name="test1", image="test-container-image1"),
            DockerService(name="test2", image="test-container-image2"),
        ]

        with create_test_manifest(services) as (manifests_dir, images_dir):
            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)

        docker_ps = mender_device.run("docker ps")
        logger.info(f"docker ps output after successful deployment:\n{docker_ps}")
        assert "test-container-image1" in docker_ps
        assert "test-container-image2" in docker_ps

        # Trigger a rollback by providing a non-existing image
        services = [
            DockerService(name="test1", image="non-existing-image", build_image=False),
            DockerService(name="test2", image="test-container-image3"),
        ]

        with create_test_manifest(services) as (manifests_dir, images_dir):
            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "failure", 1)

        docker_ps = mender_device.run("docker ps")
        logger.info(f"docker ps output after rollback:\n{docker_ps}")
        assert "test-container-image1" in docker_ps
        assert "test-container-image2" in docker_ps
        assert not "non-existing-image" in docker_ps
        assert not "test-container-image3" in docker_ps

    def test_invalid_manifest(self, standard_setup_extended, artifact_gen_script):
        env = standard_setup_extended
        mender_device = env.device

        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        devices = devauth.get_devices_status("accepted")
        assert len(devices) == 1
        device_id = devices[0]["id"]

        with tempfile.TemporaryDirectory() as temp_dir:
            manifests_dir = os.path.join(temp_dir, "manifests")
            images_dir = os.path.join(temp_dir, "images")
            os.makedirs(manifests_dir)
            os.makedirs(images_dir)

            with open(os.path.join(manifests_dir, "docker-compose.yml"), "w") as f:
                f.write("services:\n")
                f.write("  ,,,:\n")  # Invalid service name
                f.write("    image: test-container-image1\n")
                f.write("    network_mode: bridge\n")

            with open(os.path.join(images_dir, "dummy.tar"), "wb") as f:
                f.write(b"dummy")

            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "failure", 1)

    def test_empty_image_tarball(self, standard_setup_extended, artifact_gen_script):
        env = standard_setup_extended
        mender_device = env.device

        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        devices = devauth.get_devices_status("accepted")
        assert len(devices) == 1
        device_id = devices[0]["id"]

        services = [
            DockerService(name="test1", image="test-image1"),
        ]

        with create_test_manifest(services) as (manifests_dir, images_dir):
            # Corrupt the tarball by overwriting with empty file
            corrupted_tar = os.path.join(images_dir, "test-image1.tar")
            with open(corrupted_tar, "wb") as f:
                f.write(b"")

            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "failure", 1)

    def test_consecutive_updates(self, standard_setup_extended, artifact_gen_script):
        env = standard_setup_extended
        mender_device = env.device

        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        devices = devauth.get_devices_status("accepted")
        assert len(devices) == 1
        device_id = devices[0]["id"]

        # First deployment
        services = [
            DockerService(name="test1", image="test-container-image1"),
            DockerService(name="test2", image="test-container-image2"),
        ]

        with create_test_manifest(services) as (manifests_dir, images_dir):
            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)

        docker_ps = mender_device.run("docker ps")
        logger.info(f"docker ps output after first deployment:\n{docker_ps}")
        assert "test-container-image1" in docker_ps
        assert "test-container-image2" in docker_ps

        # Verify images are loaded
        docker_images = mender_device.run("docker image ls")
        assert "test-container-image1" in docker_images
        assert "test-container-image2" in docker_images

        # Second deployment with different services
        services = [
            DockerService(name="test3", image="test-container-image3"),
            DockerService(name="test4", image="test-container-image4"),
        ]

        with create_test_manifest(services) as (manifests_dir, images_dir):
            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)

        docker_ps = mender_device.run("docker ps")
        logger.info(f"docker ps output after second deployment:\n{docker_ps}")
        # Old containers should be cleaned up
        assert "test-container-image1" not in docker_ps
        assert "test-container-image2" not in docker_ps
        # New containers should be running
        assert "test-container-image3" in docker_ps
        assert "test-container-image4" in docker_ps

        # Verify old images are cleaned up
        docker_images = mender_device.run("docker images")
        assert "test-container-image1" not in docker_images
        assert "test-container-image2" not in docker_images
        assert "test-container-image3" in docker_images
        assert "test-container-image4" in docker_images

    def test_rollback_with_broken_connection(
        self, standard_setup_extended, artifact_gen_script
    ):
        """Test rollback when server connection is broken during deployment."""
        env = standard_setup_extended
        mender_device = env.device

        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        devices = devauth.get_devices_status("accepted")
        assert len(devices) == 1
        device_id = devices[0]["id"]

        services = [
            DockerService(name="test1", image="test-container-image1"),
        ]

        with create_test_manifest(services) as (manifests_dir, images_dir):
            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)

        docker_ps = mender_device.run("docker ps")
        logger.info(f"docker ps output after initial deployment:\n{docker_ps}")
        assert "test-container-image1" in docker_ps

        services = [
            DockerService(name="test2", image="test-container-image2"),
        ]

        with create_test_manifest(services) as (manifests_dir, images_dir):
            # Create an Artifact state script that blocks network access to the Mender server
            with tempfile.TemporaryDirectory() as script_dir:
                script_path = os.path.join(script_dir, "ArtifactInstall_Leave_00")
                with open(script_path, "w") as script_file:
                    script_file.write(
                        """#!/bin/sh
# Block network access to simulate connection loss by redirecting to invalid IP
echo "Blocking network connection to Mender server"
sed -i.backup -e '$a127.0.0.1 docker.mender.io' /etc/hosts
exit 0
"""
                    )
                os.chmod(script_path, 0o755)

                deployment_id, _ = common_update_procedure(
                    verify_status=True,
                    devices=[device_id],
                    make_artifact=make_docker_compose_artifact(
                        artifact_gen_script,
                        manifests_dir,
                        "test",
                        images_dir,
                        extra_args=["--", "--script", script_path],
                    ),
                    devauth=devauth,
                    deploy=deploy,
                )
        logger.info("Waiting for retry status update to fail (takes ~3 minutes)")

        timeout = 240
        for _ in range(timeout):
            if "Giving up on sending status updates to server" in mender_device.run(
                "systemctl status mender-updated", hide=True
            ):
                break
            logger.debug("Waiting for status update to give up")
            time.sleep(1)
        mender_device.run("mv /etc/hosts.backup /etc/hosts")

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "failure", 1)

        # Verify rollback occurred - original service should still be running
        docker_ps = mender_device.run("docker ps")
        logger.info(f"docker ps output after failed deployment:\n{docker_ps}")
        assert "test-container-image1" in docker_ps
        assert "test-container-image2" not in docker_ps

    def test_healthcheck(self, standard_setup_extended, artifact_gen_script):
        env = standard_setup_extended
        mender_device = env.device

        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        devices = devauth.get_devices_status("accepted")
        assert len(devices) == 1
        device_id = devices[0]["id"]

        with tempfile.TemporaryDirectory() as temp_dir:
            manifests_dir = os.path.join(temp_dir, "manifests")
            images_dir = os.path.join(temp_dir, "images")
            os.makedirs(manifests_dir)
            os.makedirs(images_dir)

            # Build and save the image
            dockerfile = os.path.join(temp_dir, "Dockerfile.test1")
            with open(dockerfile, "w") as f:
                f.write(
                    f'FROM busybox:latest\nRUN echo "{uuid.uuid4()}" > /image_id\nCMD ["sleep", "infinity"]\n'
                )
            subprocess.check_call(
                [
                    "docker",
                    "build",
                    "-t",
                    "test-container-image1",
                    "-f",
                    dockerfile,
                    temp_dir,
                ]
            )
            subprocess.check_call(
                [
                    "docker",
                    "save",
                    "-o",
                    os.path.join(images_dir, "test-container-image1.tar"),
                    "test-container-image1",
                ]
            )

            # Create manifest with passing healthcheck
            with open(os.path.join(manifests_dir, "docker-compose.yml"), "w") as f:
                f.write("services:\n")
                f.write("  test1:\n")
                f.write("    image: test-container-image1\n")
                f.write("    network_mode: bridge\n")
                f.write("    healthcheck:\n")
                f.write('      test: ["CMD", "true"]\n')
                f.write("      interval: 1s\n")
                f.write("      timeout: 1s\n")
                f.write("      retries: 1\n")

            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "success", 1)

        docker_ps = mender_device.run("docker ps")
        logger.info(f"docker ps output after successful deployment:\n{docker_ps}")
        assert "test-container-image1" in docker_ps

        with tempfile.TemporaryDirectory() as temp_dir:
            manifests_dir = os.path.join(temp_dir, "manifests")
            images_dir = os.path.join(temp_dir, "images")
            os.makedirs(manifests_dir)
            os.makedirs(images_dir)

            # Build and save the image
            dockerfile = os.path.join(temp_dir, "Dockerfile.test2")
            with open(dockerfile, "w") as f:
                f.write(
                    f'FROM busybox:latest\nRUN echo "{uuid.uuid4()}" > /image_id\nCMD ["sleep", "infinity"]\n'
                )
            subprocess.check_call(
                [
                    "docker",
                    "build",
                    "-t",
                    "test-container-image2",
                    "-f",
                    dockerfile,
                    temp_dir,
                ]
            )
            subprocess.check_call(
                [
                    "docker",
                    "save",
                    "-o",
                    os.path.join(images_dir, "test-container-image2.tar"),
                    "test-container-image2",
                ]
            )

            # Create manifest with failing healthcheck
            with open(os.path.join(manifests_dir, "docker-compose.yml"), "w") as f:
                f.write("services:\n")
                f.write("  test2:\n")
                f.write("    image: test-container-image2\n")
                f.write("    network_mode: bridge\n")
                f.write("    healthcheck:\n")
                f.write('      test: ["CMD", "false"]\n')
                f.write("      interval: 1s\n")
                f.write("      timeout: 1s\n")
                f.write("      retries: 1\n")

            deployment_id, _ = common_update_procedure(
                verify_status=True,
                devices=[device_id],
                make_artifact=make_docker_compose_artifact(
                    artifact_gen_script, manifests_dir, "test", images_dir
                ),
                devauth=devauth,
                deploy=deploy,
            )

        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "failure", 1)

        # Verify rollback occurred - original service should still be running
        docker_ps = mender_device.run("docker ps")
        logger.info(
            f"docker ps output after failed healthcheck deployment:\n{docker_ps}"
        )
        assert "test-container-image1" in docker_ps
        assert "test-container-image2" not in docker_ps
