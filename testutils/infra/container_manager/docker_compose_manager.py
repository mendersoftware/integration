
import os
import time
import subprocess
import filelock
import logging
import tempfile

from . import log_files
from .base import BaseContainerManagerNamespace

# Temporary hack: assume the caller sets the variable to whatever is
# used globally (ie.e conftest.docker_compose_instance)
# This will eventually be the id of the namespace
docker_compose_instance = "invalid"

# Global lock to sycronize calls to docker-compose
docker_lock = filelock.FileLock("docker_lock")

def get_host_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    host_ip = s.getsockname()[0]
    s.close()
    return host_ip

class DockerComposeNamespace(BaseContainerManagerNamespace):

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

    def store_logs(self):
        tfile = tempfile.mktemp("mender_testing")
        self.docker_compose_cmd("logs -f --no-color > %s 2>&1 &" % tfile,
                        env={'COMPOSE_HTTP_TIMEOUT': '100000'})
        logging.info("docker-compose log file stored here: %s" % tfile)
        log_files.append(tfile)

    def docker_compose_cmd(self, arg_list, use_common_files=True, env=None, file_list=[]):
        """
            start a specific docker-compose setup, and retry a few times due to:
            - https://github.com/opencontainers/runc/issues/1326
        """
        files_args = ""

        if use_common_files:
            for file in self.BASE_FILES + self.QEMU_CLIENT_FILES:
                files_args += " -f %s" % file

        if len(file_list) > 0:
            for file in file_list:
                files_args += " -f %s" % file

        with docker_lock:
            cmd = "docker-compose -p %s %s %s" % (docker_compose_instance,
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
                    print("failed to run docker-compose: error: %s, retrying..." % (e.output))
                    time.sleep(count * 30)
                    continue

            raise Exception("failed to start docker-compose (called: %s): exit code: %d, output: %s" % (e.cmd, e.returncode, e.output))

    def start_docker_compose(self, clients=1):
        self.docker_compose_cmd("up -d")

        if clients > 1:
            self.docker_compose_cmd("scale mender-client=%d" % clients)

    def stop_docker_compose(self):
        with docker_lock:
            # Take down all docker instances in this namespace.
            cmd = "docker ps -aq -f name=%s | xargs -r docker rm -fv" % docker_compose_instance
            logging.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)
            cmd = "docker network list -q -f name=%s | xargs -r docker network rm" % docker_compose_instance
            logging.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)

class DockerComposeStandardSetup(DockerComposeNamespace):
    def __init__(self, num_clients=1):
        self.num_clients = num_clients
    def setup(self):
        if self.num_clients > 0:
            self.start_docker_compose(self.num_clients)
        else:
            self.docker_compose_cmd("up -d", use_common_files=False, file_list=self.BASE_FILES)
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeDockerClientSetup(DockerComposeNamespace):
    def setup(self):
        self.docker_compose_cmd("up -d", use_common_files=False, file_list=self.BASE_FILES+self.DOCKER_CLIENT_FILES)
    def teardown(self):
        self.stop_docker_compose()

class DockerComposeRofsClientSetup(DockerComposeNamespace):
    def setup(self):
        self.docker_compose_cmd("up -d", use_common_files=False, file_list=self.BASE_FILES+self.QEMU_CLIENT_ROFS_FILES)
    def teardown(self):
        self.stop_docker_compose()
