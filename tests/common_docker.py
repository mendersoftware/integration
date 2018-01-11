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

COMPOSE_FILES = [
    "../docker-compose.yml",
    "../docker-compose.client.yml",
    "../docker-compose.storage.minio.yml",
    "../docker-compose.testing.yml"
]

log_files = []
logger = logging.getLogger("root")

def docker_compose_cmd(arg_list, use_common_files=True):
    files_args = ""

    if use_common_files:
        for file in COMPOSE_FILES:
            files_args += " -f %s" % file

    with conftest.docker_lock:
        cmd = "docker-compose -p %s %s %s" % (conftest.docker_compose_instance,
                                              files_args,
                                              arg_list)

        logger.info("running with: %s" % cmd)

        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
        except subprocess.CalledProcessError as e:
            print "failed to start docker-compose (called: %s): exit code: %d, output: %s" % (e.cmd, e.returncode, e.output)


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
    inline_logs = conftest.inline_logs

    docker_compose_cmd("up -d")
    if clients > 1:
        docker_compose_cmd("scale mender-client=%d" % clients)

    if inline_logs:
        docker_compose_cmd("logs -f &",
                           env={'COMPOSE_HTTP_TIMEOUT': '100000'})
    else:
        tfile = tempfile.mktemp("mender_testing")
        docker_compose_cmd("logs -f --no-color > %s 2>&1 &" % tfile,
                           env={'COMPOSE_HTTP_TIMEOUT': '100000'})
        logger.info("docker-compose log file stored here: %s" % tfile)
        log_files.append(tfile)

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


def get_mender_clients():
    return [ip + ":8822" for ip in docker_get_ip_of("mender-client")]


def get_mender_gateway():
    gateway = docker_get_ip_of("mender-api-gateway")

    if len(gateway) != 1:
        raise SystemExit("expected one instance of api-gateway running, but found: %d instance(s)" % len(gateway))

    return gateway[0]

def ssh_is_opened():
    execute(ssh_is_opened_impl, hosts=get_mender_clients())


@parallel
def ssh_is_opened_impl(cmd="true", wait=300):
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
