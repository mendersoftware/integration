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
from fabric.api import *
import subprocess
import tempfile
import time
import conftest
import psutil
import logging
import common
import os


COMPOSE_FILES = [
    "../docker-compose.yml",
    "../docker-compose.client.yml",
    "../docker-compose.storage.minio.yml",
    "../docker-compose.testing.yml",
]

log_files = []
logger = logging.getLogger("root")


def store_logs():
    inline_logs = conftest.inline_logs

    if inline_logs:
        docker_compose_cmd("logs -f &",
                           env={'COMPOSE_HTTP_TIMEOUT': '100000'})
    else:
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

                return output

            except subprocess.CalledProcessError as e:
                logger.warn("failed to run docker-compose: error: %s, retrying..." % (e.output))
                time.sleep (count * 30)
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

    common.set_setup_type(None)


def start_docker_compose(clients=1):
    docker_compose_cmd("up -d")
    
    if clients > 1:
        docker_compose_cmd("scale mender-client=%d" % clients)


    ssh_is_opened()

    common.set_setup_type(common.ST_OneClient)


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
                                     "docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'",
                                     shell=True)

    # Return as list.
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
    return output.split()[0]


def get_mender_clients(service="mender-client"):
    clients = [ip + ":8822" for ip in docker_get_ip_of(service)]
    return clients

def get_mender_client_by_container_name(image_name):
    cmd = "docker inspect -f \'{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}\' %s_%s" % (conftest.docker_compose_instance, image_name)
    output = subprocess.check_output(cmd, shell=True)
    return output.strip() + ":8822"

def get_mender_gateway():
    gateway = docker_get_ip_of("mender-api-gateway")

    if len(gateway) != 1:
        raise SystemExit("expected one instance of api-gateway running, but found: %d instance(s)" % len(gateway))

    return gateway[0]

def get_mender_conductor():
    conductor = docker_get_ip_of("mender-conductor")

    if len(conductor) != 1:
        raise SystemExit("expected one instance of mender-conductor running, but found: %d instance(s)" % len(conductor))

    return conductor[0]


def ssh_is_opened(host=None):
    if not host:
        execute(ssh_is_opened_impl, hosts=get_mender_clients())
    else:
        execute(ssh_is_opened_impl, hosts=host)


@parallel
def ssh_is_opened_impl(cmd="true", wait=60*60):
    count = 0
    sleeptime = 1

    while count < wait:
        try:
            # no point in printing this with each test
            with quiet():
                return run(cmd)
        except BaseException:
            time.sleep(sleeptime)
            count += sleeptime
            sleeptime *= 2
            continue
        else:
            break
    else:
        logger.fatal("Unable to connect to host: %s", env.host_string)


def new_tenant_client(name, tenant):
    logging.info("creating client connected to tenant: " + tenant)
    docker_compose_cmd("-f ../docker-compose.tenant.yml %s -f ../docker-compose.mt.client.yml \
                        run -d --name=%s_%s mender-client" % (conftest.mt_docker_compose_file,
                                                              conftest.docker_compose_instance,
                                                              name),
                       env={"TENANT_TOKEN": "%s" % tenant})
    time.sleep(45)
