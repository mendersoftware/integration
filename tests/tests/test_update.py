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
from common import *
from common_setup import *
from common_docker import *
from mendertesting import MenderTesting
from common_update import common_update_procedure
from MenderAPI import auth, adm, deploy, inv, deviceauth
import subprocess
import time
import conftest
import shutil
import filelock
import re

def setup_docker_volumes():
    docker_volumes = ["mender-artifacts",
                      "mender-deployments-db",
                      "mender-deviceauth-db",
                      "mender-redis-db",
                      "mender-elasticsearch-db",
                      "mender-inventory-db",
                      "mender-useradm-db"]

    for volume in docker_volumes:
        ret = subprocess.call(["docker", "volume", "create", "--name=%s" % volume])
        assert ret == 0, "failed to create docker volumes"


def setup_upgrade_source(upgrade_from):
    if os.path.exists("upgrade-from"):
        shutil.rmtree("upgrade-from")

    ret = subprocess.call(["git", "clone", "https://github.com/mendersoftware/integration", "-b", upgrade_from, "upgrade-from"])
    assert ret == 0, "failed to git clone old source version"

    # start upgrade source and bring up it's production environment
    ret = subprocess.call(["bash", "run.sh", "--get-requirements"],
                          cwd="upgrade-from/tests")
    assert ret == 0, "failed running 'run.sh --get-requirements' on upgrade source"

    ret = subprocess.call(["python", "production_test_env.py", "--start",
                           "--docker-compose-instance", conftest.docker_compose_instance],
                          cwd="upgrade-from/tests")
    assert ret == 0, "failed running 'production_test_env.py start' on upgrade source"


def perform_upgrade():
    ret = subprocess.call(["cp", "-r", "tests/upgrade-from/keys-generated", "."], cwd="..")
    assert ret == 0, "faled to copy keys from original environment"

    subprocess.check_call(["./production_test_env.py", "--start",
                           "--docker-compose-instance", conftest.docker_compose_instance])

    # give time for all microservices to come online
    time.sleep(60 * 5)


def setup_fake_clients(device_count, fail_count):
    p = subprocess.Popen(["mender-stress-test-client",
                         "-count=%s" % str(device_count),
                         "-invfreq=5",
                         "-pollfreq=5",
                         "-wait=10",
                         "-failcount=%s" % str(fail_count)])
    return p


def provision_upgrade_server():
    # deploy update to 10 devices
    ret = subprocess.Popen(["python", "production_test_env.py", "--test-deployment",
                            "--docker-compose-instance", conftest.docker_compose_instance],
                           cwd="upgrade-from/tests", stdout=subprocess.PIPE)
    time.sleep(120)

    # extract deployment_id and artifact_id from piped output
    output = ret.stdout.read()
    devices = re.search("devices=(.*)", output).group(1)
    deployment_id = re.search("deployment_id=(.*)", output).group(1)
    artifact_id = re.search("artifact_id=(.*)", output).group(1)

    return devices, deployment_id, artifact_id


class BackendUpdating():
    fake_client_process = None
    provisioned_devices = None
    provisioned_deployment_id = None
    provisioned_artifact_id = None

    def __init__(self, upgrade_from):
        setup_docker_volumes()
        setup_upgrade_source(upgrade_from)
        self.fake_client_process = setup_fake_clients(10, 3)
        self.provisioned_devices, self.provisioned_deployment_id, self.provisioned_artifact_id = provision_upgrade_server()
        perform_upgrade()

    def teardown(self):
        self.fake_client_process.kill()

    def test_original_deployments_persisted(self):
        auth.reset_auth_token()
        auth.get_auth_token()

        # wait for 10 devices to be available
        devices = adm.get_devices_status("accepted", 10)
        provisioned_devices = eval(self.provisioned_devices)

        # check that devices and provisioned_devices are the same
        assert len(devices) == provisioned_devices
        # not sure what else I can do here, the device admission changed from 1.0 to master

        assert deploy.get_statistics(self.provisioned_deployment_id)["success"] == 7
        assert deploy.get_statistics(self.provisioned_deployment_id)["failure"] == 3

        # check failures still contain logs
        for device_deployment in deploy.get_deployment_overview(self.provisioned_deployment_id):
            if device_deployment["status"] == "failure":
                assert "damn" in deploy.get_logs(device_deployment["id"], self.provisioned_deployment_id)

        deployments_in_progress = deploy.get_status("inprogress")
        deployments_pending = deploy.get_status("pending")
        deployments_finished = deploy.get_status("finished")

        assert len(deployments_in_progress) == 0
        assert len(deployments_pending) == 0
        assert len(deployments_finished) == 1

        assert self.provisioned_artifact_id in str(deployments_finished)

    def test_inventory_post_upgrade(self):
        inventory = inv.get_devices()
        for inventory_item in inventory:
            for inventory_pair in inventory_item["attributes"]:

                # make sure time was updated recently
                if inventory_pair["name"] == "time":
                    assert int(time.time()) - int(inventory_pair["value"]) <= 10

                # and other invetory items are still present
                elif inventory_pair["name"] == "device_type":
                    assert inventory_pair["value"] == "test"
                elif inventory_pair["name"] == "image_id":
                    assert inventory_pair["value"] == "test"

    def test_deployments_post_upgrade(self):
        adm.get_devices_status("accepted", 10)

        # perform upgrade
        devices_to_update = list(set([device["device_id"] for device in adm.get_devices_status("accepted", expected_devices=10)]))
        deployment_id, artifact_id = common_update_procedure("core-image-full-cmdline-%s.ext4" % conftest.machine_name,
                                                             device_type="test",
                                                             devices=devices_to_update)

        deploy.check_expected_status("finished", deployment_id)
        assert deploy.get_statistics(deployment_id)["success"] == 7
        assert deploy.get_statistics(deployment_id)["failure"] == 3

        deploy.get_status("finished")

    def test_artifacts_persisted(self):
        devices_to_update = list(set([device["device_id"] for device in adm.get_devices_status("accepted", expected_devices=10)]))
        deployment_id = deploy.trigger_deployment(name="artifact survived backed upgrade",
                                                  artifact_name=self.provisioned_artifact_id,
                                                  devices=devices_to_update)
        deploy.check_expected_status("finished", deployment_id)

    def test_decommissioning_post_upgrade(self):
        # assertion error occurs here on decommissioning fail
        for device in adm.get_devices(10):
            deviceauth.decommission(device["device_id"])


@MenderTesting.upgrade_from
@pytest.mark.usefixtures("running_custom_production_setup")
@pytest.mark.parametrize("upgrade_from", [s.strip() for s in pytest.config.getoption("--upgrade-from").split(",")])
def test_run_upgrade_test(upgrade_from):
    # run these tests sequentially since they expose the storage proxy and the api gateports to the host
    with filelock.FileLock(".update_test_lock"):
        t = None
        try:
            t = BackendUpdating(upgrade_from)
            t.test_original_deployments_persisted()
            t.test_inventory_post_upgrade()
            t.test_deployments_post_upgrade()
            t.test_artifacts_persisted()
            t.test_decommissioning_post_upgrade()
        except Exception, e:
            # exception is handled by pytest
            raise e
        finally:
           if isinstance(t, BackendUpdating):
               t.teardown()
