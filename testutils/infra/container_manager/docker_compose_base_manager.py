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
import os
import re
import time
import subprocess
import filelock
import logging
import copy
import redo

from .docker_manager import DockerNamespace

logger = logging.getLogger("root")

# Global lock to synchronize calls to docker-compose
docker_lock = filelock.FileLock("docker_lock")


class DockerComposeBaseNamespace(DockerNamespace):
    COMPOSE_FILES_PATH = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    BASE_FILES = []

    def __init__(self, name=None, extra_files=[]):
        DockerNamespace.__init__(self, name)
        self.extra_files = copy.copy(extra_files)

    @property
    def docker_compose_files(self):
        return self.BASE_FILES + self.extra_files

    def teardown(self):
        self._debug_log_containers_logs()
        self._stop_docker_compose()

    def get_mender_clients(self, network="mender"):
        """Returns IP address(es) of mender-client container(s)"""
        clients = [
            ip + ":8822"
            for ip in self.get_ip_of_service("mender-client", network=network)
        ]
        return clients

    def get_mender_gateways(self, network="mender"):
        """Returns IP address(es) of mender-gateway container(s)"""
        clients = [
            ip + ":8822"
            for ip in self.get_ip_of_service("mender-gateway", network=network)
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

    def get_ip_of_service(self, service, network="mender"):
        """Return a list of IP addresseses of `service`. `service` is the same name as
        present in docker-compose files.
        """
        temp = (
            "docker ps -q "
            "--filter label=com.docker.compose.project={project} "
            "--filter label=com.docker.compose.service={service} "
        )
        cmd = temp.format(project=self.name, service=service)

        output = subprocess.check_output(
            cmd + "| xargs -r "
            "docker inspect --format='{{.NetworkSettings.Networks.%s_%s.IPAddress}}'"
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
        cmd = temp.format(project=self.name, service="mender-api-gateway")

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
            gateway = self.get_ip_of_service("mender-api-gateway")

            if len(gateway) != 1:
                continue
            else:
                return gateway[0]
        else:
            assert (
                False
            ), "expected one instance of api-gateway running, but found: {} instance(s)".format(
                len(gateway)
            )

    def restart_service(self, service):
        """Restarts a service."""
        self._docker_compose_cmd(f"up -d --scale {service}=0 {service}")
        self._docker_compose_cmd(f"up -d --scale {service}=1 {service}")

    def get_file(self, container_name, path):
        container_id = super().getid([container_name])
        return super().execute(container_id, ["cat", path])

    def _debug_log_containers_logs(self):
        logs = self._docker_compose_cmd("logs --no-color")
        for line in logs.split("\n"):
            logger.debug(self._re_newlines_sub("", line))

    def _docker_compose_cmd(self, arg_list, env=None):
        """Run docker-compose command using self.docker_compose_files

        It will retry a few times due to https://github.com/opencontainers/runc/issues/1326
        """
        files_args = "".join([" -f %s" % file for file in self.docker_compose_files])

        cmd = "docker-compose -p %s %s %s" % (self.name, files_args, arg_list)

        logger.info("running with: %s" % cmd)

        penv = dict(os.environ)
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
                    self._stop_docker_compose()

            if count < 5:
                logger.info("sleeping %d seconds and retrying" % (count * 30))
                time.sleep(count * 30)

        raise Exception("failed to start docker-compose (called: %s)" % cmd)

    def _stop_docker_compose(self):
        with docker_lock:
            output = subprocess.check_output(
                "docker ps -f name=%s" % self.name, shell=True
            ).decode()
            logger.info("%s: stopping all:\n%s\n" % (self.name, output))

            stop_sleep_seconds = 15
            retry_attempts = 8

            # Take down all docker instances in this namespace.
            # QA-455 special treatment for redis
            while retry_attempts > 0:
                logger.info("qa-455: %s: attempting to shutdown redis" % self.name)
                cmd = (
                    "docker ps -f name=%s | grep -F redis | awk '{print($1);}' | xargs -n1 -I{} docker exec {} redis-cli shutdown"
                    % self.name
                )
                subprocess.run(cmd, check=False, shell=True)
                time.sleep(stop_sleep_seconds)
                output = subprocess.check_output(
                    "docker ps -f name=%s | grep -F redis | wc -l" % self.name,
                    shell=True,
                ).decode()
                output = output.rstrip()
                if int(output) == 0:
                    logger.info("qa-455: %s: stopped redis." % self.name)
                    break

            retry_attempts = 8
            while retry_attempts > 0:
                logger.info(
                    "(attempts left: %d) trying to stop all containers in %s"
                    % (retry_attempts, self.name)
                )
                cmd = "docker ps -q -f name=%s | xargs -r docker stop" % self.name
                logger.info("running %s" % cmd)
                subprocess.run(cmd, check=False, shell=True)
                time.sleep(stop_sleep_seconds)
                cmd = (
                    "docker ps -aq -f name=%s | while read -r; do docker network list -q -f name=%s | xargs -n1 -I{} -r docker network disconnect -f {} $REPLY; done"
                    % (self.name, self.name)
                )
                logger.info("running %s" % cmd)
                output = subprocess.run(
                    cmd,
                    check=False,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                logger.info(
                    "%s disconnecting containers: %s/%s"
                    % (
                        self.name,
                        output.stdout.decode("utf-8").strip(),
                        output.stderr.decode("utf-8").strip(),
                    )
                )

                output = subprocess.check_output(
                    "docker ps -q -f name=%s | wc -l" % self.name, shell=True
                ).decode()
                output = output.rstrip()
                if int(output) == 0:
                    logger.info(
                        "(attempts left: %d) stopped all containers in %s"
                        % (retry_attempts, self.name)
                    )
                    break
                remaining = subprocess.check_output(
                    "docker ps -f name=%s" % self.name, shell=True
                ).decode()
                logger.info(
                    "(attempts left: %d) %d containers remained in %s are: %s"
                    % (retry_attempts, int(output), self.name, remaining)
                )
                retry_attempts = retry_attempts - 1

            output = subprocess.check_output(
                "docker ps -a -f name=%s" % self.name, shell=True
            ).decode()
            logger.info("%s containers to remove: '%s'" % (self.name, output))
            output = subprocess.check_output(
                "docker network list -q -f name=%s | xargs -n1 -r docker network inspect"
                % self.name,
                shell=True,
            ).decode()
            logger.info("qa-455 %s networks to remove: '\n%s\n'" % (self.name, output))

            cmd = "docker ps -aq -f name=%s | xargs -r docker rm -fv" % self.name
            logger.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)

            cmd = (
                "docker network list -q -f name=%s | xargs -r docker network rm"
                % self.name
            )
            logger.info("running %s" % cmd)
            output = subprocess.run(
                cmd,
                check=False,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if output.returncode != 0:
                logger.info(
                    "qa-455 dbg: '%s' rc:%d out/err %s/%s"
                    % (
                        cmd,
                        output.returncode,
                        output.stdout.decode("utf-8").strip(),
                        output.stderr.decode("utf-8").strip(),
                    )
                )
                output = subprocess.check_output(
                    "docker network list -q -f name=%s | xargs -n1 -r docker network inspect"
                    % self.name,
                    shell=True,
                ).decode()
                logger.info(
                    "qa-455 %s networks existing on error rm: '\n%s\n'"
                    % (self.name, output)
                )
                output = subprocess.check_output(
                    "docker ps -aq -f name=%s | xargs -r -n1 docker inspect"
                    % self.name,
                    shell=True,
                ).decode()
                logger.info(
                    "qa-455 %s all containers on error rm: '\n%s\n'"
                    % (self.name, output)
                )

            max_tries = 255
            try_number = 0
            while try_number < max_tries:
                time.sleep(stop_sleep_seconds)
                try_number = try_number + 1
                cmd = (
                    "docker network list -q -f name=%s | xargs -r docker network rm"
                    % self.name
                )
                logger.info(
                    "%s qa-455 dbg: try %d running %s" % (self.name, try_number, cmd)
                )
                output = subprocess.run(
                    cmd,
                    check=False,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if output.returncode == 0:
                    logger.info(
                        "%s qa-455 dbg: try %d rc:%d"
                        % (self.name, try_number, output.returncode)
                    )
                    break
                if output.returncode != 0:
                    logger.info(
                        "%s qa-455 dbg: try %d '%s' rc:%d out/err %s/%s"
                        % (
                            self.name,
                            try_number,
                            cmd,
                            output.returncode,
                            output.stdout.decode("utf-8").strip(),
                            output.stderr.decode("utf-8").strip(),
                        )
                    )
                output = subprocess.check_output(
                    "docker network list -q -f name=%s | xargs -n1 -r docker network inspect"
                    % self.name,
                    shell=True,
                ).decode()
                logger.info(
                    "qa-455 %s try %d networks existing on error rm: '\n%s\n'"
                    % (self.name, try_number, output)
                )
                output = subprocess.check_output(
                    "docker ps -aq | xargs -r -n1 docker inspect",
                    shell=True,
                ).decode()
                logger.info(
                    "qa-455 %s try %d _all_ containers on error rm: '\n%s\n'"
                    % (self.name, try_number, output)
                )


            cmd = (
                "docker network list -q -f name=%s | xargs -r docker network rm"
                % self.name
            )
            logger.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)
