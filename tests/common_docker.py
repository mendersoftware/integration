#!/usr/bin/python
# Copyright 2017 Northern.tech AS
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

import subprocess
import tempfile
import time
import logging
import os

from platform import python_version
if python_version().startswith('2'):
    from fabric.api import *
else:
    # Dummy parallel decorator for Python3/Fabric 2
    # Feature has not been implemented: https://github.com/pyinvoke/invoke/issues/63
    def parallel(func):
        def func_wrapper():
            return None
        return func_wrapper

import conftest

COMPOSE_FILES_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))

COMPOSE_FILES = [
    COMPOSE_FILES_PATH + "/docker-compose.yml",
    COMPOSE_FILES_PATH + "/docker-compose.client.yml",
    COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml",
    COMPOSE_FILES_PATH + "/docker-compose.testing.yml",
]

log_files = []
logger = logging.getLogger("root")


def store_logs():
    tfile = tempfile.mktemp("mender_testing")
    docker_compose_cmd("logs -f --no-color > %s 2>&1 &" % tfile,
                        env={'COMPOSE_HTTP_TIMEOUT': '100000'})
    logger.info("docker-compose log file stored here: %s" % tfile)
    log_files.append(tfile)


def docker_compose_cmd(arg_list, use_common_files=True, env=None):
    """
        start a specific docker-compose setup, and retry a few times due to:
        - https://github.com/opencontainers/runc/issues/1326
    """
    files_args = ""

    if use_common_files:
        for file in COMPOSE_FILES:
            files_args += " -f %s" % file

    with conftest.docker_lock:
        cmd = "docker-compose -p %s %s %s" % (conftest.docker_compose_instance,
                                              files_args,
                                              arg_list)

        logger.info("running with: %s" % cmd)

        penv = dict(os.environ)
        if env:
            penv.update(env)

        for count in range(5):
            try:
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True, env=penv)

                if "up -d" in arg_list:
                    store_logs()

                # Return as string (Python 2/3 compatible)
                if isinstance(output, bytes):
                    return output.decode()
                return output

            except subprocess.CalledProcessError as e:
                logger.warning("failed to run docker-compose: error: %s, retrying..." % (e.output))
                time.sleep(count * 30)
                continue

        raise Exception("failed to start docker-compose (called: %s): exit code: %d, output: %s" % (e.cmd, e.returncode, e.output))

def stop_docker_compose():
     with conftest.docker_lock:
         # Take down all docker instances in this namespace.
         cmd = "docker ps -aq -f name=%s | xargs -r docker rm -fv" % conftest.docker_compose_instance
         logger.info("running %s" % cmd)
         subprocess.check_call(cmd, shell=True)
         cmd = "docker network list -q -f name=%s | xargs -r docker network rm" % conftest.docker_compose_instance
         logger.info("running %s" % cmd)
         subprocess.check_call(cmd, shell=True)

def stop_docker_compose_exclude(exclude=[]):
    with conftest.docker_lock:
        """
        Take down all docker instances in this namespace, except for 'exclude'd container names.
        'exclude' doesn't need exact names, it's a verbatim grep regex.
        """

        cmd = "docker ps -aq -f name=%s  | xargs -r docker rm -fv" % conftest.docker_compose_instance

        # exclude containers by crude grep -v and awk'ing out the id
        # that's because docker -f allows only simple comparisons, no negations/logical ops
        if len(exclude) != 0:
            cmd_excl = 'grep -vE "(' + " | ".join(exclude) + ')"'
            cmd_id = "awk 'NR>1 {print $1}'"
            cmd = "docker ps -a -f name=%s | %s | %s | xargs -r docker rm -fv" % (conftest.docker_compose_instance, cmd_excl, cmd_id)

        logger.info("running %s" % cmd)
        subprocess.check_call(cmd, shell=True)

        # if we're preserving some containers, don't destroy the network (will error out on exit)
        if len(exclude) == 0:
            cmd = "docker network list -q -f name=%s | xargs -r docker network rm" % conftest.docker_compose_instance
            logger.info("running %s" % cmd)
            subprocess.check_call(cmd, shell=True)


def start_docker_compose(clients=1):
    docker_compose_cmd("up -d")

    if clients > 1:
        docker_compose_cmd("scale mender-client=%d" % clients)


    ssh_is_opened()


def restart_docker_compose(clients=1):
    stop_docker_compose()
    start_docker_compose(clients)


def docker_get_ip_of(service):
    """Return a list of IP addresseses of `service`. `service` is the same name as
    present in docker-compose files.
    """
    temp = "docker ps -q " \
           "--filter label=com.docker.compose.project={project} " \
           "--filter label=com.docker.compose.service={service} "
    cmd = temp.format(project=conftest.docker_compose_instance,
                      service=service)

    output = subprocess.check_output(cmd + \
                                     "| xargs -r " \
                                     "docker inspect --format='{{.NetworkSettings.Networks.%s_mender.IPAddress}}'" % \
                                     conftest.docker_compose_instance,
                                     shell=True)

    # Return as list of strings (Python 2/3 compatible)
    if isinstance(output, bytes):
        return output.decode().split()
    return output.split()

def docker_get_docker_host_ip():
    """Returns the IP of the host running the Docker containers. The IP will be
    for the correct docker-compose instance.
    """
    temp = "docker ps -q " \
           "--filter label=com.docker.compose.project={project} "
    cmd = temp.format(project=conftest.docker_compose_instance)

    output = subprocess.check_output(cmd + \
                                     "| head -n1 | xargs -r " \
                                     "docker inspect --format='{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}'",
                                     shell=True)
    # Return as string (Python 2/3 compatible)
    if isinstance(output, bytes):
        return output.decode().split()[0]
    return output.split()[0]


def get_mender_clients(service="mender-client"):
    clients = [ip + ":8822" for ip in docker_get_ip_of(service)]
    return clients

def get_mender_client_by_container_name(image_name):
    cmd = "docker inspect -f \'{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}\' %s_%s" % (conftest.docker_compose_instance, image_name)
    output = subprocess.check_output(cmd, shell=True)
    # Return as string (Python 2/3 compatible)
    if isinstance(output, bytes):
        return output.decode().strip() + ":8822"
    return output.strip() + ":8822"

def get_mender_gateway(service="mender-api-gateway"):
    gateway = docker_get_ip_of(service)

    if len(gateway) != 1:
        raise SystemExit("expected one instance of api-gateway running, but found: %d instance(s)" % len(gateway))

    return gateway[0]

def get_mender_conductor():
    conductor = docker_get_ip_of("mender-conductor")

    if len(conductor) != 1:
        raise SystemExit("expected one instance of mender-conductor running, but found: %d instance(s)" % len(conductor))

    return conductor[0]

def new_tenant_client(name, tenant):
    logging.info("creating client connected to tenant: " + tenant)
    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml -f " + COMPOSE_FILES_PATH + \
                       "/docker-compose.mt.client.yml run -d --name=%s_%s mender-client" %
                       (conftest.docker_compose_instance, name),
                       env={"TENANT_TOKEN": "%s" % tenant})
    time.sleep(45)
