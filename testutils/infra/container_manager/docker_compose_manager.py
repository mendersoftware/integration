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
import time
import socket
import subprocess
import logging
from testutils.common import wait_until_healthy

from .docker_compose_base_manager import DockerComposeBaseNamespace, docker_lock

logger = logging.getLogger("root")


class DockerComposeNamespace(DockerComposeBaseNamespace):
    COMPOSE_FILES_PATH = DockerComposeBaseNamespace.COMPOSE_FILES_PATH
    BASE_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.yml",
        COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml",
        COMPOSE_FILES_PATH + "/docker-compose.testing.yml",
        COMPOSE_FILES_PATH + "/extra/integration-testing/docker-compose.yml",
    ]
    QEMU_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
    ]
    MONITOR_CLIENT_COMMERCIAL_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.monitor-client.commercial.yml",
    ]
    QEMU_CLIENT_ROFS_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.client.rofs.yml",
    ]
    DOCKER_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.docker-client.yml",
    ]
    LEGACY_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/tests/legacy-v1-client.yml",
        COMPOSE_FILES_PATH + "/storage-proxy/docker-compose.storage-proxy.yml",
        COMPOSE_FILES_PATH + "/storage-proxy/docker-compose.storage-proxy.demo.yml",
    ]
    LEGACY_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/tests/legacy-v1-client.yml",
        COMPOSE_FILES_PATH + "/storage-proxy/docker-compose.storage-proxy.yml",
        COMPOSE_FILES_PATH + "/storage-proxy/docker-compose.storage-proxy.demo.yml",
    ]
    SIGNED_ARTIFACT_CLIENT_FILES = [
        COMPOSE_FILES_PATH
        + "/extra/signed-artifact-client-testing/docker-compose.signed-client.yml"
    ]
    SHORT_LIVED_TOKEN_FILES = [
        COMPOSE_FILES_PATH
        + "/extra/expired-token-testing/docker-compose.short-token.yml"
    ]
    FAILOVER_SERVER_FILES = [
        COMPOSE_FILES_PATH
        + "/extra/failover-testing/docker-compose.failover-server.yml"
    ]
    ENTERPRISE_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml",
        COMPOSE_FILES_PATH + "/docker-compose.testing.enterprise.yml",
    ]
    MT_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]
    MT_DOCKER_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.docker-client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]
    MTLS_FILES = [
        COMPOSE_FILES_PATH + "/extra/mtls/docker-compose.mtls-ambassador-test.yml",
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]
    SMTP_MOCK_FILES = [
        COMPOSE_FILES_PATH + "/extra/smtp-testing/workflows-worker-smtp-mock.yml",
        COMPOSE_FILES_PATH
        + "/extra/recaptcha-testing/tenantadm-test-recaptcha-conf.yml",
        COMPOSE_FILES_PATH + "/extra/smtp-testing/smtp.mock.yml",
    ]
    COMPAT_FILES = [
        COMPOSE_FILES_PATH + "/extra/integration-testing/docker-compose.compat.yml"
    ]
    MENDER_2_5_FILES = [
        COMPOSE_FILES_PATH + "/extra/integration-testing/docker-compose.mender.2.5.yml"
    ]

    def setup(self):
        self._docker_compose_cmd("up -d")

    def _wait_for_containers(self):
        wait_until_healthy(self.name, timeout=60 * 5)

    def teardown_exclude(self, exclude=[]):
        """
        Take down all docker instances in this namespace, except for 'exclude'd container names.
        'exclude' doesn't need exact names, it's a verbatim grep regex.
        """
        with docker_lock:
            cmd = "docker ps -aq -f name=%s  | xargs -r docker rm -fv" % self.name

            # exclude containers by crude grep -v and awk'ing out the id
            # that's because docker -f allows only simple comparisons, no negations/logical ops
            if len(exclude) != 0:
                cmd_excl = 'grep -vE "(' + " | ".join(exclude) + ')"'
                cmd_id = "awk 'NR>1 {print $1}'"
                cmd = "docker ps -a -f name=%s | %s | %s | xargs -r docker rm -fv" % (
                    self.name,
                    cmd_excl,
                    cmd_id,
                )

            logger.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)

            # if we're preserving some containers, don't destroy the network (will error out on exit)
            if len(exclude) == 0:
                cmd = (
                    "docker network list -q -f name=%s | xargs -r docker network rm"
                    % self.name
                )
                logger.info("running %s" % cmd)
                subprocess.check_call(cmd, shell=True)


class DockerComposeStandardSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=1):
        self.num_clients = num_clients
        if self.num_clients == 0:
            DockerComposeNamespace.__init__(self, name)
        else:
            DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_FILES)

    def setup(self):
        self._docker_compose_cmd("up -d --scale mender-client=%d" % self.num_clients)


class DockerComposeMonitorCommercialSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(
                self, name, self.ENTERPRISE_FILES + self.SMTP_MOCK_FILES
            )

    def setup(self, recreate=True, env=None):
        cmd = "up -d"
        if not recreate:
            cmd += " --no-recreate"
        self._docker_compose_cmd(cmd, env=env)
        self._wait_for_containers()

    def new_tenant_client(self, name, tenant):
        if not self.MONITOR_CLIENT_COMMERCIAL_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MONITOR_CLIENT_COMMERCIAL_FILES
        logger.info("creating client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(45)

    def new_tenant_docker_client(self, name, tenant):
        if not self.MT_DOCKER_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_DOCKER_CLIENT_FILES
        logger.info("creating docker client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(5)


class DockerComposeDockerClientSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(self, name, self.DOCKER_CLIENT_FILES)


class DockerComposeRofsClientSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_ROFS_FILES)


class DockerComposeLegacyClientSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(self, name, self.LEGACY_CLIENT_FILES)


class DockerComposeSignedArtifactClientSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(
            self, name, self.QEMU_CLIENT_FILES + self.SIGNED_ARTIFACT_CLIENT_FILES
        )


class DockerComposeShortLivedTokenSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(
            self, name, self.QEMU_CLIENT_FILES + self.SHORT_LIVED_TOKEN_FILES
        )


class DockerComposeFailoverServerSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(
            self, name, self.QEMU_CLIENT_FILES + self.FAILOVER_SERVER_FILES
        )


class DockerComposeEnterpriseSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(self, name, self.ENTERPRISE_FILES)

    def setup(self, recreate=True, env=None):
        cmd = "up -d"
        if not recreate:
            cmd += " --no-recreate"
        self._docker_compose_cmd(cmd, env=env)
        self._wait_for_containers()

    def new_tenant_client(self, name, tenant):
        if not self.MT_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_CLIENT_FILES
        logger.info("creating client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(45)

    def new_tenant_docker_client(self, name, tenant):
        if not self.MT_DOCKER_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_DOCKER_CLIENT_FILES
        logger.info("creating docker client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(5)


class DockerComposeEnterpriseSignedArtifactClientSetup(DockerComposeEnterpriseSetup):
    def new_tenant_client(self, name, tenant):
        if not self.MT_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_CLIENT_FILES
            self.extra_files += self.SIGNED_ARTIFACT_CLIENT_FILES
        logger.info("creating client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(45)


class DockerComposeEnterpriseShortLivedTokenSetup(DockerComposeEnterpriseSetup):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(
                self, name, self.ENTERPRISE_FILES + self.SHORT_LIVED_TOKEN_FILES
            )


class DockerComposeEnterpriseLegacyClientSetup(DockerComposeEnterpriseSetup):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(
                self, name, self.ENTERPRISE_FILES + self.LEGACY_CLIENT_FILES
            )


class DockerComposeEnterpriseRofsClientSetup(DockerComposeEnterpriseSetup):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(
                self, name, self.ENTERPRISE_FILES + self.QEMU_CLIENT_ROFS_FILES
            )


class DockerComposeEnterpriseDockerClientSetup(DockerComposeEnterpriseSetup):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(
                self, name, self.ENTERPRISE_FILES + self.MT_DOCKER_CLIENT_FILES
            )

    def setup(self):
        compose_args = "up -d --scale mender-client=0"
        self._docker_compose_cmd(compose_args)

    def new_tenant_docker_client(self, name, tenant):
        logger.info("creating docker client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "up -d --scale mender-client=1", env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(5)


class DockerComposeCompatibilitySetup(DockerComposeNamespace):
    def __init__(self, name, enterprise=False):
        self._enterprise = enterprise
        extra_files = self.COMPAT_FILES
        if self._enterprise:
            extra_files += self.ENTERPRISE_FILES
        super().__init__(name, extra_files)

    def client_services(self):
        services = self._docker_compose_cmd("ps --service").split()
        clients = []
        for service in services:
            if service.startswith("mender-client"):
                clients.append(service)
        return clients

    def setup(self):
        compose_args = "up -d " + " ".join(
            ["--scale %s=0" % service for service in self.client_services()]
        )
        self._docker_compose_cmd(compose_args)

    def populate_clients(self, name=None, tenant_token="", replicas=1):
        client_services = self.client_services()
        compose_cmd = "run -d"
        if tenant_token != "":
            compose_cmd += " -e TENANT_TOKEN={tkn}".format(tkn=tenant_token)
        if name is not None:
            compose_cmd += " --name '{name}'".format(name=name)

        compose_cmd += " {service}"

        for i in range(replicas):
            for service in client_services:
                self._docker_compose_cmd(compose_cmd.format(service=service))

    def get_mender_clients(self):
        cmd = [
            "docker",
            "ps",
            "--filter=label=com.docker.compose.project=" + self.name,
            '--format={{.Label "com.docker.compose.service"}}',
        ]

        services = subprocess.check_output(cmd).decode().split()
        clients = []
        for service in services:
            if service.startswith("mender-client"):
                clients.append(service)

        addrs = []
        for client in clients:
            for ip in self.get_ip_of_service(client):
                addrs.append(ip + ":8822")

        return addrs


class DockerComposeMTLSSetup(DockerComposeNamespace):
    def __init__(self, name):
        extra_files = self.MTLS_FILES + self.ENTERPRISE_FILES
        super().__init__(name, extra_files)

    def setup(self):
        host_ip = socket.gethostbyname(socket.gethostname())
        self._docker_compose_cmd(
            "up -d --scale mtls-ambassador=0 --scale mender-client=0",
            env={"HOST_IP": host_ip},
        )
        self._wait_for_containers()

    def start_api_gateway(self):
        self._docker_compose_cmd("scale mender-api-gateway=1")

    def stop_api_gateway(self):
        self._docker_compose_cmd("scale mender-api-gateway=0")

    def start_mtls_ambassador(self):
        self._docker_compose_cmd(
            "up -d --scale mtls-ambassador=1 --scale mender-client=0"
        )
        self._wait_for_containers()

    def new_mtls_client(self, name, tenant):
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        logger.info("creating client connected to tenant: " + tenant)
        time.sleep(45)


class DockerComposeMenderClient_2_5(DockerComposeCompatibilitySetup):
    """
    Setup is identical to DockerComposeCompatiblitySetup but excluding images
    without mender-connect.
    """

    def __init__(self, name, enterprise=False):
        self._enterprise = enterprise
        extra_files = self.MENDER_2_5_FILES
        if self._enterprise:
            extra_files += self.ENTERPRISE_FILES
        super(DockerComposeCompatibilitySetup, self).__init__(
            name, extra_files=extra_files
        )

    def new_tenant_client(self, name, tenant):
        logger.info("creating client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client-2-5" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(45)


class DockerComposeCustomSetup(DockerComposeNamespace):
    def __init__(self, name):
        DockerComposeNamespace.__init__(self, name)

    def setup(self):
        pass
