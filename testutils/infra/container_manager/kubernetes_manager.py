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
import filelock
import logging
import os
import subprocess
import time
from typing import List

from .docker_compose_base_manager import DockerComposeBaseNamespace

logger = logging.getLogger("root")

# Global lock to synchronize calls to docker-compose
docker_lock = filelock.FileLock("docker_lock")


class KubernetesNamespace(DockerComposeBaseNamespace):
    def setup(self):
        pass

    def execute(self, container_id: str, cmd: List[str]) -> str:
        cmd = ["kubectl", "exec", "{}".format(container_id), "--"] + cmd
        ret = subprocess.check_output(cmd).decode("utf-8").strip()
        return ret

    def cmd(self, container_id, docker_cmd, cmd=[]):
        cmd = ["kubectl", docker_cmd] + [str(container_id)] + cmd
        ret = subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return ret.stdout.decode("utf-8").strip()

    def getid(self, filters):
        filters = ["grep {}".format(f) for f in filters]
        cmd = (
            "kubectl get pods | "
            + " | ".join(filters)
            + " | awk '{print $1}' | head -n 1"
        )
        ret = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        if ret == "":
            raise RuntimeError("container id for {} not found".format(str(filters)))
        return ret

    def get_mender_gateway(self):
        return os.environ.get("GATEWAY_HOSTNAME")


class KubernetesEnterpriseSetup(KubernetesNamespace):
    COMPOSE_FILES_PATH = DockerComposeBaseNamespace.COMPOSE_FILES_PATH
    MT_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]
    MT_DOCKER_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.docker-client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]

    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        self.extra_files = []
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            KubernetesNamespace.__init__(self, name)

    def new_tenant_client(self, name, tenant):
        if not self.MT_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_CLIENT_FILES
        logger.info("creating client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={
                "SERVER_URL": "https://%s" % self.get_mender_gateway(),
                "TENANT_TOKEN": "%s" % tenant,
            },
        )
        time.sleep(45)

    def new_tenant_docker_client(self, name, tenant):
        if not self.MT_DOCKER_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_DOCKER_CLIENT_FILES
        logger.info("creating docker client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={
                "SERVER_URL": "https://%s" % self.get_mender_gateway(),
                "TENANT_TOKEN": "%s" % tenant,
            },
        )
        time.sleep(5)


class KubernetesEnterpriseMonitorCommercialSetup(KubernetesEnterpriseSetup):
    COMPOSE_FILES_PATH = DockerComposeBaseNamespace.COMPOSE_FILES_PATH
    MT_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.monitor-client.commercial.yml",
    ]


def isK8S() -> bool:
    return bool(os.environ.get("K8S"))
