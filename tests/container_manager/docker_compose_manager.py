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

import hashlib
import logging
import os
import socket
import subprocess
import time

from .docker_compose_base_manager import DockerComposeBaseNamespace, docker_lock

logger = logging.getLogger("root")


class DockerComposeNamespace(DockerComposeBaseNamespace):
    COMPOSE_FILES_PATH = DockerComposeBaseNamespace.COMPOSE_FILES_PATH
    # Please note that the compose files sequence matters!
    # The same parameter in different files can have different values and
    # a value from the last yaml will be used.
    # The import and its overrides must stay separate files: compose v2 rejects a
    # file that both include:s a composition and overrides a service from it.
    BASE_FILES = [
        COMPOSE_FILES_PATH + "/tests/compose/docker-compose.testing.yml",
        COMPOSE_FILES_PATH + "/tests/compose/docker-compose.testing.overrides.yml",
    ]
    QEMU_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
    ]
    QEMU_EXTENDED_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.extended.yml",
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
    # Overlay for the second backend, brought up as its own compose project.
    FAILOVER_SERVER_FILES = [
        COMPOSE_FILES_PATH + "/tests/compose/docker-compose.failover.yml",
    ]
    # Attaches the client to the failover backend's network as well as its own.
    FAILOVER_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.failover.yml",
    ]
    ENTERPRISE_FILES = [
        COMPOSE_FILES_PATH + "/tests/compose/docker-compose.testing.enterprise.yml",
        COMPOSE_FILES_PATH
        + "/tests/compose/docker-compose.testing.enterprise.overrides.yml",
    ]
    # Opt-in: gives Mongo a real volume instead of the default tmpfs, for setups
    # that have to survive the backend being torn down and replaced underneath.
    PERSISTENT_MONGO_FILES = [
        COMPOSE_FILES_PATH + "/tests/compose/docker-compose.persistent-mongo.yml",
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
        self._docker_compose_up()

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
    def __init__(self, name, num_clients=1, persistent_mongo=False):
        self.num_clients = num_clients
        extra_files = list(self.QEMU_CLIENT_FILES)
        if persistent_mongo:
            extra_files += self.PERSISTENT_MONGO_FILES
        super().__init__(name, extra_files)

    def setup(self):
        self._docker_compose_up(f"--scale mender-client={self.num_clients}")


class DockerComposeExtendedSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=1):
        self.num_clients = num_clients
        super().__init__(name, self.QEMU_EXTENDED_FILES)

    def setup(self):
        self._docker_compose_up(f"--scale mender-client={self.num_clients}")

    def get_mender_clients(self, network="default"):
        return super().get_mender_clients(
            network=network, client_service_name="mender-client"
        )


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
        args = "" if recreate else "--no-recreate"
        self._docker_compose_up(args, env)

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
    def __init__(self, name, num_clients=1):
        self.num_clients = num_clients
        DockerComposeNamespace.__init__(self, name, self.DOCKER_CLIENT_FILES)

    def setup(self):
        self._docker_compose_up(f"--scale mender-client={self.num_clients}")


class DockerComposeRofsClientSetup(DockerComposeNamespace):
    def __init__(
        self,
        name,
    ):
        DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_ROFS_FILES)


class DockerComposeLegacyV3ClientSetup(DockerComposeNamespace):
    def __init__(
        self,
        name,
    ):
        DockerComposeNamespace.__init__(self, name, self.LEGACY_V3_CLIENT_FILES)

    def get_mender_clients(self, network="default"):
        clients = [
            ip + ":8822"
            for ip in self.get_ip_of_service(
                service="mender-client-3-6", network=network
            )
        ]
        return clients


class DockerComposeSignedArtifactClientSetup(DockerComposeNamespace):
    def __init__(
        self,
        name,
    ):
        DockerComposeNamespace.__init__(
            self, name, self.QEMU_CLIENT_FILES + self.SIGNED_ARTIFACT_CLIENT_FILES
        )


class DockerComposeShortLivedTokenSetup(DockerComposeNamespace):
    def __init__(
        self,
        name,
    ):
        DockerComposeNamespace.__init__(
            self, name, self.QEMU_CLIENT_FILES + self.SHORT_LIVED_TOKEN_FILES
        )


