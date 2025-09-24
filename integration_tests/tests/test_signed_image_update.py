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

from integration_tests.common_setup import (
    standard_setup_with_signed_artifact_client,
    enterprise_with_signed_artifact_client,
)
from integration_tests.tests.common_update import update_image, common_update_procedure
from integration_tests.MenderAPI import DeviceAuthV2, Deployments
from integration_tests.tests.mendertesting import MenderTesting


class BaseTestSignedUpdates(MenderTesting):
    """
    Signed artifacts are well tested in the client's acceptance tests, so
    we will only test basic backend integration with signed images here.
    """

    def do_test_signed_artifact_success(self, env, valid_image_with_mender_conf):
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)
        mender_conf = env.device.run("cat /etc/mender/mender.conf")
        update_image(
            env.device,
            env.get_virtual_network_host_ip(),
            install_image=valid_image_with_mender_conf(mender_conf),
            signed=True,
            devauth=devauth,
            deploy=deploy,
        )

    def do_test_unsigned_artifact_fails_deployment(
        self, env, valid_image_with_mender_conf
    ):
        """
        Make sure that an unsigned image fails, and is handled by the backend.
        Notice that this test needs a fresh new version of the backend, since
        we installed a signed image earlier without a verification key in mender.conf
        """
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        mender_conf = env.device.run("cat /etc/mender/mender.conf")
        deployment_id, _ = common_update_procedure(
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
        )
        deploy.check_expected_status("finished", deployment_id)
        deploy.check_expected_statistics(deployment_id, "failure", 1)

        for d in devauth.get_devices():
            assert (
                "expecting signed artifact, but no signature file found"
                in deploy.get_logs(d["id"], deployment_id)
            )


@MenderTesting.fast
class TestSignedUpdatesOpenSource(BaseTestSignedUpdates):
    def test_signed_artifact_success(
        self, standard_setup_with_signed_artifact_client, valid_image_with_mender_conf
    ):
        self.do_test_signed_artifact_success(
            standard_setup_with_signed_artifact_client, valid_image_with_mender_conf
        )

    @pytest.mark.parametrize(
        "standard_setup_with_signed_artifact_client", ["force_new"], indirect=True
    )
    def test_unsigned_artifact_fails_deployment(
        self, standard_setup_with_signed_artifact_client, valid_image_with_mender_conf
    ):
        self.do_test_unsigned_artifact_fails_deployment(
            standard_setup_with_signed_artifact_client, valid_image_with_mender_conf
        )


@MenderTesting.fast
class TestSignedUpdatesEnterprise(BaseTestSignedUpdates):
    def test_signed_artifact_success(
        self, enterprise_with_signed_artifact_client, valid_image_with_mender_conf
    ):
        self.do_test_signed_artifact_success(
            enterprise_with_signed_artifact_client, valid_image_with_mender_conf
        )

    @pytest.mark.parametrize(
        "enterprise_with_signed_artifact_client", ["force_new"], indirect=True
    )
    def test_unsigned_artifact_fails_deployment(
        self, enterprise_with_signed_artifact_client, valid_image_with_mender_conf
    ):
        self.do_test_unsigned_artifact_fails_deployment(
            enterprise_with_signed_artifact_client, valid_image_with_mender_conf
        )
