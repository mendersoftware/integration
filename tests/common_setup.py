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

import time
import socket
import subprocess
import pytest
from . import conftest

from .MenderAPI import auth, auth_v2, reset_mender_api
from .common import *
from .common_docker import *

def wait_for_containers(expected_containers, defined_in):
    for _ in range(60 * 5):
        out = subprocess.check_output("docker-compose -p %s %s ps -q" % (conftest.docker_compose_instance, "-f " + " -f ".join(defined_in)), shell=True)
        if len(out.split()) == expected_containers:
            time.sleep(60)
            return
        else:
            time.sleep(1)

    pytest.fail("timeout: %d containers not running for docker-compose project: %s" % (expected_containers, conftest.docker_compose_instance))

@pytest.fixture(scope="function")
def standard_setup_one_client(request):
    restart_docker_compose()
    reset_mender_api()


def setup_set_client_number_bootstrapped(clients):
    docker_compose_cmd("scale mender-client=%d" % clients)
    ssh_is_opened()

    auth.reset_auth_token()
    auth_v2.accept_devices(clients)


@pytest.fixture(scope="function")
def standard_setup_one_client_bootstrapped():
    restart_docker_compose()
    reset_mender_api()
    auth_v2.accept_devices(1)


@pytest.fixture(scope="function")
def standard_setup_one_rofs_client_bootstrapped():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.client.rofs.yml up -d")

    ssh_is_opened()

    auth.reset_auth_token()
    auth_v2.accept_devices(1)


@pytest.fixture(scope="function")
def standard_setup_one_docker_client_bootstrapped():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.docker-client.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml up -d",
                       use_common_files=False)

    ssh_is_opened()

    auth.reset_auth_token()
    auth_v2.accept_devices(1)

@pytest.fixture(scope="function")
def standard_setup_two_clients_bootstrapped():
    restart_docker_compose(2)
    reset_mender_api()
    auth_v2.accept_devices(2)

@pytest.fixture(scope="function")
def standard_setup_without_client():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml up -d",
                       use_common_files=False)

@pytest.fixture(scope="function")
def setup_with_legacy_client():
    # The legacy 1.7.0 client was only built for qemux86-64, so skip tests using
    # it when running other platforms.
    if conftest.machine_name != "qemux86-64":
        pytest.skip("Test only works with qemux86-64, and this is %s"
                    % conftest.machine_name)

    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.client.yml \
                        -f " + COMPOSE_FILES_PATH + "/tests/legacy-v1-client.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml up -d",
                       use_common_files=False)

    ssh_is_opened()
    auth_v2.accept_devices(1)

@pytest.fixture(scope="function")
def standard_setup_with_signed_artifact_client(request):
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/extra/signed-artifact-client-testing/docker-compose.signed-client.yml up -d")

    ssh_is_opened()
    auth.reset_auth_token()
    auth_v2.accept_devices(1)


@pytest.fixture(scope="function")
def standard_setup_with_short_lived_token():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.client.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml  \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/extra/expired-token-testing/docker-compose.short-token.yml up -d",
                       use_common_files=False)

    ssh_is_opened()
    auth.reset_auth_token()
    auth_v2.accept_devices(1)

@pytest.fixture(scope="function")
def setup_failover():
    """
    Setup with two servers and one client.
    First server (A) behaves as usual, whereas the second server (B) should
    not expect any clients. Client is initially set up against server A.
    In docker all microservices for B has a suffix "-2"
    """
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.client.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml  \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/extra/failover-testing/docker-compose.failover-server.yml up -d",
                       use_common_files=False)

    ssh_is_opened()
    auth.reset_auth_token()
    auth_v2.accept_devices(1)

@pytest.fixture(scope="function")
def running_custom_production_setup(request):
    conftest.production_setup_lock.acquire()

    stop_docker_compose()
    reset_mender_api()

    def fin():
        conftest.production_setup_lock.release()
        stop_docker_compose()

    request.addfinalizer(fin)


@pytest.fixture(scope="function")
def enterprise_no_client(request):
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml \
                        up -d",
                       use_common_files=False)

    # wait a bit for the backend to start
    wait_for_containers(16, [COMPOSE_FILES_PATH + "/docker-compose.yml",
                             COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml",
                             COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml"])

    def fin():
        stop_docker_compose()

    request.addfinalizer(fin)

@pytest.fixture(scope="function")
def enterprise_no_client_smtp(request):
    stop_docker_compose()
    reset_mender_api()

    host_ip = get_host_ip()

    docker_compose_cmd("-f " + COMPOSE_FILES_PATH + "/docker-compose.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.testing.yml \
                        -f " + COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml \
                        -f " + COMPOSE_FILES_PATH + "/extra/smtp-testing/conductor-workers-smtp-test.yml \
                        -f " + COMPOSE_FILES_PATH + "/extra/recaptcha-testing/tenantadm-test-recaptcha-conf.yml \
                        up -d",
                       use_common_files=False, env={"HOST_IP": host_ip})

    # wait a bit for the backend to start
    wait_for_containers(16, [COMPOSE_FILES_PATH + "/docker-compose.yml",
                             COMPOSE_FILES_PATH + "/docker-compose.enterprise.yml",
                             COMPOSE_FILES_PATH + "/docker-compose.storage.minio.yml"])

    def fin():
        stop_docker_compose()

    request.addfinalizer(fin)


def get_host_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    host_ip = s.getsockname()[0]
    s.close()
    return host_ip
