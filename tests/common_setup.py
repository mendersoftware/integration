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
from MenderAPI import auth, adm
from common import *
from common_docker import *
import conftest

@pytest.fixture(scope="function")
def standard_setup_one_client(request):
    if getattr(request, 'param', False) and request.param != "force_new" and setup_type() == ST_OneClient:
        return

    restart_docker_compose()
    auth.reset_auth_token()

    set_setup_type(ST_OneClient)


def setup_set_client_number_bootstrapped(clients):
    docker_compose_cmd("scale mender-client=%d" % clients)
    ssh_is_opened()

    auth.reset_auth_token()
    adm.accept_devices(clients)

    set_setup_type(None)


@pytest.fixture(scope="function")
def standard_setup_one_client_bootstrapped():
    if setup_type() == ST_OneClientBootstrapped:
        return

    restart_docker_compose()
    auth.reset_auth_token()
    adm.accept_devices(1)

    set_setup_type(ST_OneClientBootstrapped)


@pytest.fixture(scope="function")
def standard_setup_two_clients_bootstrapped():
    if setup_type() == ST_TwoClientsBootstrapped:
        return

    restart_docker_compose(2)
    auth.reset_auth_token()
    adm.accept_devices(2)

    set_setup_type(ST_TwoClientsBootstrapped)

@pytest.fixture(scope="function")
def standard_setup_one_client_bootstrapped_with_s3():
    if setup_type() == ST_OneClientsBootstrapped_AWS_S3:
        return

    stop_docker_compose()

    docker_compose_cmd("-f ../docker-compose.client.yml \
                        -f ../docker-compose.storage.s3.yml \
                        -f ../docker-compose.yml \
                        -f ../extra/travis-testing/s3.yml up -d",
                        use_common_files=False)

    docker_compose_cmd("logs -f &")
    ssh_is_opened()

    auth.reset_auth_token()
    adm.accept_devices(1)

    set_setup_type(ST_OneClientsBootstrapped_AWS_S3)


@pytest.fixture(scope="function")
def standard_setup_without_client():
    if setup_type() == ST_NoClient:
        return

    stop_docker_compose()
    conftest.production_setup_lock.acquire()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f ../docker-compose.testing.yml up -d",
                        use_common_files=False)

    set_setup_type(ST_NoClient)


@pytest.fixture(scope="function")
def standard_setup_with_signed_artifact_client(request):
    if getattr(request, 'param', False) and request.param != "force_new" and setup_type() == ST_SignedClient:
        return

    stop_docker_compose()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.storage.minio.yml \
                        -f  ../extra/signed-artifact-client-testing/docker-compose.signed-client.yml  \
                        -f ../docker-compose.testing.yml up -d",
                        use_common_files=False)

    ssh_is_opened()
    auth.reset_auth_token()
    adm.accept_devices(1)
    set_setup_type(ST_SignedClient)


@pytest.fixture(scope="function")
def standard_setup_with_short_lived_token():
    if setup_type() == ST_ShortLivedAuthToken:
        return

    stop_docker_compose()

    docker_compose_cmd("-f ../docker-compose.yml \
                        -f ../docker-compose.client.yml \
                        -f ../docker-compose.storage.minio.yml  \
                        -f ../docker-compose.testing.yml \
                        -f ../extra/expired-token-testing/docker-compose.short-token.yml up -d",
                        use_common_files=False)

    ssh_is_opened()
    auth.reset_auth_token()
    adm.accept_devices(1)
    set_setup_type(ST_ShortLivedAuthToken)

@pytest.fixture(scope="function")
def running_custom_production_setup(request):
    conftest.production_setup_lock.acquire()

    # since we are starting a manual instance of the backend,
    # let the script know the instance is called "testprod"
    # so that is cleaned up correctly on test failure/error

    def fin():
        conftest.production_setup_lock.release()
        stop_docker_compose()

    conftest.docker_compose_instance = "testprod"
    request.addfinalizer(fin)

    set_setup_type(ST_CustomSetup)
