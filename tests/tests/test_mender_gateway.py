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

from ..common_setup import (
    standard_setup_one_client_bootstrapped_with_gateway,
    enterprise_one_client_bootstrapped_with_gateway,
)
from .common_update import update_image
from ..MenderAPI import DeviceAuthV2, Deployments
from .mendertesting import MenderTesting


class BaseTestMenderGateway(MenderTesting):
    def do_test_deployment(self, env, valid_image_with_mender_conf):
        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device.run("cat /etc/mender/mender.conf")
        update_image(
            mender_device,
            host_ip,
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
        )


class TestMenderGatewayOpenSource(BaseTestMenderGateway):
    @MenderTesting.fast
    def test_deployment(
        self,
        standard_setup_one_client_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment(
            standard_setup_one_client_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )


class TestMenderGatewayEnterprise(BaseTestMenderGateway):
    @MenderTesting.fast
    def test_deployment(
        self,
        enterprise_one_client_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment(
            enterprise_one_client_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )
