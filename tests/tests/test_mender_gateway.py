# Copyright 2024 Northern.tech AS
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

import os
import pytest
import shutil
import subprocess
import tempfile

from flaky import flaky

from .. import conftest
from ..common_setup import (
    standard_setup_one_client_bootstrapped_with_gateway,
    standard_setup_two_clients_bootstrapped_with_gateway,
    enterprise_one_client_bootstrapped_with_gateway,
    enterprise_two_clients_bootstrapped_with_gateway,
)
from .common_artifact import get_script_artifact
from .common_update import common_update_procedure, update_image
from ..MenderAPI import DeviceAuthV2, Deployments
from .mendertesting import MenderTesting
from ..helpers import Helpers
from testutils.infra.device import MenderDeviceGroup


REBOOT_MAX_WAIT = 600


@pytest.fixture(scope="function")
def image_with_mender_conf_and_mender_gateway_conf(request):
    """Insert mender.conf and mender-gateway.conf into an image"""
    with tempfile.TemporaryDirectory() as d:

        def cleanup():
            shutil.rmtree(d, ignore_errors=True)

        request.addfinalizer(cleanup)
        yield lambda image, mender_conf, mender_gateway_conf: add_mender_conf_and_mender_gateway_conf(
            d, image, mender_conf, mender_gateway_conf
        )


