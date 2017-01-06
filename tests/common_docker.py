#!/usr/bin/python
# Copyright 2016 Mender Software AS
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

import conftest
from common import *


COMPOSE_FILES = [
    "../docker-compose.yml",
    "../docker-compose.client.yml",
    "../docker-compose.demo.yml"
]

def docker_compose_cmd(arg_list):
    files_args = ""
    for file in COMPOSE_FILES:
        files_args += " -f %s" % file

    subprocess.check_call("docker-compose %s %s" % (files_args, arg_list), shell=True)


def stop_docker_compose():
    docker_compose_cmd("down -v")

    set_setup_type(None)


def start_docker_compose():
    docker_compose_cmd("up -d")
    docker_compose_cmd("logs -f &")

    ssh_is_opened()

    set_setup_type(ST_OneClient)


def restart_docker_compose():
    stop_docker_compose()
    start_docker_compose()


def docker_get_ip_of(image):
    # Returns newline separated list of IPs
    output = subprocess.check_output("docker ps --filter='ancestor=%s' --format='{{.ID}}' | xargs -r docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'" % image, shell=True)

    # Return as list.
    return output.split()


def get_mender_clients():
    return [ip + ":8822" for ip in docker_get_ip_of("mendersoftware/mender-client-qemu")]


def get_mender_gateway():
    return docker_get_ip_of("mendersoftware/api-gateway")[0]


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
        logging.fail("Unable to connect to host: ", env.host_string)
