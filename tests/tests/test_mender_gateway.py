# Copyright 2022 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import pytest


from testutils.api import proto_shell, protomsg
from testutils.infra.cli import CliTenantadm
from testutils.infra.container_manager import factory
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra.device import MenderDevice
from ..common_setup import (
    class_persistent_standard_setup_one_client_bootstrapped,
    enterprise_no_client_class,
)
from ..MenderAPI import (
    devconnect,
    devauth,
    reset_mender_api,
    DeviceAuthV2,
    Authentication,
    DeviceConnect,
    get_container_manager,
)
from testutils.common import User, update_tenant
from .common_connect import wait_for_connect

container_factory = factory.get_factory()

class TestMenderGatewayEnterprise:

    def enterprise_gateway_and_client(self):
        pass

    def test_container_up(self, enterprise_no_client_class):
        """Test that the container is working"""

        pass
