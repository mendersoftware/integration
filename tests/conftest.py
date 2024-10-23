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

import logging
import os
import subprocess
import shutil
import tempfile
import yaml
import packaging.version

import filelock
import pytest
from filelock import FileLock
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


def _extract_fs_from_image(request, client_compose_file, filename):
    if os.path.exists(os.path.join(THIS_DIR, filename)):
        return filename
    d = os.path.join(THIS_DIR, "output")
    image_type = "mender-client"
    if "gateway" in client_compose_file:
        image_type = "mender-gateway"

    image = (
        subprocess.check_output(
            [
                "docker-compose",
                "-f",
                client_compose_file,
                "config",
                "--images",
                image_type,
            ],
            env=os.environ,
        )
        .decode("UTF-8")
        .strip()
        .split("\n")[0]
    )

    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--privileged",
            "--entrypoint",
            "/extract_fs",
            "--volume",
            d + ":/output",
            image,
        ]
    )

    if not os.path.exists(os.path.join(THIS_DIR, filename)):
        shutil.move(os.path.join(d, filename), THIS_DIR)

    def cleanup():
        shutil.rmtree(d, ignore_errors=True)

    request.addfinalizer(cleanup)

    return filename


def _image(request, compose_file, filename):
    return _extract_fs_from_image(
        request, os.path.join(THIS_DIR, "..", compose_file), filename
    )


# https://pytest-xdist.readthedocs.io/en/latest/how-to.html#making-session-scoped-fixtures-execute-only-once
def run_if_non_existent(request, tmp_path_factory, compose_file, filename):
    """
    Makes session scoped fixtures only run once
    to avoid conflict while running multiple workers with xdist
    """
    root_tmp_dir = tmp_path_factory.getbasetemp().parent
    file_lock = root_tmp_dir / filename

    with FileLock(f"{file_lock}.lock"):
        if file_lock.is_file() and os.path.exists(os.path.join(THIS_DIR, filename)):
            return filename
    return _image(request, compose_file, filename)


@pytest.fixture(scope="session")
def valid_image(request, tmp_path_factory, worker_id):
    compose_file = "docker-compose.client.yml"
    filename = f"core-image-full-cmdline-{machine_name}.ext4"

    if worker_id == "master":
        return _image(request, compose_file, filename)

    return run_if_non_existent(request, tmp_path_factory, compose_file, filename)


@pytest.fixture(scope="session")
def gateway_image(request, tmp_path_factory, worker_id):
    compose_file = "docker-compose.mender-gateway.commercial.yml"
    filename = f"mender-gateway-image-full-cmdline-{machine_name}.ext4"

    if worker_id == "master":
        return _image(request, compose_file, filename)

    return run_if_non_existent(request, tmp_path_factory, compose_file, filename)


def _special_image(request, image, command):
    subprocess.run(command, check=True)
    return image


@pytest.fixture(scope="session")
def broken_network_image(request, valid_image):
    image = f"core-image-full-cmdline-{machine_name}-broken-network.ext4"
    shutil.copy(valid_image, image)
    return _special_image(
        request,
        image,
        ["debugfs", "-w", "-R", "rm /lib/systemd/systemd-networkd", image],
    )


@pytest.fixture(scope="session")
def large_image(request):
    return _special_image(
        request,
        "large_image.dat",
        ["dd", "if=/dev/zero", "of=large_image.dat", "bs=500M", "count=1"],
    )


@pytest.fixture(scope="session")
def broken_update_image(request):
    return _special_image(
        request,
        "broken_update.ext4",
        ["dd", "if=/dev/urandom", "of=broken_update.ext4", "bs=10M", "count=5"],
    )


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


@pytest.fixture(scope="session")
def valid_image_with_mender_conf(request, valid_image):
    """Insert the given mender_conf into a valid_image"""
    with tempfile.TemporaryDirectory() as d:

        def cleanup():
            shutil.rmtree(d, ignore_errors=True)

        request.addfinalizer(cleanup)
        yield lambda conf: add_mender_conf_to_image(valid_image, d, conf)


@pytest.fixture(scope="session")
def valid_image_rofs_with_mender_conf(request):

    valid_image = _image(
        request,
        "docker-compose.client.rofs.yml",
        f"mender-image-full-cmdline-rofs-{machine_name}.ext4",
    )

    if not os.path.exists(valid_image):
        yield None
        return

    with tempfile.TemporaryDirectory() as d:

        def cleanup():
            shutil.rmtree(d, ignore_errors=True)

        request.addfinalizer(cleanup)
        yield lambda conf: add_mender_conf_to_image(valid_image, d, conf)


@pytest.fixture(scope="session")
def valid_image_rofs_commercial_with_mender_conf(request):

    valid_image = _image(
        request,
        "docker-compose.client.rofs.commercial.yml",
        f"mender-image-full-cmdline-rofs-commercial-{machine_name}.ext4",
    )

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

            def log_and_maybe_truncate(output):
                """For long entries, log the last 10k chars as info and all as debug"""
                if len(output) > 10000:
                    logger.info(output[-10000:])
                    logger.info(
                        "... (truncated, see test log file for complete output)"
                    )
                    logger.debug(output)
                else:
                    logger.info(output)

            def run_remote_command(instances, command):
                """Log command output for a list of MenderDevice and/or MenderDeviceGroup."""
                for instance in instances:
                    logger.info("Executing %s in instance %s", command, instance)

                    output = instance.run(command, wait=60)

                    if isinstance(instance, MenderDevice):
                        log_and_maybe_truncate(output)
                    else:
                        for dev, log in output.items():
                            logger.info("Printing output of device %s", dev)
                            log_and_maybe_truncate(log)

            try:
                logger.info("Printing client deployment log, if possible:")
                run_remote_command(devices, "cat /data/mender/deployment*.log || true")

            except:
                logger.info("Not able to print client deployment log")

            for service in [
                "mender-authd",
                "mender-updated",
                "mender-connect",
                "mender-monitor",
                "mender-gateway",
                "mender-client",
                "mender",
            ]:
                try:
                    logger.info("Printing %s systemd log, if possible:" % service)
                    run_remote_command(
                        devices,
                        "journalctl --unit=%s --output=cat --no-tail --no-pager || true"
                        % service,
                    )
                except:
                    logger.info("Not able to print %s systemd log" % service)

        # Note that this is not very fine grained, but running docker-compose -p XXXX ps seems
        # to ignore the filter
        output = subprocess.check_output("docker ps -a", shell=True).decode()
        logger.info("Containers at the end of the test:")
        for line in output.split("\n"):
            logger.info(line)


def verify_sane_test_environment():
    # check if required tools are in PATH, add any other checks here
    if shutil.which("mender-artifact") is None:
        raise SystemExit("mender-artifact not found in PATH")

    if shutil.which("docker") is None:
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


@pytest.fixture(autouse=True)
def mender_client_version():
    return (
        subprocess.check_output([RELEASE_TOOL, "--version-of", "mender"])
        .decode()
        .strip()
    )


def version_is_minimum(version, min_version):
    try:
        version_parsed = packaging.version.Version(version)
    except packaging.version.InvalidVersion:
        # Indicates that 'version' is likely a string (branch name).
        # Always consider them higher than the minimum version.
        return True

    return version_parsed >= packaging.version.Version(min_version)