class DockerComposeFailoverBackend(DockerComposeNamespace):
    """The second backend of the failover setup, in its own compose project.

    Same composition as the primary, with only traefik's aliases overridden, so
    there is nothing here to keep in step with mender-server.
    """

    FAILOVER_HOSTNAME = "failover.docker.mender.io"

    def __init__(self, name):
        DockerComposeNamespace.__init__(self, name, self.FAILOVER_SERVER_FILES)

    @property
    def compose_env(self):
        # Selects the hostname every router rule in this project matches on. Has
        # to be set for every compose command, not just 'up', so that the
        # rendered project stays consistent.
        return {"MENDER_HOSTNAME": self.FAILOVER_HOSTNAME}

    @property
    def GATEWAY_HOSTNAME(self):
        return self.FAILOVER_HOSTNAME


class DockerComposeFailoverServerSetup(DockerComposeNamespace):
    """Two independent backends plus one client that can reach both.

    Server A is this namespace and behaves normally. Server B is a second compose
    project -- separate network, separate database -- so it genuinely does not know
    the device until the test decommissions it from A. See
    tests/compose/docker-compose.failover.yml for why it cannot be one project.
    """

    def __init__(
        self,
        name,
    ):
        DockerComposeNamespace.__init__(
            self, name, self.QEMU_CLIENT_FILES + self.FAILOVER_CLIENT_FILES
        )
        self.failover = DockerComposeFailoverBackend(self._failover_project_name())

    def _failover_project_name(self):
        """Project name for the second backend.

        It must not *contain* this namespace's own name. DockerNamespace.getid
        locates a container by grepping `docker ps` for the project name, so with
        a name like "<self.name>_failover" every lookup in this namespace would
        also match the failover backend's container of the same service, hand two
        ids to `docker exec`, and fail with a misleading error. Swapping the
        prefix keeps the two disjoint.
        """
        prefix = "mender"
        if self.name.startswith(prefix):
            candidate = "failover" + self.name[len(prefix) :]
        else:
            candidate = "failover" + hashlib.sha1(self.name.encode()).hexdigest()[:10]
        assert (
            self.name not in candidate
        ), "failover project name %r must not contain the primary project name %r" % (
            candidate,
            self.name,
        )
        return candidate

    def setup(self):
        # B first: the client's compose file declares B's network as external, so
        # it has to exist before A's client can be attached to it.
        self.failover.setup()
        self._docker_compose_up("--scale mender-client=1")

    def teardown(self):
        try:
            super().teardown()
        finally:
            self.failover.teardown()

    def teardown_exclude(self, exclude=[]):
        try:
            super().teardown_exclude(exclude)
        finally:
            self.failover.teardown()

    @property
    def compose_env(self):
        # Resolves the external network in docker-compose.client.failover.yml.
        return {"MENDER_FAILOVER_NETWORK": self.failover.network_name}

    def get_failover_gateway(self):
        """IP of the failover backend's ingress."""
        return self.failover.get_mender_gateway()


class DockerComposeEnterpriseSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=0, persistent_mongo=False):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError(
                "Clients not implemented on setup time, use new_tenant_client"
            )
        else:
            extra_files = list(self.ENTERPRISE_FILES)
            if persistent_mongo:
                extra_files += self.PERSISTENT_MONGO_FILES
            DockerComposeNamespace.__init__(self, name, extra_files)

    def setup(self, recreate=True, env=None):
        args = ""
        if any("client" in cf for cf in self.docker_compose_files):
            args += f"--scale mender-client={self.num_clients}"
        if not recreate:
            args += " --no-recreate"
        self._docker_compose_up(args, env)

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

    def get_mender_clients(self, network="default"):
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
        self._docker_compose_up("--scale mender-client=0")

    def new_tenant_docker_client(self, name, tenant):
        logger.info("creating docker client connected to tenant: " + tenant)
        # The backend was already waited for in setup(); this only adds a client.
        self._docker_compose_up(
            "--scale mender-client=1",
            {"TENANT_TOKEN": "%s" % tenant},
            wait_ready=False,
        )


class DockerComposeMTLSSetup(DockerComposeNamespace):
    def __init__(self, name):
        extra_files = self.MTLS_FILES + self.ENTERPRISE_FILES
        super().__init__(name, extra_files)

    def setup(self):
        host_ip = socket.gethostbyname(socket.gethostname())
        self._docker_compose_up(
            "--scale mtls-gateway=0 --scale mender-client=0",
            {"HOST_IP": host_ip},
        )

    def start_api_gateway(self):
        self._docker_compose_cmd("start traefik")

    def stop_api_gateway(self):
        self._docker_compose_cmd("stop traefik")

    def start_mtls_gateway(self):
        # Must not wait on the ingress: the mTLS fixture stops it deliberately,
        # so a readiness poll here would block until it times out.
        self._docker_compose_up("--scale mtls-gateway=1 mtls-gateway", wait_ready=False)

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
