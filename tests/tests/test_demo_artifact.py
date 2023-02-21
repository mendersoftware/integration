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

import os
import signal
import subprocess

import pytest
from flaky import flaky

from ..common_setup import running_custom_production_setup
from ..MenderAPI import authentication, deployments, DeviceAuthV2, logger
from .mendertesting import MenderTesting
from testutils.common import wait_until_healthy
from testutils.infra.container_manager.kubernetes_manager import isK8S


class BaseTestDemoArtifact(MenderTesting):
    """A simple class for testing the demo-Artifact upload."""

    EXTRA_ARGS = []

    # NOTE - The password is set on a per test-basis,
    # as it is generated on the fly by the demo script.
    auth = authentication.Authentication(
        name="mender-demo", username="mender-demo@example.com"
    )
    authv2 = DeviceAuthV2(auth)
    deploy = deployments.Deployments(auth, authv2)

    @pytest.fixture(scope="function")
    def run_demo_script(
        self, running_custom_production_setup, exit_cond="Login password:"
    ):
        """Simple fixture which returns a function which runs 'demo up'.

        :param exit_cond

               Is the string which needs to be present in the output of the demo
               script in order for it to return the process handle to the test
               asking for it. If the string does not exist, the process will block
               indefinitely, and hence the tests employing this fixture will need
               to have a timeout.
        """

        def run_demo_script_up(exit_cond=exit_cond):
            test_env = os.environ.copy()
            test_env[
                "DOCKER_COMPOSE_PROJECT_NAME"
            ] = running_custom_production_setup.name

            # the infra layer sets MENDER_TESTPREFIX for the compose command on first run
            # but here we're running the setup manually (the test does multiple ups/downs)
            # the prefix is lost here, so re-set it to the correct value
            test_env["MENDER_TESTPREFIX"] = running_custom_production_setup.name

            args = [
                "./demo",
                "--client",
                "-p",
                running_custom_production_setup.name,
            ]
            args += self.EXTRA_ARGS
            args.append("up")

            proc = subprocess.Popen(
                args,
                cwd="..",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=test_env,
            )
            logger.info("Started the demo script")
            password = ""

            for line in proc.stdout:
                line = line.decode()
                logger.info(line)
                if exit_cond in line.strip():
                    if exit_cond == "Login password:":
                        password = line.split(":")[-1].strip()
                        logger.info("The login password:")
                        logger.info(password)
                        self.auth.password = password
                        assert len(password) == 12
                    break
            wait_until_healthy(running_custom_production_setup.name)
            return proc

        running_custom_production_setup.run_demo_script_up = run_demo_script_up
        return running_custom_production_setup

    # Give the test a timeframe, as the script might run forever,
    # if something goes awry, or the script is not brought down properly.
    @flaky(max_runs=3)  # https://tracker.mender.io/browse/MEN-4495
    @pytest.mark.timeout(3000)
    def test_demo_artifact(self, run_demo_script):
        """Tests that the demo script does indeed upload the demo Artifact to the server."""

        run_demo_script.teardown()

        logger.info("--------------------------------------------------")
        logger.info("Running test_demo_artifact_upload")
        logger.info("--------------------------------------------------")
        self.demo_artifact_upload(run_demo_script.run_demo_script_up)
        run_demo_script.teardown()
        self.auth.reset_auth_token()

        logger.info("--------------------------------------------------")
        logger.info("Running test_demo_artifact_installation")
        logger.info("--------------------------------------------------")
        self.demo_artifact_installation(run_demo_script.run_demo_script_up)
        run_demo_script.teardown()
        self.auth.reset_auth_token()

        logger.info("--------------------------------------------------")
        logger.info("Running test_demo_up_down_up")
        logger.info("--------------------------------------------------")
        self.demo_up_down_up(run_demo_script.run_demo_script_up)
        run_demo_script.teardown()
        self.auth.reset_auth_token()

    def demo_artifact_upload(self, run_demo_script, exit_cond="Login password:"):
        proc = run_demo_script(exit_cond)
        arts = self.deploy.get_artifacts()
        try:
            assert len(arts) == 1
        except:
            logger.error(str(arts))
            raise
        assert "mender-demo-artifact" in arts[0]["name"]

        # Bring down the demo script
        logger.info("-- Terminating demo script")
        proc.send_signal(signal.SIGTERM)
        # Continue logging stdout until process stops
        for line in proc.stdout:
            logger.info(line.decode())
        proc.wait()
        assert proc.returncode == 0, "Demo script failed with non-zero exit code"

    def demo_artifact_installation(self, run_demo_script):
        """Tests that the demo-artifact is successfully deployed to a client device."""
        run_demo_script()
        artifacts = self.deploy.get_artifacts(
            auth_create_new_user=False
        )  # User should be created by the demo script.
        assert len(artifacts) == 1
        artifact_name = artifacts[0]["name"]

        # Trigger the deployment
        devices = self.authv2.get_devices()
        assert len(devices) == 1

        # Accept the device to be updated
        self.authv2.accept_devices(1)
        devices = list(
            set([device["id"] for device in self.authv2.get_devices_status("accepted")])
        )
        assert len(devices) == 1

        # Run the deployment.
        deployment_id = self.deploy.trigger_deployment(
            name="Demo artifact deployment",
            artifact_name=artifact_name,
            devices=devices,
        )

        # Verify the deployment
        self.deploy.check_expected_status("finished", deployment_id)

    def demo_up_down_up(self, run_demo_script):
        """Test that bringing the demo environment up, then down, then up succeeds"""

        # Upload demo artifact and create demo user
        self.demo_artifact_upload(run_demo_script)

        # Verify that the demo user is still present, when bringing
        # the environment up a second time
        self.demo_artifact_upload(run_demo_script, exit_cond="The user already exists")
        logger.info("Finished")


class TestDemoArtifactOpenSource(BaseTestDemoArtifact):
    pass


@pytest.mark.skipif(
    isK8S(), reason="not relevant in a staging or production environment"
)
class TestDemoArtifactEnterprise(BaseTestDemoArtifact):
    """A subclass of the BaseTestDemoArtifact class for testing the demo-Artifact
    upload in Enterprise mode."""

    EXTRA_ARGS = ["--enterprise-testing"]
