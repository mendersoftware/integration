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

import logging
import os
import socket
import subprocess
import time

from integration_testutils.common import wait_until_healthy

from .docker_compose_base_manager import DockerComposeBaseNamespace, docker_lock

logger = logging.getLogger("root")


class DockerComposeNamespace(DockerComposeBaseNamespace):
    COMPOSE_FILES_PATH = DockerComposeBaseNamespace.COMPOSE_FILES_PATH
    # Please note that the compose files sequence matters!
    # The same parameter in different files can have different values and
    # a value from the last yaml will be used.
    BASE_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.yml",
        COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml",
        COMPOSE_FILES_PATH + "/docker-compose.demo.yml",
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
    QEMU_CLIENT_ROFS_COMMERCIAL_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.client.rofs.commercial.yml",
    ]
    DOCKER_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.docker-client.addons.yml",
    ]
    LEGACY_V1_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/extra/legacy-clients-testing/legacy-v1-client.yml",
        COMPOSE_FILES_PATH + "/storage-proxy/docker-compose.storage-proxy.yml",
        COMPOSE_FILES_PATH + "/storage-proxy/docker-compose.storage-proxy.testing.yml",
    ]
    LEGACY_V3_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/extra/legacy-clients-testing/legacy-v3-client.yml",
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
        COMPOSE_FILES_PATH + "/docker-compose.docker-client.addons.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]
    MTLS_FILES = [
        COMPOSE_FILES_PATH + "/extra/mtls/docker-compose.mtls-test.yml",
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]
    SMTP_MOCK_FILES = [
        COMPOSE_FILES_PATH + "/extra/smtp-testing/workflows-worker-smtp-mock.yml",
        COMPOSE_FILES_PATH
        + "/extra/recaptcha-testing/tenantadm-test-recaptcha-conf.yml",
        COMPOSE_FILES_PATH + "/extra/smtp-testing/smtp.mock.yml",
    ]

    def setup(self):
        self._docker_compose_cmd("up -d")
        self._wait_for_containers()

    def _wait_for_containers(self):
        wait_until_healthy(self.name, timeout=60 * 5)

    def teardown_exclude(self, exclude=[]):
        """
        Take down all docker instances in this namespace, except for 'exclude'd container names.
        'exclude' doesn't need exact names, it's a verbatim grep regex.
        """
        with docker_lock:
            cmd = "down --remove-orphans"
            if len(exclude) > 0:
                # Filter exclude from all services in composition
                services = self._docker_compose_cmd("config --services").split()
                rm_services = list(filter(lambda svc: svc not in exclude, services))
                svc_args = " ".join(rm_services)

                if svc_args != "":
                    # Only if we're excluding services do we use 'rm'
                    # Otherwise default to 'down --remove-orphans'
                    cmd = f"rm -sf {svc_args}"

            self._docker_compose_cmd(cmd)


class DockerComposeStandardSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=1):
        self.num_clients = num_clients
        super().__init__(name, self.QEMU_CLIENT_FILES)

    def setup(self):
        self._docker_compose_cmd("up -d --scale mender-client=%d" % self.num_clients)
        self._wait_for_containers()


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


class DockerComposeLegacyV1ClientSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(self, name, self.LEGACY_V1_CLIENT_FILES)


class DockerComposeLegacyV3ClientSetup(DockerComposeNamespace):
    def __init__(
        self, name,
    ):
        DockerComposeNamespace.__init__(self, name, self.LEGACY_V3_CLIENT_FILES)

    def get_mender_clients(self, network="mender"):
        clients = [
            ip + ":8822"
            for ip in self.get_ip_of_service(
                service="mender-client-3-6", network=network
            )
        ]
        return clients


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
        if any(
            ["client" in compose_file for compose_file in self.docker_compose_files]
        ):
            cmd += " --scale mender-client=%d" % self.num_clients
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


class DockerComposeEnterpriseLegacyV1ClientSetup(DockerComposeEnterpriseSetup):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(
                self, name, self.ENTERPRISE_FILES + self.LEGACY_V1_CLIENT_FILES
            )


class DockerComposeEnterpriseLegacyV3ClientSetup(DockerComposeEnterpriseSetup):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(self, name, self.ENTERPRISE_FILES)

    def new_tenant_client(self, name, tenant):
        if not self.LEGACY_V3_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.LEGACY_V3_CLIENT_FILES
        logger.info("creating Mender v3.6 client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            f"run -d --name={self.name}_{name} mender-client-3-6",
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(45)

    def get_mender_clients(self, network="mender"):
        clients = [
            ip + ":8822"
            for ip in self.get_ip_of_service(
                service="mender-client-3-6", network=network
            )
        ]
        return clients


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


class DockerComposeEnterpriseRofsCommercialClientSetup(DockerComposeEnterpriseSetup):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            DockerComposeNamespace.__init__(
                self,
                name,
                self.ENTERPRISE_FILES + self.QEMU_CLIENT_ROFS_COMMERCIAL_FILES,
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
        self._wait_for_containers()

    def new_tenant_docker_client(self, name, tenant):
        logger.info("creating docker client connected to tenant: " + tenant)
        self._docker_compose_cmd(
            "up -d --scale mender-client=1", env={"TENANT_TOKEN": "%s" % tenant},
        )
        time.sleep(5)


class DockerComposeMTLSSetup(DockerComposeNamespace):
    def __init__(self, name):
        extra_files = self.MTLS_FILES + self.ENTERPRISE_FILES
        super().__init__(name, extra_files)

    def setup(self):
        host_ip = socket.gethostbyname(socket.gethostname())
        self._docker_compose_cmd(
            "up -d --scale mtls-gateway=0 --scale mender-client=0",
            env={"HOST_IP": host_ip},
        )
        self._wait_for_containers()

    def start_api_gateway(self):
        self._docker_compose_cmd("start mender-api-gateway")

    def stop_api_gateway(self):
        self._docker_compose_cmd("stop mender-api-gateway")

    def start_mtls_gateway(self):
        self._docker_compose_cmd("up -d --scale mtls-gateway=1 mtls-gateway")
        self._wait_for_containers()

    def new_mtls_client(self, name, tenant):
        self._docker_compose_cmd(
            "run -d --name=%s_%s mender-client" % (self.name, name),
            env={"TENANT_TOKEN": "%s" % tenant},
        )
        logger.info("creating client connected to tenant: " + tenant)
        time.sleep(45)


class DockerComposeCustomSetup(DockerComposeNamespace):
    def __init__(self, name):
        DockerComposeNamespace.__init__(self, name)

    def setup(self):
        pass
