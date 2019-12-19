
import os
import time
import socket
import subprocess
import filelock
import logging
import tempfile
import copy

from . import log_files
from .docker_manager import DockerNamespace

# Global lock to sycronize calls to docker-compose
docker_lock = filelock.FileLock("docker_lock")

class DockerComposeNamespace(DockerNamespace):

    COMPOSE_FILES_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    BASE_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.yml",
        COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml",
        COMPOSE_FILES_PATH + "/docker-compose.testing.yml",
    ]
    QEMU_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
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
    ]
    SIGNED_ARTIFACT_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/extra/signed-artifact-client-testing/docker-compose.signed-client.yml"
    ]
    SHORT_LIVED_TOKEN_FILES = [
        COMPOSE_FILES_PATH + "/extra/expired-token-testing/docker-compose.short-token.yml"
    ]
    FAILOVER_SERVER_FILES = [
        COMPOSE_FILES_PATH + "/extra/failover-testing/docker-compose.failover-server.yml"
    ]
    ENTERPRISE_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml",
        COMPOSE_FILES_PATH + "/docker-compose.testing.enterprise.yml",
    ]
    MT_CLIENT_FILES = [
        COMPOSE_FILES_PATH + "/docker-compose.client.yml",
        COMPOSE_FILES_PATH + "/docker-compose.mt.client.yml",
    ]
    SMTP_FILES = [
        COMPOSE_FILES_PATH + "/extra/smtp-testing/conductor-workers-smtp-test.yml",
        COMPOSE_FILES_PATH + "/extra/recaptcha-testing/tenantadm-test-recaptcha-conf.yml",
    ]

    def __init__(self, name, extra_files=[]):
        DockerNamespace.__init__(self, name)
        self.extra_files = copy.copy(extra_files)

    @property
    def docker_compose_files(self):
        return self.BASE_FILES + self.extra_files

    def store_logs(self):
        tfile = tempfile.mktemp("mender_testing")
        self._docker_compose_cmd("logs -f --no-color > %s 2>&1 &" % tfile,
                        env={'COMPOSE_HTTP_TIMEOUT': '100000'})
        logging.info("docker-compose log file stored here: %s" % tfile)
        log_files.append(tfile)

    def _docker_compose_cmd(self, arg_list, env=None):
        """
            start a specific docker-compose setup, and retry a few times due to:
            - https://github.com/opencontainers/runc/issues/1326
        """
        files_args = "".join([" -f %s" % file for file in self.docker_compose_files])

        with docker_lock:
            cmd = "docker-compose -p %s %s %s" % (self.name,
                                                files_args,
                                                arg_list)

            logging.info("running with: %s" % cmd)

            penv = dict(os.environ)
            if env:
                penv.update(env)

            for count in range(5):
                try:
                    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True, env=penv)

                    if "up -d" in arg_list:
                        self.store_logs()

                    # Return as string (Python 2/3 compatible)
                    if isinstance(output, bytes):
                        return output.decode()
                    return output

                except subprocess.CalledProcessError as e:
                    logging.info("failed to run docker-compose: error: %s, retrying..." % (e.output))
                    time.sleep(count * 30)
                    continue

            raise Exception("failed to start docker-compose (called: %s): exit code: %d, output: %s" % (e.cmd, e.returncode, e.output))

    def wait_for_containers(self, expected_containers):
        files_args = "".join([" -f %s" % file for file in self.docker_compose_files])
        for _ in range(60 * 5):
            out = subprocess.check_output("docker-compose -p %s %s ps -q" % (self.name, files_args), shell=True)
            if len(out.split()) == expected_containers:
                time.sleep(60)
                return
            else:
                time.sleep(1)

        raise Exception("timeout: %d containers not running for docker-compose project: %s" % (expected_containers, self.name))

    def stop_docker_compose(self):
        with docker_lock:
            # Take down all docker instances in this namespace.
            cmd = "docker ps -aq -f name=%s | xargs -r docker rm -fv" % self.name
            logging.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)
            cmd = "docker network list -q -f name=%s | xargs -r docker network rm" % self.name
            logging.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)

    def stop_docker_compose_exclude(self, exclude=[]):
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
                cmd = "docker ps -a -f name=%s | %s | %s | xargs -r docker rm -fv" % (self.name, cmd_excl, cmd_id)

            logging.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)

            # if we're preserving some containers, don't destroy the network (will error out on exit)
            if len(exclude) == 0:
                cmd = "docker network list -q -f name=%s | xargs -r docker network rm" % self.name
                logging.info("running %s" % cmd)
                subprocess.check_call(cmd, shell=True)

    def restart_docker_compose(self, clients=1):
        self.stop_docker_compose()
        self.start_docker_compose(clients)

    def docker_get_ip_of(self, service):
        """Return a list of IP addresseses of `service`. `service` is the same name as
        present in docker-compose files.
        """
        temp = "docker ps -q " \
            "--filter label=com.docker.compose.project={project} " \
            "--filter label=com.docker.compose.service={service} "
        cmd = temp.format(project=self.name,
                        service=service)

        output = subprocess.check_output(cmd + \
                                        "| xargs -r " \
                                        "docker inspect --format='{{.NetworkSettings.Networks.%s_mender.IPAddress}}'" % \
                                        self.name,
                                        shell=True)

        # Return as list of strings (Python 2/3 compatible)
        if isinstance(output, bytes):
            return output.decode().split()
        return output.split()

    def get_logs_of_service(self, service):
        """Return logs of service"""
        return self._docker_compose_cmd("logs %s" % service)

    def docker_get_docker_host_ip(self):
        """Returns the IP of the host running the Docker containers. The IP will be
        for the correct docker-compose instance.
        """
        temp = "docker ps -q " \
            "--filter label=com.docker.compose.project={project} "
        cmd = temp.format(project=self.name)

        output = subprocess.check_output(cmd + \
                                        "| head -n1 | xargs -r " \
                                        "docker inspect --format='{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'",
                                        shell=True)
        # Return as string (Python 2/3 compatible)
        if isinstance(output, bytes):
            return output.decode().split()[0]
        return output.split()[0]

    def get_mender_clients(self, service="mender-client"):
        clients = [ip + ":8822" for ip in self.docker_get_ip_of(service)]
        return clients

    def get_mender_client_by_container_name(self, image_name):
        cmd = "docker inspect -f \'{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}\' %s_%s" % (self.name, image_name)
        output = subprocess.check_output(cmd, shell=True)
        # Return as string (Python 2/3 compatible)
        if isinstance(output, bytes):
            return output.decode().strip() + ":8822"
        return output.strip() + ":8822"

    def get_mender_gateway(self, service="mender-api-gateway"):
        gateway = self.docker_get_ip_of(service)

        if len(gateway) != 1:
            raise SystemExit("expected one instance of api-gateway running, but found: %d instance(s)" % len(gateway))

        return gateway[0]

    def get_mender_conductor(self):
        conductor = self.docker_get_ip_of("mender-conductor")

        if len(conductor) != 1:
            raise SystemExit("expected one instance of mender-conductor running, but found: %d instance(s)" % len(conductor))

        return conductor[0]

class DockerComposeStandardSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=1):
        self.num_clients = num_clients
        if self.num_clients == 0:
            DockerComposeNamespace.__init__(self, name)
        else:
            DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_FILES)
    def setup(self):
        self._docker_compose_cmd("up -d")
        if self.num_clients > 1:
                self._docker_compose_cmd("scale mender-client=%d" % self.num_clients)
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeDockerClientSetup(DockerComposeNamespace):
    def __init__(self, name, ):
        DockerComposeNamespace.__init__(self, name, self.DOCKER_CLIENT_FILES)
    def setup(self):
        self._docker_compose_cmd("up -d")
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeRofsClientSetup(DockerComposeNamespace):
    def __init__(self, name, ):
        DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_ROFS_FILES)
    def setup(self):
        self._docker_compose_cmd("up -d")
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeLegacyClientSetup(DockerComposeNamespace):
    def __init__(self, name, ):
        DockerComposeNamespace.__init__(self, name, self.LEGACY_CLIENT_FILES)
    def setup(self):
        self._docker_compose_cmd("up -d")
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeSignedArtifactClientSetup(DockerComposeNamespace):
    def __init__(self, name, ):
        DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_FILES+self.SIGNED_ARTIFACT_CLIENT_FILES)
    def setup(self):
        self._docker_compose_cmd("up -d")
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeShortLivedTokenSetup(DockerComposeNamespace):
    def __init__(self, name, ):
        DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_FILES+self.SHORT_LIVED_TOKEN_FILES)
    def setup(self):
        self._docker_compose_cmd("up -d")
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeFailoverServerSetup(DockerComposeNamespace):
    def __init__(self, name, ):
        DockerComposeNamespace.__init__(self, name, self.QEMU_CLIENT_FILES+self.FAILOVER_SERVER_FILES)
    def setup(self):
        self._docker_compose_cmd("up -d")
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeEnterpriseSetup(DockerComposeNamespace):
    def __init__(self, name, num_clients=0):
        self.num_clients = num_clients
        if self.num_clients > 0:
            raise NotImplementedError("Clients not implemented on setup time, use new_tenant_client")
        else:
            DockerComposeNamespace.__init__(self, name, self.ENTERPRISE_FILES)
    def setup(self, recreate=True, env=None):
        cmd = "up -d"
        if not recreate:
            cmd += " --no-recreate"
        self._docker_compose_cmd(cmd, env=env)
        self.wait_for_containers(15)
    def teardown(self):
        self.stop_docker_compose()

    def new_tenant_client(self, name, tenant):
        if not self.MT_CLIENT_FILES[0] in self.docker_compose_files:
            self.extra_files += self.MT_CLIENT_FILES
        logging.info("creating client connected to tenant: " + tenant)
        self._docker_compose_cmd("run -d --name=%s_%s mender-client" % (self.name, name),
                                env={"TENANT_TOKEN": "%s" % tenant})
        time.sleep(45)

class DockerComposeEnterpriseSMTPSetup(DockerComposeNamespace):
    def __init__(self, name):
        DockerComposeNamespace.__init__(self, name, self.ENTERPRISE_FILES+self.SMTP_FILES)
    def setup(self):
        host_ip = socket.gethostbyname(socket.gethostname())
        self._docker_compose_cmd("up -d", env={"HOST_IP": host_ip})
        self.wait_for_containers(15)
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeNoneSetup(DockerComposeNamespace):
    def __init__(self, name):
        DockerComposeNamespace.__init__(self, name)
    def setup(self):
        pass
    def teardown(self):
        self.stop_docker_compose()
