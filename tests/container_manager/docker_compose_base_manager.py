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
import re
import time
import subprocess
import filelock
import logging
import copy
import warnings

import redo
import requests
from urllib3.exceptions import InsecureRequestWarning

from testutils.infra.container_manager.docker_manager import DockerNamespace
from testutils.api.client import GATEWAY_HOSTNAME as _GATEWAY_HOSTNAME

logger = logging.getLogger("root")

# Global lock to synchronize calls to docker-compose
docker_lock = filelock.FileLock("docker_lock")


class DockerComposeBaseNamespace(DockerNamespace):
    # Repo root: this module lives at tests/container_manager/, so two levels up.
    COMPOSE_FILES_PATH = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    BASE_FILES = []

    # How long 'up --wait' is given for every container to report healthy. Used
    # to live on testutils' BaseContainerManagerNamespace, which this repo no
    # longer forks.
    wait_healthy_timeout = 300

    # Traefik routes on the Host header and we address it by container IP, so
    # every request has to carry this explicitly. Single source of truth lives in
    # testutils.api.client; exposed here so callers holding a container manager
    # do not need a second import.
    GATEWAY_HOSTNAME = _GATEWAY_HOSTNAME

    def __init__(self, name=None, extra_files=[]):
        DockerNamespace.__init__(self, name)
        self.extra_files = copy.copy(extra_files)

    @property
    def docker_compose_files(self):
        return self.BASE_FILES + self.extra_files

    @property
    def compose_env(self):
        """Environment applied to every compose command for this namespace.

        For values that have to be identical across up, down and config -- the
        failover backend's MENDER_HOSTNAME, for instance, which selects the
        hostname its routers match on. A per-call 'env' still takes precedence.
        """
        return {}

    @property
    def network_name(self):
        """Name docker gives this namespace's default network."""
        return "%s_default" % self.name

    def teardown(self):
        self._debug_log_containers_logs()
        self._stop_docker_compose()

    def get_mender_clients(
        self, network="default", client_service_name="mender-client"
    ):
        """Returns IP address(es) of mender-client container(s)"""
        clients = [
            ip + ":8822"
            for ip in self.get_ip_of_service(
                service=client_service_name, network=network
            )
        ]
        return clients

    def get_mender_client_by_container_name(self, image_name):
        cmd = (
            "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' %s_%s"
            % (self.name, image_name)
        )
        output = subprocess.check_output(cmd, shell=True)
        return output.decode().strip() + ":8822"

    _re_newlines_sub = re.compile(r"[\r\n]*").sub

    def get_ip_of_service(self, service, network="default"):
        """Return a list of IP addresseses of `service`. `service` is the same name as
        present in docker-compose files.
        """
        temp = (
            "docker ps -q "
            "--filter label=com.docker.compose.project={project} "
            "--filter label=com.docker.compose.service={service} "
        )
        cmd = temp.format(project=self.name, service=service)

        # 'index' rather than dotted field access: a Go template cannot parse a
        # field name containing '-', which a project name may well have.
        output = subprocess.check_output(
            cmd + "| xargs -r "
            "docker inspect --format='{{ (index .NetworkSettings.Networks \"%s_%s\").IPAddress }}'"
            % (self.name, network),
            shell=True,
        )

        return output.decode().split()

    def get_logs_of_service(self, service):
        """Return logs of service"""
        return self._docker_compose_cmd("logs %s" % service)

    def get_virtual_network_host_ip(self):
        """Returns the IP of the host running the Docker containers"""
        temp = (
            "docker ps -q "
            "--filter label=com.docker.compose.project={project} "
            "--filter label=com.docker.compose.service={service}"
        )
        cmd = temp.format(project=self.name, service="traefik")

        output = subprocess.check_output(
            cmd + "| head -n1 | xargs -r "
            "docker inspect --format='{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'",
            shell=True,
        )
        return output.decode().split()[0]

    def get_mender_gateway(self):
        """Returns IP address of mender-api-gateway service
        Has internal retry - upon setup 'up', the gateway
        will not be available for a while.
        """
        for _ in redo.retrier(attempts=10, sleeptime=1):
            gateway = self.get_ip_of_service("traefik")

            if len(gateway) != 1:
                continue
            else:
                return gateway[0]
        else:
            assert (
                False
            ), "expected one instance of api-gateway running, but found: {} instance(s) for project {}".format(
                len(gateway), self.name
            )

    # An unauthenticated GET on the login route answers with one of these once
    # the ingress routes and useradm's HTTP server is listening.
    _READY_STATUS_CODES = (200, 401, 405)

    def wait_for_backend_ready(self, attempts=60, sleeptime=2):
        """Block until the ingress routes and useradm answers HTTP.

        mender-server defines healthchecks only on traefik, mongo, nats and s3,
        so 'up --wait' returns while the Go services are still binding their
        ports. Without this the first API call of a test races service startup.
        """
        url = "https://%s/api/management/v1/useradm/auth/login" % (
            self.get_mender_gateway()
        )

        def _check_ready():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=InsecureRequestWarning)
                r = requests.get(
                    url,
                    headers={"Host": self.GATEWAY_HOSTNAME},
                    verify=False,
                    timeout=10,
                )
            if r.status_code not in self._READY_STATUS_CODES:
                raise ValueError("backend not ready yet, status: %d" % r.status_code)
            return True

        logger.info("waiting for the backend to become ready")
        return redo.retry(
            _check_ready,
            attempts=attempts,
            sleeptime=sleeptime,
            max_sleeptime=sleeptime,
            sleepscale=1,
        )

    def _docker_compose_up(self, extra_args="", env=None, wait_ready=True):
        # --pull missing only reaches the registry when the image is absent
        # locally, so this costs nothing on a warm cache. A plain 'compose pull'
        # per environment would be ~20 manifest requests x every test, which at
        # this suite's size runs into registry rate limits.
        # --no-build turns a missing image into a hard error instead of silently
        # building it from mender-server's build: stanzas.
        cmd = (
            f"up -d --wait --wait-timeout {self.wait_healthy_timeout}"
            f" --pull missing --no-build --quiet-pull"
        )
        if extra_args:
            cmd += f" {extra_args}"
        output = self._docker_compose_cmd(cmd, env=env)
        if wait_ready:
            self.wait_for_backend_ready()
        return output

    def restart_service(self, service):
        """Restarts a service."""
        self._docker_compose_cmd(f"up -d --scale {service}=0 {service}")
        # Scaling a single service back up says nothing about the rest of the
        # stack, which is already running.
        self._docker_compose_up(f"--scale {service}=1 {service}", wait_ready=False)

    def get_file(self, service, path):
        container_id = super().getid(service)
        return super().execute(container_id, ["cat", path])

    def _debug_log_containers_logs(self):
        logs = self._docker_compose_cmd("logs --no-color")
        for line in logs.split("\n"):
            logger.debug(self._re_newlines_sub("", line))

    def _docker_compose_cmd(self, arg_list, env=None, fail_early=True):
        """Run docker-compose command using self.docker_compose_files

        It will retry a few times due to https://github.com/opencontainers/runc/issues/1326
        """
        files_args = "".join([" -f %s" % file for file in self.docker_compose_files])

        # Pin the project directory to the repo root. Compose otherwise derives it
        # from the first -f file (now under tests/compose/), which would resolve
        # every relative bind mount and the root .env against the wrong directory.
        cmd = "docker compose -p %s --project-directory %s %s %s" % (
            self.name,
            self.COMPOSE_FILES_PATH,
            files_args,
            arg_list,
        )

        logger.info("running with: %s" % cmd)

        penv = dict(os.environ)
        # The traefik Docker-provider constraint in docker-compose.testing.yml
        # interpolates this, and it is not set when compose gets -p on the CLI.
        penv["COMPOSE_PROJECT_NAME"] = self.name
        penv.update(self.compose_env)
        if env:
            penv.update(env)

        for count in range(1, 6):
            with docker_lock:
                try:
                    return subprocess.check_output(
                        cmd, stderr=subprocess.STDOUT, shell=True, env=penv
                    ).decode("utf-8", "ignore")

                except subprocess.CalledProcessError as e:
                    logger.info(
                        'failed to run "%s": error follows:\n%s' % (cmd, e.output)
                    )
                    if fail_early:
                        self._stop_docker_compose()

            if count < 5:
                logger.info("sleeping %d seconds and retrying" % (count * 30))
                time.sleep(count * 30)

        raise Exception("failed to start docker compose (called: %s)" % cmd)

    def _stop_docker_compose(self):
        stop_sleep_seconds = 15
        retry_attempts = 8

        # Take down all docker instances in this namespace.
        while retry_attempts > 0:
            logger.info(
                "(attempts left: %d) trying to stop all containers in %s"
                % (retry_attempts, self.name)
            )
            try:
                self._docker_compose_cmd("down -v --remove-orphans", fail_early=False)
                break
            except Exception as e:
                time.sleep(stop_sleep_seconds)
                logger.error(e)
                retry_attempts = retry_attempts - 1
