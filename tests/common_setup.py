# Copyright 2020 Northern.tech AS
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
from . import conftest

from .MenderAPI import auth, auth_v2, reset_mender_api
from .helpers import Helpers

from testutils.infra.device import MenderDevice, MenderDeviceGroup
from testutils.infra.container_manager import factory

container_factory = factory.get_factory()


@pytest.fixture(scope="function")
def standard_setup_one_client(request):
    env = container_factory.getStandardSetup(num_clients=1)
    request.addfinalizer(env.teardown)

    env.setup()

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    reset_mender_api(env)

    return env


@pytest.fixture(scope="function")
def standard_setup_one_client_bootstrapped(request):
    env = container_factory.getStandardSetup(num_clients=1)
    request.addfinalizer(env.teardown)

    env.setup()

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    reset_mender_api(env)
    auth_v2.accept_devices(1)

    return env


@pytest.fixture(scope="function")
def standard_setup_one_rofs_client_bootstrapped(request):
    env = container_factory.getRofsClientSetup()
    request.addfinalizer(env.teardown)

    env.setup()

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    reset_mender_api(env)
    auth_v2.accept_devices(1)

    return env


@pytest.fixture(scope="function")
def standard_setup_one_docker_client_bootstrapped(request):
    env = container_factory.getDockerClientSetup()
    request.addfinalizer(env.teardown)

    env.setup()

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    reset_mender_api(env)
    auth_v2.accept_devices(1)

    return env


@pytest.fixture(scope="function")
def standard_setup_two_clients_bootstrapped(request):
    env = container_factory.getStandardSetup(num_clients=2)
    request.addfinalizer(env.teardown)

    env.setup()

    env.device_group = MenderDeviceGroup(env.get_mender_clients())
    env.device_group.ssh_is_opened()

    reset_mender_api(env)
    auth_v2.accept_devices(2)

    return env


@pytest.fixture(scope="function")
def standard_setup_without_client(request):
    env = container_factory.getStandardSetup(num_clients=0)
    request.addfinalizer(env.teardown)

    env.setup()
    reset_mender_api(env)

    return env


@pytest.fixture(scope="function")
def setup_with_legacy_client(request):
    # The legacy 1.7.0 client was only built for qemux86-64, so skip tests using
    # it when running other platforms.
    if conftest.machine_name != "qemux86-64":
        pytest.skip(
            "Test only works with qemux86-64, and this is %s" % conftest.machine_name
        )

    env = container_factory.getLegacyClientSetup()
    request.addfinalizer(env.teardown)

    env.setup()

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    reset_mender_api(env)
    auth_v2.accept_devices(1)

    return env


@pytest.fixture(scope="function")
def standard_setup_with_signed_artifact_client(request):
    env = container_factory.getSignedArtifactClientSetup()
    request.addfinalizer(env.teardown)

    env.setup()

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    reset_mender_api(env)
    auth.reset_auth_token()
    auth_v2.accept_devices(1)

    return env


@pytest.fixture(scope="function")
def standard_setup_with_short_lived_token(request):
    env = container_factory.getShortLivedTokenSetup()
    request.addfinalizer(env.teardown)

    env.setup()

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    reset_mender_api(env)
    auth.reset_auth_token()
    auth_v2.accept_devices(1)

    return env


@pytest.fixture(scope="function")
def setup_failover(request):
    env = container_factory.getFailoverServerSetup()
    request.addfinalizer(env.teardown)

    env.setup()
    reset_mender_api(env)

    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    auth.reset_auth_token()
    auth_v2.accept_devices(1)

    return env


@pytest.fixture(scope="function")
def running_custom_production_setup(request):
    conftest.production_setup_lock.acquire()

    env = container_factory.getCustomSetup()

    def fin():
        env.teardown()
        conftest.production_setup_lock.release()

    request.addfinalizer(fin)

    reset_mender_api(env)

    return env


@pytest.fixture(scope="function")
def enterprise_no_client(request):
    env = container_factory.getEnterpriseSetup(num_clients=0)
    request.addfinalizer(env.teardown)

    env.setup()
    reset_mender_api(env)

    return env


@pytest.fixture(scope="function")
def enterprise_no_client_smtp(request):
    env = container_factory.getEnterpriseSMTPSetup()
    request.addfinalizer(env.teardown)

    env.setup()
    reset_mender_api(env)

    return env
