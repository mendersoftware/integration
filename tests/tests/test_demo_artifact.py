#!/usr/bin/python
# Copyright 2019 Northern.tech AS
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
import os
import signal
import subprocess
import time

import pytest

from .. import conftest
from ..common_setup import running_custom_production_setup
from ..common_docker import stop_docker_compose
from ..MenderAPI import authentication, deployments, DeviceAuthV2
from .mendertesting import MenderTesting


class TestDemoArtifact(MenderTesting):
    """A simple class for testing the demo-Artifact upload."""

    # NOTE - The password is set on a per test-basis,
    # as it is generated on the fly by the demo script.
    auth = authentication.Authentication(
        name='mender-demo', username='mender-demo@example.com')
    authv2 = DeviceAuthV2(auth)
    deploy = deployments.Deployments(auth, authv2)

    @pytest.fixture(scope="function")
    def run_demo_script(self, request, exit_cond="Login password:"):
        """Simple fixture which returns a function which runs 'demo up'.
        Afterwards the fixture brings down the docker-compose environment,
        so that each invocation run keeps the environment clean

        :param exit_cond

               Is the string which needs to be present in the output of the demo
               script in order for it to return the process handle to the test
               asking for it. If the string does not exist, the process will block
               indefinitely, and hence the tests employing this fixture will need
               to have a timeout.
        """

        request.addfinalizer(stop_docker_compose)

        def run_demo_script_up(exit_cond=exit_cond):
            test_env = os.environ.copy()
            test_env[
                'DOCKER_COMPOSE_PROJECT_NAME'] = conftest.docker_compose_instance
            test_env['COMPOSE_HTTP_TIMEOUT'] = "1024"
            test_env["DOCKER_CLIENT_TIMEOUT"]= "1024"
            proc = subprocess.Popen(
                [
                    './demo', '--client', '-p',
                    conftest.docker_compose_instance, 'up'
                ],
                cwd="..",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                env=test_env)
            logging.info("run_demo_script_up %s waiting for demo script to be up" % conftest.docker_compose_instance)
            # out = subprocess.check_output("/builds/Northern.tech/Mender/integration/wait-for-all %s" % conftest.docker_compose_instance, shell=True)
            logging.info("run_demo_script_up %s Started the demo script" % conftest.docker_compose_instance)
            password = ""
            for line in iter(proc.stdout.readline, ''):
                logging.info(line)
                if exit_cond in line.strip():
                    if "Encountered errors while bringing up the project" in exit_cond:
                        logging.info("run_demo_script_up %s failed to start" % conftest.docker_compose_instance)
                        pytest.fail("run_demo_script_up %s failed to start 'Encountered errors while bringing up the project'" % conftest.docker_compose_instance)
                    if exit_cond == "Login password:":
                        password = line.split(':')[-1].strip()
                        logging.info('The login password:')
                        logging.info(password)
                        self.auth.password = password
                        assert len(password) == 12
                    break
            return proc

        return run_demo_script_up

    # Give the test a timeframe, as the script might run forever,
    # if something goes awry, or the script is not brought down properly.
    @pytest.mark.timeout(30000)
    @pytest.mark.usefixtures("running_custom_production_setup")
    def test_demo_artifact(self, run_demo_script):
        """Tests that the demo script does indeed upload the demo Artifact to the server."""

        stop_docker_compose()

        logging.info("--------------------------------------------------")
        logging.info("Running test_demo_artifact_upload")
        logging.info("--------------------------------------------------")
        self.demo_artifact_upload(run_demo_script)
        stop_docker_compose()
        self.auth.reset_auth_token()

        logging.info("--------------------------------------------------")
        logging.info("Running test_demo_artifact_installation")
        logging.info("--------------------------------------------------")
        self.demo_artifact_installation(run_demo_script)
        stop_docker_compose()
        self.auth.reset_auth_token()

        logging.info("--------------------------------------------------")
        logging.info("Running test_demo_up_down_up")
        logging.info("--------------------------------------------------")
        self.demo_up_down_up(run_demo_script)
        stop_docker_compose()
        self.auth.reset_auth_token()

    def demo_artifact_upload(self, run_demo_script, exit_cond="Login password:"):
        proc = run_demo_script(exit_cond)
        arts = self.deploy.get_artifacts()
        try:
            assert len(arts) == 1
        except:
            logging.error(str(arts))
            raise
        assert "mender-demo-artifact" in arts[0]['name']
        # Bring down the demo script
        proc.send_signal(signal.SIGTERM)
        proc.wait()
        assert proc.returncode == 0

    def demo_artifact_installation(self, run_demo_script):
        """Tests that the demo-artifact is successfully deployed to a client device."""
        run_demo_script()
        artifacts = self.deploy.get_artifacts(auth_create_new_user=False,expected_count=1) # User should be created by the demo script.
        assert len(artifacts) == 1
        artifact_name = artifacts[0]['name']

        # Trigger the deployment
        devices = self.authv2.get_devices()
        assert len(devices) == 1

        # Accept the device to be updated
        self.authv2.accept_devices(1)
        devices = list(
            set([
                device["id"]
                for device in self.authv2.get_devices_status("accepted")
            ]))
        assert len(devices) == 1

        # Run the deployment.
        deployment_id = self.deploy.trigger_deployment(
            name="Demo artifact deployment",
            artifact_name=artifacts[0]['name'],
            devices=devices)

        # Verify the deployment
        self.deploy.check_expected_status("finished", deployment_id)

    def demo_up_down_up(self, run_demo_script):
        """Test that bringing the demo environment up, then down, then up succeeds"""

        # Upload demo artifact and create demo user
        self.demo_artifact_upload(run_demo_script)

        # Verify that the demo user is still present, when bringing
        # the environment up a second time
        self.demo_artifact_upload(run_demo_script, exit_cond="The user already exists")
        logging.info('Finished')
