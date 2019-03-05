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
import pytest
from MenderAPI import auth, auth_v2, reset_mender_api
from common import *
from common_docker import *
import conftest
import time
import socket

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

    set_setup_type(ST_OneClient)


def setup_set_client_number_bootstrapped(clients):
    docker_compose_cmd("scale mender-client=%d" % clients)
    ssh_is_opened()

    auth.reset_auth_token()
    auth_v2.accept_devices(clients)

    set_setup_type(None)


@pytest.fixture(scope="function")
def standard_setup_one_client_bootstrapped():
    restart_docker_compose()
    reset_mender_api()
    auth_v2.accept_devices(1)

    set_setup_type(ST_OneClientBootstrapped)


@pytest.fixture(scope="function")
def standard_setup_two_clients_bootstrapped():
    restart_docker_compose(2)
    reset_mender_api()
    auth_v2.accept_devices(2)

    set_setup_type(ST_TwoClientsBootstrapped)

@pytest.fixture(scope="function")
def standard_setup_one_client_bootstrapped_with_s3():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.client.yml \
                        -f ../docker-compose.testing.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f ../docker-compose.storage.s3.yml up -d",
                        use_common_files=False)

    docker_compose_cmd("logs -f &")
    ssh_is_opened()

    auth.reset_auth_token()
    auth_v2.accept_devices(1)

    set_setup_type(ST_OneClientsBootstrapped_AWS_S3)


@pytest.fixture(scope="function")
def standard_setup_without_client():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f ../docker-compose.testing.yml up -d",
                        use_common_files=False)

    set_setup_type(ST_NoClient)

@pytest.fixture(scope="function")
def setup_with_legacy_client():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.client.yml \
                        -f legacy-v1-client.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f ../docker-compose.testing.yml up -d",
                        use_common_files=False)

    ssh_is_opened()
    auth_v2.accept_devices(1)
    set_setup_type(ST_NoClient)

@pytest.fixture(scope="function")
def standard_setup_with_signed_artifact_client(request):
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f ../extra/signed-artifact-client-testing/docker-compose.signed-client.yml up -d")

    ssh_is_opened()
    auth.reset_auth_token()
    auth_v2.accept_devices(1)
    set_setup_type(ST_SignedClient)


@pytest.fixture(scope="function")
def standard_setup_with_short_lived_token():
    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.client.yml \
                        -f ../docker-compose.storage.minio.yml  \
                        -f ../docker-compose.testing.yml \
                        -f ../extra/expired-token-testing/docker-compose.short-token.yml up -d",
                        use_common_files=False)

    ssh_is_opened()
    auth.reset_auth_token()
    auth_v2.accept_devices(1)
    set_setup_type(ST_ShortLivedAuthToken)

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

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.client.yml \
                        -f ../docker-compose.storage.minio.yml  \
                        -f ../docker-compose.testing.yml \
                        -f ../extra/failover-testing/docker-compose.failover-server.yml up -d",
                        use_common_files=False)

    ssh_is_opened()
    auth.reset_auth_token()
    auth_v2.accept_devices(1)
    set_setup_type(ST_Failover)

@pytest.fixture(scope="function")
def running_custom_production_setup(request):
    conftest.production_setup_lock.acquire()

    stop_docker_compose()
    reset_mender_api()

    def fin():
        conftest.production_setup_lock.release()
        stop_docker_compose()

    request.addfinalizer(fin)

    set_setup_type(ST_CustomSetup)


@pytest.fixture(scope="function")
def multitenancy_setup_without_client(request):
    if not conftest.run_tenant_tests:
        pytest.skip("Tenant tests disabled")

    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f ../docker-compose.testing.yml \
                        -f ../docker-compose.tenant.yml \
                        %s up -d" % (conftest.mt_docker_compose_file),
                        use_common_files=False)

    # wait a bit for the backend to start
    wait_for_containers(15, ["../docker-compose.yml",
                             "../docker-compose.tenant.yml",
                             "../docker-compose.storage.minio.yml"])

    def fin():
        stop_docker_compose()

    request.addfinalizer(fin)
    set_setup_type(ST_MultiTenancyNoClient)


@pytest.fixture(scope="function")
def standard_setup_one_client_bootstrapped_with_s3_and_mt(request):
    if not conftest.run_tenant_tests:
        pytest.skip("Tenant tests disabled")

    stop_docker_compose()
    reset_mender_api()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.testing.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f ../docker-compose.storage.s3.yml \
                        -f ../docker-compose.tenant.yml \
                        %s up -d" % (conftest.mt_docker_compose_file),
                        use_common_files=False)


    wait_for_containers(15, ["../docker-compose.yml",
                             "../docker-compose.testing.yml ",
                             "../docker-compose.tenant.yml",
                             "../docker-compose.storage.minio.yml",
                             "../docker-compose.storage.s3.yml"])

    def fin():
        stop_docker_compose()

    request.addfinalizer(fin)
    set_setup_type(ST_OneClientsBootstrapped_AWS_S3_MT)

@pytest.fixture(scope="function")
def multitenancy_setup_without_client_with_smtp(request):
    if not conftest.run_tenant_tests:
        pytest.skip("Tenant tests disabled")

    stop_docker_compose()
    reset_mender_api()

    host_ip = get_host_ip()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f ../docker-compose.testing.yml \
                        -f ../docker-compose.tenant.yml \
                        %s \
                        -f ../extra/smtp-testing/conductor-workers-smtp-test.yml \
                        -f ../extra/recaptcha-testing/tenantadm-test-recaptcha-conf.yml \
                        up -d"  % (conftest.mt_docker_compose_file),
                       use_common_files=False, env={"HOST_IP": host_ip})

    # wait a bit for the backend to start
    wait_for_containers(15, ["../docker-compose.yml",
                             "../docker-compose.tenant.yml",
                             "../docker-compose.storage.minio.yml"])

    def fin():
        stop_docker_compose()

    request.addfinalizer(fin)
    set_setup_type(ST_MultiTenancyNoClientWithSmtp)


def get_host_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    host_ip = s.getsockname()[0]
    s.close()
    return host_ip
