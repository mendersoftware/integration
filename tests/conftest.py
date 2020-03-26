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

import logging
import requests
import filelock
import uuid
import subprocess
import os
import re
import pytest
import distutils.spawn
from . import log
from .tests.mendertesting import MenderTesting
from testutils.infra.container_manager.base import BaseContainerManagerNamespace
from testutils.infra.device import MenderDevice, MenderDeviceGroup

logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("paramiko").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("filelock").setLevel(logging.INFO)
logger = logging.getLogger()

production_setup_lock = filelock.FileLock(".exposed_ports_lock")

machine_name = None

try:
    requests.packages.urllib3.disable_warnings()
except:
    pass


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", help="run slow tests")
    parser.addoption("--runfast", action="store_true", help="run fast tests")

    parser.addoption(
        "--machine-name",
        action="store",
        default="qemux86-64",
        help="The machine name to test. Most common values are qemux86-64 and vexpress-qemu.",
    )


@pytest.fixture(scope="session")
def valid_image(request):
    return "core-image-full-cmdline-%s.ext4" % machine_name


@pytest.fixture(scope="session")
def valid_image_rofs(request):
    return "mender-image-full-cmdline-rofs-%s.ext4" % machine_name


def pytest_configure(config):
    verify_sane_test_environment()

    global machine_name
    machine_name = config.getoption("--machine-name")

    MenderTesting.set_test_conditions(config)


def unique_test_name(request):
    """Generate unique test names by prepending the class to the method name"""
    if request.node.cls is not None:
        return request.node.cls.__name__ + "__" + request.node.name
    else:
        return request.node.name


# If we have xdist installed, the testlogger fixture will include the thread id
try:
    import xdist

    @pytest.fixture(scope="function", autouse=True)
    def testlogger(request, worker_id):
        test_name = unique_test_name(request)
        log.setup_test_logger(test_name, worker_id)
        logger.info("%s is starting.... " % test_name)


except ImportError:

    @pytest.fixture(scope="function", autouse=True)
    def testlogger(request):
        test_name = unique_test_name(request)
        log.setup_test_logger(test_name)
        logger.info("%s is starting.... " % test_name)


def pytest_exception_interact(node, call, report):
    if report.failed:
        logger.error(
            "Test %s failed with exception:\n%s" % (node.name, call.excinfo.getrepr())
        )

        # Hack-ish way to inspect the fixtures in use by the node to find a MenderDevice/MenderDeviceGroup
        device = None
        env_candidates = [
            val
            for val in node.funcargs.values()
            if isinstance(val, BaseContainerManagerNamespace)
        ]
        if len(env_candidates) == 1:
            env = env_candidates[0]
            dev_candidates = [
                getattr(env, attr)
                for attr in dir(env)
                if isinstance(getattr(env, attr), MenderDevice)
                or isinstance(getattr(env, attr), MenderDeviceGroup)
            ]
            if len(dev_candidates) == 1:
                device = dev_candidates[0]

        # If we have a device (or group) try to print deployment and systemd logs
        if device == None:
            logger.info("Could not find device in test environment, no printing logs")
        else:
            try:
                logger.info("Printing client deployment log, if possible:")
                output = device.run("cat /data/mender/deployment*.log || true", wait=60)
                logger.info(output)
            except:
                logger.info("Not able to print client deployment log")
            try:
                logger.info("Printing client systemd log, if possible:")
                output = device.run(
                    "journalctl -u %s || true" % device.get_client_service_name(),
                    wait=60,
                )
                logger.info(output)
            except:
                logger.info("Not able to print client systemd log")

        # Note that this is not very fine grained, but running docker-compose -p XXXX ps seems
        # to ignore the filter
        output = subprocess.check_output(
            'docker ps --filter "status=exited"', shell=True
        ).decode()
        logger.info("Containers that exited during the test:")
        for line in output.split("\n"):
            logger.info(line)


def verify_sane_test_environment():
    # check if required tools are in PATH, add any other checks here
    if distutils.spawn.find_executable("mender-artifact") is None:
        raise SystemExit("mender-artifact not found in PATH")

    if distutils.spawn.find_executable("docker") is None:
        raise SystemExit("docker not found in PATH")

    ret = subprocess.call("docker ps > /dev/null", shell=True)
    if ret != 0:
        raise SystemExit(
            "not able to use docker, is your user part of the docker group?"
        )
