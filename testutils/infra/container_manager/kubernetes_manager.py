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

from kubernetes import client, config
from kubernetes.stream import stream

from .docker_compose_base_manager import DockerComposeBaseNamespace

logger = logging.getLogger("root")

# Global lock to synchronize calls to docker-compose
docker_lock = filelock.FileLock("docker_lock")


class KubernetesNamespace(DockerComposeBaseNamespace):
    namespace = "staging"
    KUBECONFIG = f"{os.getenv('HOME')}/kubeconfig.{namespace}"
    config.load_kube_config(config_file=KUBECONFIG)
    v1 = client.CoreV1Api()

    def setup(self):
        pass

    def execute(self, pod_id: str, cmd: List[str]) -> str:
        """Perform kubectl exec command on given pod. """
        ws_client = stream(
            self.v1.connect_get_namespaced_pod_exec,
            pod_id,
            self.namespace,
            command=cmd,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        ws_client.run_forever(timeout=60)
        if ws_client.returncode != 0:
            raise RuntimeError(f"Kubernetes SDK exec error: {ws_client.read_stderr()}")
        return ws_client.read_all()

    def cmd(self, container_id, docker_cmd, cmd=[]):
        cmd = ["kubectl", docker_cmd] + [str(container_id)] + cmd
        ret = subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return ret.stdout.decode("utf-8").strip()

    def getid(self, filters: List[str]) -> str:
        """Get pod id based on given filters."""
        pod_list = self.v1.list_namespaced_pod(self.namespace)
        pod_id = ""

        for pod in pod_list.items:
            if filters[0] in pod.metadata.name and pod.status.phase == "Running":
                pod_id = pod.metadata.name
        if pod_id == "":
            raise RuntimeError(f"pod id for filters {str(filters)} not found")
        return pod_id

    def get_mender_gateway(self):
        return os.environ.get("GATEWAY_HOSTNAME")


class KubernetesEnterpriseSetupWithGateway(KubernetesNamespace):
    COMPOSE_FILES_PATH = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    MENDER_GATEWAY_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.mender-gateway.commercial.yml",
        COMPOSE_FILES_PATH + "/extra/mender-gateway/docker-compose.test.yml",
    ]
    MENDER_GATEWAY_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/extra/mender-gateway/docker-compose.client.yml",
    ]
    MT_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]

    def __init__(self, name, num_clients=1):
        self.num_clients = num_clients
        if self.num_clients == 0:
            KubernetesNamespace.__init__(self, name, self.MENDER_GATEWAY_FILES)
        else:
            KubernetesNamespace.__init__(
                self, name, self.MENDER_GATEWAY_FILES + self.MENDER_GATEWAY_CLIENT_FILES
            )

    def _wait_for_containers(self):
        self.wait_until_healthy(self.name, timeout=60 * 5)

    def new_tenant_client(self, name: str, tenant_token: str):
        if not self.MT_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_CLIENT_FILES
        logger.info("creating client connected to tenant: " + tenant_token)
        self._docker_compose_cmd(
            f"run -d --name={self.name}_{name} mender-client",
            env={
                "SERVER_URL": f"https://{self.get_mender_gateway()}",
                "TENANT_TOKEN": tenant_token,
            },
        )
        time.sleep(30)

    def start_tenant_mender_gateway(self, tenant_token: str):
        self._docker_compose_cmd(
            "up -d --scale mender-gateway=1 --scale mender-client=0",
            env={
                "SERVER_URL": f"https://{self.get_mender_gateway()}",
                "TENANT_TOKEN": tenant_token,
            },
        )
        time.sleep(30)


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

    def get_virtual_network_host_ip(self):
        """Returns the IP of the host running the Docker containers"""
        temp = (
            "docker ps -q "
            "--filter label=com.docker.compose.project={project} "
            "--filter label=com.docker.compose.service={service}"
        )
        cmd = temp.format(project=self.name, service="mender-client")

        output = subprocess.check_output(
            cmd + "| head -n1 | xargs -r "
            "docker inspect --format='{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'",
            shell=True,
        )
        return output.decode().split()[0]


class KubernetesEnterpriseMonitorCommercialSetup(KubernetesEnterpriseSetup):
    COMPOSE_FILES_PATH = DockerComposeBaseNamespace.COMPOSE_FILES_PATH
    MT_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.monitor-client.commercial.yml",
    ]


def isK8S() -> bool:
    return bool(os.environ.get("K8S"))
