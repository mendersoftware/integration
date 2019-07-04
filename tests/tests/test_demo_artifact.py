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
import re

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
    demoauth = authentication.Authentication(
        username='mender-demo', email='mender-demo@example.com')
    demoauthv2 = auth_v2_mod.DeviceAuthV2(demoauth)
    demodeploy = deployments.Deployments(demoauth, demoauthv2)

    @pytest.fixture(scope="function")
    def run_demo_script(self, request):
        """Simple fixture which returns a function which runs 'demo up'.
        Afterwards the fixture brings down the docker-compose environment,
        so that each invocation run keeps the environment clean."""
        self.demoauth.reset_auth_token()

        request.addfinalizer(stop_docker_compose)
        procs = []

        def maybe_kill_proc():
            for proc in procs:
                if proc.poll() == None:
                    proc.kill()

        request.addfinalizer(maybe_kill_proc)

        def run_demo_script_up():
            test_env = os.environ.copy()
            test_env[
                'DOCKER_COMPOSE_PROJECT_NAME'] = conftest.docker_compose_instance
            proc = subprocess.Popen(
                ['./demo', '--client', 'up'],
                cwd="..",
                stdout=subprocess.PIPE,
                env=test_env)
            procs.append(proc)
            logging.info('Started the demo script')
            password = ""
            time.sleep(60)
            for line in iter(proc.stdout.readline, ''):
                logging.info(line)
                if "Login password:" in line.strip():
                    password = re.search("Login password: .*([^ ]{12})",
                                         line).group(1)
                    logging.info('The login password:')
                    logging.info(password)
                    self.demoauth.password = password
                    assert len(password) == 12
                    break
            # Make sure that the demo script has not errored out,
            # or errored out with a nonzero error
            logging.info("The demo password is: %s\n" % password)
            assert proc.poll() == None or proc.returncode == 0
            return proc

        return run_demo_script_up

    def demo_artifact_upload(self, run_demo_script):
        proc = run_demo_script()
        assert len(self.demoauth.password) == 12, \
            "expected password of length 12, got: %s" % self.demoauth.password
        arts = self.demodeploy.get_artifacts()
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

    def test_demo_artifact_installation(self, run_demo_script):
        """Tests that the demo-artifact is successfully deployed to a client device."""
        stop_docker_compose()
        self.demoauth.reset_auth_token()
        run_demo_script()
        assert len(self.demoauth.password) == 12, \
            "expected password of length 12, got: %s" % self.demoauth.password
        artifacts = self.demodeploy.get_artifacts(
            auth_create_new_user=False
        )  # User should be created by the demo script.
        assert len(
            artifacts) == 1, "Server wrong number of artifacts: %s" % artifacts
        artifact_name = artifacts[0]['name']

        # Trigger the deployment
        devices = self.demoauthv2.get_devices()
        assert len(devices) == 1

        # Accept the device to be updated
        self.demoauthv2.accept_devices(1)
        devices = list(
            set([
                device["id"]
                for device in self.demoauthv2.get_devices_status("accepted")
            ]))
        assert len(devices) == 1

        # Run the deployment.
        deployment_id = self.demodeploy.trigger_deployment(
            name="Demo artifact deployment",
            artifact_name=artifacts[0]['name'],
            devices=devices)

        # Verify the deployment
        self.demodeploy.check_expected_status("finished", deployment_id)

    def test_demo_up_down_up(self, run_demo_script):
        """Test that bringing the demo environment up, then down, then up succeeds"""
        stop_docker_compose()
        self.demoauth.reset_auth_token()
        self.demo_artifact_upload(run_demo_script)
        assert len(self.demoauth.password) == 12, \
            "expected password of length 12, got: %s" % self.demoauth.password
        # Since the docker-compose project has not been removed
        # a user already exists in the useradm container.
        # Thus the demo script returns a 0
        proc = run_demo_script()
        proc.wait()
        assert proc.returncode == 0