def add_mender_conf_and_mender_gateway_conf(d, image, mender_conf, mender_gateway_conf):
    mender_conf_tmp = os.path.join(d, "mender.conf")
    with open(mender_conf_tmp, "w") as f:
        f.write(mender_conf)
    mender_gateway_conf_tmp = os.path.join(d, "mender-gateway.conf")
    with open(mender_gateway_conf_tmp, "w") as f:
        f.write(mender_gateway_conf)
    new_image = os.path.join(d, image)
    shutil.copy(image, new_image)

    instr_file = os.path.join(d, "write.instr")
    with open(os.path.join(d, "write.instr"), "w") as f:
        f.write(
            """cd /etc/mender
        rm mender.conf
        rm mender-gateway.conf
        write {local1} mender.conf
        write {local2} mender-gateway.conf
        """.format(
                local1=mender_conf_tmp, local2=mender_gateway_conf_tmp,
            )
        )
    subprocess.run(
        ["debugfs", "-w", "-f", instr_file, new_image],
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(
        ["debugfs", "-R", "cat /etc/mender/mender.conf", new_image],
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(
        ["debugfs", "-R", "cat /etc/mender/mender-gateway.conf", new_image],
        check=True,
        stdout=subprocess.PIPE,
    )
    return new_image


class BaseTestMenderGateway(MenderTesting):
    def do_test_deployment_one_device(self, env, valid_image_with_mender_conf):
        mender_device = env.device
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device.run("cat /etc/mender/mender.conf")

        device_id = Helpers.ip_to_device_id_map(
            MenderDeviceGroup([mender_device.host_string]), devauth=devauth,
        )[mender_device.host_string]

        update_image(
            mender_device,
            host_ip,
            expected_mender_clients=1,
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
            devices=[device_id],
        )

    def do_test_deployment_gateway_and_one_device(
        self,
        env,
        valid_image_with_mender_conf,
        image_with_mender_conf_and_mender_gateway_conf,
        gateway_image,
    ):
        mender_device = env.device
        mender_gateway = env.device_gateway
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        mender_device_mender_conf = mender_device.run("cat /etc/mender/mender.conf")
        mender_gateway_gateway_conf = mender_gateway.run(
            "cat /etc/mender/mender-gateway.conf"
        )
        mender_gateway_mender_conf = mender_gateway.run("cat /etc/mender/mender.conf")

        host_ip = env.get_virtual_network_host_ip()

        ip_to_device_id = Helpers.ip_to_device_id_map(
            MenderDeviceGroup([mender_device.host_string, mender_gateway.host_string]),
            devauth=devauth,
        )

        mender_gateway_image = image_with_mender_conf_and_mender_gateway_conf(
            gateway_image, mender_gateway_mender_conf, mender_gateway_gateway_conf,
        )

        def update_device():
            device_id = ip_to_device_id[mender_device.host_string]
            update_image(
                mender_device,
                host_ip,
                expected_mender_clients=1,
                install_image=valid_image_with_mender_conf(mender_device_mender_conf),
                devauth=devauth,
                deploy=deploy,
                devices=[device_id],
            )

        gateway_id = ip_to_device_id[mender_gateway.host_string]
        deployment_id, _ = common_update_procedure(
            mender_gateway_image,
            devices=[gateway_id],
            devauth=devauth,
            deploy=deploy,
            deployment_triggered_callback=update_device,
            verify_status=False,
        )

        deploy.check_expected_statistics(deployment_id, "success", 1)
        deploy.check_expected_status("finished", deployment_id)

    def do_test_deployment_two_devices_update_both(
        self, env, valid_image_with_mender_conf
    ):
        device_group = env.device_group
        mender_device_1 = device_group[0]
        mender_device_2 = device_group[1]
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device_1.run("cat /etc/mender/mender.conf")

        ip_to_device_id = Helpers.ip_to_device_id_map(device_group, devauth=devauth)
        device_id_1 = ip_to_device_id[mender_device_1.host_string]
        device_id_2 = ip_to_device_id[mender_device_2.host_string]

        update_image(
            mender_device_1,
            host_ip,
            expected_mender_clients=2,
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
            devices=[device_id_1, device_id_2],
        )

    def do_test_deployment_two_devices_update_one(
        self, env, valid_image_with_mender_conf
    ):
        device_group = env.device_group
        mender_device_1 = device_group[0]
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device_1.run("cat /etc/mender/mender.conf")

        ip_to_device_id = Helpers.ip_to_device_id_map(device_group, devauth=devauth)
        device_id_1 = ip_to_device_id[mender_device_1.host_string]

        update_image(
            mender_device_1,
            host_ip,
            expected_mender_clients=1,
            install_image=valid_image_with_mender_conf(mender_conf),
            devauth=devauth,
            deploy=deploy,
            devices=[device_id_1],
        )

    def do_test_deployment_two_devices_parallel_updates(
        self, env, valid_image_with_mender_conf
    ):
        device_group = env.device_group
        mender_device_1 = device_group[0]
        mender_device_2 = device_group[1]
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device_1.run("cat /etc/mender/mender.conf")
        valid_image = valid_image_with_mender_conf(mender_conf)

        ip_to_device_id = Helpers.ip_to_device_id_map(device_group, devauth=devauth)
        device_id_1 = ip_to_device_id[mender_device_1.host_string]
        device_id_2 = ip_to_device_id[mender_device_2.host_string]

        reboot = {mender_device_1: None, mender_device_2: None}
        with mender_device_1.get_reboot_detector(host_ip) as reboot[
            mender_device_1
        ], mender_device_2.get_reboot_detector(host_ip) as reboot[mender_device_2]:
            deployment_id_1, expected_image_id_1 = common_update_procedure(
                valid_image, devices=[device_id_1], devauth=devauth, deploy=deploy,
            )

            deployment_id_2, expected_image_id_2 = common_update_procedure(
                valid_image, devices=[device_id_2], devauth=devauth, deploy=deploy,
            )
            reboot[mender_device_1].verify_reboot_performed(REBOOT_MAX_WAIT)
            reboot[mender_device_2].verify_reboot_performed(REBOOT_MAX_WAIT)

        deploy.check_expected_statistics(deployment_id_1, "success", 1)
        deploy.get_logs(device_id_1, deployment_id_1, expected_status=404)

        deploy.check_expected_statistics(deployment_id_2, "success", 1)
        deploy.get_logs(device_id_2, deployment_id_2, expected_status=404)

        assert mender_device_1.yocto_id_installed_on_machine() == expected_image_id_1
        assert mender_device_2.yocto_id_installed_on_machine() == expected_image_id_2

        deploy.check_expected_status("finished", deployment_id_1)
        deploy.check_expected_status("finished", deployment_id_2)

    def do_test_deployment_two_devices_parallel_updates_one_failure(
        self, env, valid_image_with_mender_conf, broken_update_image,
    ):
        device_group = env.device_group
        mender_device_1 = device_group[0]
        mender_device_2 = device_group[1]
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device_1.run("cat /etc/mender/mender.conf")
        valid_image = valid_image_with_mender_conf(mender_conf)

        ip_to_device_id = Helpers.ip_to_device_id_map(device_group, devauth=devauth)
        device_id_1 = ip_to_device_id[mender_device_1.host_string]
        device_id_2 = ip_to_device_id[mender_device_2.host_string]

        reboot = {mender_device_1: None, mender_device_2: None}
        with mender_device_1.get_reboot_detector(host_ip) as reboot[
            mender_device_1
        ], mender_device_2.get_reboot_detector(host_ip) as reboot[mender_device_2]:
            deployment_id_1, expected_image_id_1 = common_update_procedure(
                valid_image, devices=[device_id_1], devauth=devauth, deploy=deploy,
            )

            deployment_id_2, expected_image_id_2 = common_update_procedure(
                broken_update_image,
                devices=[device_id_2],
                devauth=devauth,
                deploy=deploy,
            )
            reboot[mender_device_1].verify_reboot_performed(REBOOT_MAX_WAIT)
            reboot[mender_device_2].verify_reboot_performed(
                REBOOT_MAX_WAIT, number_of_reboots=2
            )

        assert mender_device_1.yocto_id_installed_on_machine() == expected_image_id_1
        assert mender_device_2.yocto_id_installed_on_machine() != expected_image_id_2

        deploy.check_expected_status("finished", deployment_id_1)
        deploy.check_expected_status("finished", deployment_id_2)

        deploy.check_expected_statistics(deployment_id_1, "success", 1)
        deploy.get_logs(device_id_1, deployment_id_1, expected_status=404)

        deploy.check_expected_statistics(deployment_id_2, "failure", 1)
        assert "ArtifactVerifyReboot: Process exited with status 1" in deploy.get_logs(
            device_id_2, deployment_id_2
        )

    def do_test_deployment_two_devices_parallel_updates_one_aborted(
        self, env, valid_image_with_mender_conf
    ):
        device_group = env.device_group
        mender_device_1 = device_group[0]
        mender_device_2 = device_group[1]
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device_1.run("cat /etc/mender/mender.conf")
        valid_image = valid_image_with_mender_conf(mender_conf)

        ip_to_device_id = Helpers.ip_to_device_id_map(device_group, devauth=devauth)
        device_id_1 = ip_to_device_id[mender_device_1.host_string]
        device_id_2 = ip_to_device_id[mender_device_2.host_string]

        reboot = {mender_device_1: None, mender_device_2: None}
        with mender_device_1.get_reboot_detector(host_ip) as reboot[
            mender_device_1
        ], mender_device_2.get_reboot_detector(host_ip) as reboot[mender_device_2]:
            deployment_id_1, expected_image_id_1 = common_update_procedure(
                valid_image, devices=[device_id_1], devauth=devauth, deploy=deploy,
            )

            deployment_id_2, expected_image_id_2 = common_update_procedure(
                valid_image, devices=[device_id_2], devauth=devauth, deploy=deploy,
            )

            deploy.check_expected_statistics(deployment_id_2, "rebooting", 1)
            deploy.abort(deployment_id_2)

            reboot[mender_device_1].verify_reboot_performed(REBOOT_MAX_WAIT)
            reboot[mender_device_2].verify_reboot_performed(REBOOT_MAX_WAIT)

        deploy.check_expected_statistics(deployment_id_1, "success", 1)
        deploy.get_logs(device_id_1, deployment_id_1, expected_status=404)

        deploy.check_expected_statistics(deployment_id_2, "aborted", 1)
        deploy.get_logs(device_id_2, deployment_id_2, expected_status=404)

        assert mender_device_1.yocto_id_installed_on_machine() == expected_image_id_1
        assert mender_device_2.yocto_id_installed_on_machine() != expected_image_id_2

        deploy.check_expected_status("finished", deployment_id_1)
        deploy.check_expected_status("finished", deployment_id_2)

    def do_test_deployment_two_devices_parallel_updates_multiple_deployments(
        self, env, valid_image_with_mender_conf
    ):
        device_group = env.device_group
        mender_device_1 = device_group[0]
        mender_device_2 = device_group[1]
        devauth = DeviceAuthV2(env.auth)
        deploy = Deployments(env.auth, devauth)

        host_ip = env.get_virtual_network_host_ip()
        mender_conf = mender_device_1.run("cat /etc/mender/mender.conf")
        valid_image = valid_image_with_mender_conf(mender_conf)

        ip_to_device_id = Helpers.ip_to_device_id_map(device_group, devauth=devauth)
        device_id_1 = ip_to_device_id[mender_device_1.host_string]
        device_id_2 = ip_to_device_id[mender_device_2.host_string]

        reboot = {mender_device_1: None, mender_device_2: None}
        with mender_device_1.get_reboot_detector(host_ip) as reboot[
            mender_device_1
        ], mender_device_2.get_reboot_detector(host_ip) as reboot[mender_device_2]:
            deployment_id_1, expected_image_id_1 = common_update_procedure(
                valid_image, devices=[device_id_1], devauth=devauth, deploy=deploy,
            )

            with tempfile.NamedTemporaryFile() as tf:
                artifact_name = "%s-script-1" % device_id_2
                script_image = get_script_artifact(
                    b"exit 0", artifact_name, conftest.machine_name, tf.name,
                )
                deploy.upload_image(script_image)
                deployment_id_2 = deploy.trigger_deployment(
                    name="script 1", artifact_name=artifact_name, devices=[device_id_2],
                )

            with tempfile.NamedTemporaryFile() as tf:
                artifact_name = "%s-script-2" % device_id_2
                script_image = get_script_artifact(
                    b"exit 0", artifact_name, conftest.machine_name, tf.name,
                )
                deploy.upload_image(script_image)
                deployment_id_3 = deploy.trigger_deployment(
                    name="script 2", artifact_name=artifact_name, devices=[device_id_2],
                )

            reboot[mender_device_1].verify_reboot_performed(REBOOT_MAX_WAIT)
            reboot[mender_device_2].verify_reboot_not_performed(REBOOT_MAX_WAIT / 2)

        deploy.check_expected_statistics(deployment_id_1, "success", 1)
        deploy.get_logs(device_id_1, deployment_id_1, expected_status=404)

        deploy.check_expected_statistics(deployment_id_2, "success", 1)
        deploy.get_logs(device_id_2, deployment_id_2, expected_status=404)

        deploy.check_expected_statistics(deployment_id_3, "success", 1)
        deploy.get_logs(device_id_2, deployment_id_3, expected_status=404)

        assert mender_device_1.yocto_id_installed_on_machine() == expected_image_id_1

        deploy.check_expected_status("finished", deployment_id_1)
        deploy.check_expected_status("finished", deployment_id_2)
        deploy.check_expected_status("finished", deployment_id_3)


class TestMenderGatewayOpenSource(BaseTestMenderGateway):
    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_one_device(
        self,
        standard_setup_one_client_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_one_device(
            standard_setup_one_client_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_gateway_and_one_device(
        self,
        standard_setup_one_client_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
        image_with_mender_conf_and_mender_gateway_conf,
        gateway_image,
    ):
        self.do_test_deployment_gateway_and_one_device(
            standard_setup_one_client_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
            image_with_mender_conf_and_mender_gateway_conf,
            gateway_image,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_update_both(
        self,
        standard_setup_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_update_both(
            standard_setup_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_update_one(
        self,
        standard_setup_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_update_one(
            standard_setup_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates(
        self,
        standard_setup_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_parallel_updates(
            standard_setup_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates_one_failure(
        self,
        standard_setup_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
        broken_update_image,
    ):
        self.do_test_deployment_two_devices_parallel_updates_one_failure(
            standard_setup_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
            broken_update_image,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates_one_aborted(
        self,
        standard_setup_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_parallel_updates_one_aborted(
            standard_setup_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @pytest.mark.skip(reason="FIXME: QA-817")
    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates_multiple_deployments(
        self,
        standard_setup_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_parallel_updates_multiple_deployments(
            standard_setup_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )


class TestMenderGatewayEnterprise(BaseTestMenderGateway):
    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_one_device(
        self,
        enterprise_one_client_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_one_device(
            enterprise_one_client_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_gateway_and_one_device(
        self,
        enterprise_one_client_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
        image_with_mender_conf_and_mender_gateway_conf,
        gateway_image,
    ):
        self.do_test_deployment_gateway_and_one_device(
            enterprise_one_client_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
            image_with_mender_conf_and_mender_gateway_conf,
            gateway_image,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_update_both(
        self,
        enterprise_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_update_both(
            enterprise_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_update_one(
        self,
        enterprise_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_update_one(
            enterprise_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates(
        self,
        enterprise_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_parallel_updates(
            enterprise_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates_one_failure(
        self,
        enterprise_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
        broken_update_image,
    ):
        self.do_test_deployment_two_devices_parallel_updates_one_failure(
            enterprise_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
            broken_update_image,
        )

    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates_one_aborted(
        self,
        enterprise_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_parallel_updates_one_aborted(
            enterprise_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )

    @pytest.mark.skip(reason="FIXME: QA-817")
    @flaky(max_runs=3)
    @MenderTesting.fast
    def test_deployment_two_devices_parallel_updates_multiple_deployments(
        self,
        enterprise_two_clients_bootstrapped_with_gateway,
        valid_image_with_mender_conf,
    ):
        self.do_test_deployment_two_devices_parallel_updates_multiple_deployments(
            enterprise_two_clients_bootstrapped_with_gateway,
            valid_image_with_mender_conf,
        )
