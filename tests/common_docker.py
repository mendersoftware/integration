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
import pytest
import subprocess
import tempfile
import time
import conftest
from common import *

COMPOSE_FILES = [
    "../docker-compose.yml",
    "../docker-compose.client.yml",
    "../docker-compose.storage.minio.yml",
    "../docker-compose.testing.yml"
]

log_files = []


def docker_compose_cmd(arg_list, use_common_files=True):
    extra_files = conftest.extra_files
    if extra_files is None:
        extra_files = []

    files_args = ""

    if use_common_files:
        for file in COMPOSE_FILES + extra_files:
            files_args += " -f %s" % file

    with conftest.docker_lock:
        cmd = "docker-compose -p %s %s %s" % (conftest.docker_compose_instance,
                                              files_args,
                                              arg_list)

        logging.info("running with: %s" % cmd)

        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
        except subprocess.CalledProcessError as e:
            print "failed to start docker-compose (called: %s): exit code: %d, output: %s" % (e.cmd, e.returncode, e.output)


def stop_docker_compose():
    # take down all COMPOSE_FILES and the s3 specific files
    docker_compose_cmd(" -f ../docker-compose.storage.s3.yml -f ../extra/travis-testing/s3.yml down -v")

    if setup_type() == ST_CustomSetup or setup_type() == ST_NoClient and conftest.production_setup_lock.is_locked:
        conftest.production_setup_lock.release()

    set_setup_type(None)


def start_docker_compose(clients=1):
    inline_logs = conftest.inline_logs

    docker_compose_cmd("up -d")
    if clients > 1:
        docker_compose_cmd("scale mender-client=%d" % clients)

    if inline_logs:
        docker_compose_cmd("logs -f &")
    else:
        tfile = tempfile.mktemp("mender_testing")
        docker_compose_cmd("logs -f --no-color > %s 2>&1 &" % tfile)
        logging.info("docker-compose log file stored here: %s" % tfile)
        log_files.append(tfile)

    ssh_is_opened()

    set_setup_type(ST_OneClient)


def restart_docker_compose(clients=1):
    stop_docker_compose()
    start_docker_compose(clients)


def docker_get_ip_of(image):
    # Returns newline separated list of IPs
    output = subprocess.check_output("docker ps | grep '%s' | grep '%s'| awk '{print $1}'| xargs -r docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'" % (conftest.docker_compose_instance, image), shell=True)

    # Return as list.
    return output.split()


def get_mender_clients():
    return [ip + ":8822" for ip in docker_get_ip_of("mendersoftware/mender-client-qemu")]


def get_mender_gateway():
    gateway = docker_get_ip_of("mendersoftware/api-gateway")

    if len(gateway) != 1:
        raise SystemExit("expected one instance of api-gateway running, but found: %d instance(s)" % len(gateway))

    return gateway[0]

def ssh_is_opened():
    execute(ssh_is_opened_impl, hosts=get_mender_clients())


@parallel
def ssh_is_opened_impl(cmd="true", wait=60):
    count = 0

    while count < wait:
        try:
            # no point in printing this with each test
            with quiet():
                return run(cmd)
        except BaseException:
            time.sleep(1)
            count += 1
            continue
        else:
            break

    if count >= 60:
        logging.fatal("Unable to connect to host: %s", env.host_string)
