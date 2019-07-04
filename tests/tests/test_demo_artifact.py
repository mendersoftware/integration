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

import pytest
import requests

import conftest
from common_docker import *
from MenderAPI import *
from mendertesting import MenderTesting


class TestDemoArtifact(MenderTesting):
    """A simple class for testing the demo-Artifact upload."""

    # NOTE - The password is set on a per test-basis,
    # as it is generated on the fly by the demo script.
    auth = authentication.Authentication(
        username='mender-demo', email='mender-demo@example.com')
    authv2 = auth_v2_mod.DeviceAuthV2(auth)
    deploy = deployments.Deployments(auth, authv2)

    @pytest.fixture(scope="function")
    def run_demo_script(self, request):
        """Simple fixture which returns a function which runs 'demo up'.
        Afterwards the fixture brings down the docker-compose environment,
        so that each invocation run keeps the environment clean."""

        request.addfinalizer(stop_docker_compose)

        def run_demo_script_up():
            test_env = os.environ.copy()
            test_env[
                'DOCKER_COMPOSE_PROJECT_NAME'] = conftest.docker_compose_instance
            proc = subprocess.Popen(
                [
                    './demo', '--client', '-p',
                    conftest.docker_compose_instance, 'up'
                ],
                cwd="..",
                stdout=subprocess.PIPE,
                env=test_env)
            logging.info('Started the demo script')
            password = ""
            time.sleep(60)
            for line in iter(proc.stdout.readline, ''):
                logging.info(line)
                if "Login password:" in line.strip():
                    password = line[-13:-1]
                    logging.info('The login password:')
                    logging.info(password)
                    self.auth.password = password
                    assert len(password) == 12
                    break
            return proc

        return run_demo_script_up

    # Give the test a timeframe, as the script might run forever,
    # if something goes awry, or the script is not brought down properly.
    @pytest.mark.timeout(3000)
    @pytest.mark.skip(reason="Seems to cause unknown test failures in other tests.")
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

    def demo_artifact_upload(self, run_demo_script):
        proc = run_demo_script()
        arts = self.deploy.get_artifacts()
        try:
            assert len(arts) == 1
        except:
            logging.error(str(arts))
            raise
        assert "mender-demo-artifact" in arts[0]['name']
        # Emulate ctrl-c exit
        proc.send_signal(signal.SIGINT)
        proc.wait()
        assert proc.returncode == 0

    def demo_artifact_installation(self, run_demo_script):
        """Tests that the demo-artifact is successfully deployed to a client device."""
        run_demo_script()
        artifacts = self.deploy.get_artifacts(auth_create_new_user=False) # User should be created by the demo script.
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
        self.demo_artifact_upload(run_demo_script)
        self.demo_artifact_upload(run_demo_script)
        logging.info('Finished')
