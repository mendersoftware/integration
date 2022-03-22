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

import distutils.spawn
import logging
import os
import subprocess
import shutil
import tempfile
from distutils.version import LooseVersion

import filelock
import pytest
from testutils.infra.container_manager.base import BaseContainerManagerNamespace
from testutils.infra.device import MenderDevice, MenderDeviceGroup

from . import log
from .tests.mendertesting import MenderTesting

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RELEASE_TOOL = os.path.join(THIS_DIR, "..", "extra", "release_tool.py")

logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("paramiko").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("filelock").setLevel(logging.INFO)
logging.getLogger("redo").setLevel(logging.INFO)
logger = logging.getLogger()

production_setup_lock = filelock.FileLock(".exposed_ports_lock")

machine_name = None


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


def add_mender_conf_to_image(image, d, mender_conf):
    """Copy image to the dir 'd', and replace the images /etc/mender/mender.conf
    with the contents of the string 'mender_conf'"""

    mender_conf_tmp = os.path.join(d, "mender.conf")

    with open(mender_conf_tmp, "w") as f:
        f.write(mender_conf)

    new_image = os.path.join(d, image)
    shutil.copy(image, new_image)

    instr_file = os.path.join(d, "write.instr")
    with open(os.path.join(d, "write.instr"), "w") as f:
        f.write(
            """cd /etc/mender
        rm mender.conf
        write {local} mender.conf""".format(
                local=mender_conf_tmp
            )
        )
    subprocess.run(
        ["debugfs", "-w", "-f", instr_file, new_image],
        check=True,
        stdout=subprocess.PIPE,
    )

    res = subprocess.run(
        ["debugfs", "-R", "cat /etc/mender/mender.conf", new_image],
        check=True,
        stdout=subprocess.PIPE,
    )

    assert "ServerURL" in res.stdout.decode()

    return new_image


@pytest.fixture(scope="function")
def valid_image_with_mender_conf(request, valid_image):
    """Insert the given mender_conf into a valid_image"""
    with tempfile.TemporaryDirectory() as d:

        def cleanup():
            shutil.rmtree(d, ignore_errors=True)

        request.addfinalizer(cleanup)
        yield lambda conf: add_mender_conf_to_image(valid_image, d, conf)


@pytest.fixture(scope="session")
def valid_image_rofs_with_mender_conf(request):
    valid_image = "mender-image-full-cmdline-rofs-%s.ext4" % machine_name
    if not os.path.exists(valid_image):
        yield None
        return

    with tempfile.TemporaryDirectory() as d:

        def cleanup():
            shutil.rmtree(d, ignore_errors=True)

        request.addfinalizer(cleanup)
        yield lambda conf: add_mender_conf_to_image(valid_image, d, conf)


def pytest_configure(config):
    verify_sane_test_environment()

    global machine_name
    machine_name = config.getoption("--machine-name")

    MenderTesting.set_test_conditions(config)

    config.addinivalue_line(
        "markers",
        "min_mender_client_version: indicate lowest Mender client version for which the test will run",
    )


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

        # Inspect the fixtures in use by the node to find instances of MenderDevice/MenderDeviceGroup
        devices = []
        env_candidates = []
        if getattr(node, "funcargs", None) is not None:
            env_candidates = [
                val
                for val in node.funcargs.values()
                if isinstance(val, BaseContainerManagerNamespace)
            ]
        if len(env_candidates) > 0:
            env = env_candidates[0]
            dev_candidates = [
                getattr(env, attr)
                for attr in dir(env)
                if isinstance(getattr(env, attr), MenderDevice)
                or isinstance(getattr(env, attr), MenderDeviceGroup)
            ]
            if len(dev_candidates) >= 1:
                devices = dev_candidates

        # If we have devices (or groups) try to print deployment and systemd logs
        if devices is []:
            logger.info("Could not find devices in test environment, no printing logs")
        else:

            def run_remote_command(instances, command):
                """Log command output for a list of MenderDevice and/or MenderDeviceGroup."""
                for instance in instances:
                    logger.info("Executing %s in instance %s", command, instance)

                    output = instance.run(command, wait=60)

                    if isinstance(instance, MenderDevice):
                        logger.info(output)
                    else:
                        for dev, log in output.items():
                            logger.info("Printing output of device %s", dev)
                            logger.info(log)

            try:
                logger.info("Printing client deployment log, if possible:")
                run_remote_command(devices, "cat /data/mender/deployment*.log || true")

            except:
                logger.info("Not able to print client deployment log")

            for service in [
                "mender-client",
                "mender-connect",
                "mender-monitor",
                "mender-gateway",
            ]:
                try:
                    logger.info("Printing %s systemd log, if possible:" % service)
                    run_remote_command(devices, "journalctl -u %s || true" % service)
                except:
                    logger.info("Not able to print %s systemd log" % service)

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


@pytest.fixture(autouse=True)
def min_mender_client_version(request):
    version_marker = request.node.get_closest_marker("min_mender_client_version")
    if version_marker is None:
        # No marker, assume it shall run for all versions
        return

    mender_client_version = (
        subprocess.check_output([RELEASE_TOOL, "--version-of", "mender"])
        .decode()
        .strip()
    )
    min_required_version = version_marker.args[0]

    if not version_is_minimum(mender_client_version, min_required_version):
        pytest.skip("Test requires Mender client %s or newer" % min_required_version)


def version_is_minimum(version, min_version):
    try:
        if LooseVersion(min_version) > LooseVersion(version):
            return False
        else:
            return True
    except TypeError:
        # Type error indicates that 'version' is likely a string (branch
        # name). Default to always consider them higher than the minimum version.
        return True
