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

from platform import python_version
if python_version().startswith('2'):
    from fabric.api import *
else:
    # User should re-implement: ???
    pass

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

    parser.addoption("--machine-name", action="store", default="qemux86-64",
                     help="The machine name to test. Most common values are qemux86-64 and vexpress-qemu.")


def pytest_configure(config):
    verify_sane_test_environment()

    global machine_name
    machine_name = config.getoption("--machine-name")
    env.valid_image = "core-image-full-cmdline-%s.ext4" % machine_name

    env.password = ""

    # Bash not always available, nor currently required:
    env.shell = "/bin/sh -c"

    # Disable known_hosts file, to avoid "host identification changed" errors.
    env.disable_known_hosts = True

    env.abort_on_prompts = True
    # Don't allocate pseudo-TTY by default, since it is not fully functional.
    # It can still be overriden on a case by case basis by passing
    # "pty = True/False" to the various fabric functions. See
    # https://www.fabfile.org/faq.html about init scripts.
    env.always_use_pty = False

    # Don't combine stderr with stdout. The login profile sometimes prints
    # terminal specific codes there, and we don't want it interfering with our
    # output. It can still be turned on on a case by case basis by passing
    # combine_stderr to each run() or sudo() command.
    env.combine_stderr = False

    env.user = "root"

    env.connection_attempts = 50
    env.eagerly_disconnect = True
    env.banner_timeout = 10

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
        logger.error("Test %s failed with exception:\n%s" % (str(node), call.excinfo.getrepr()))
        try:
            logger.info("Printing client deployment log, if possible:")
            output = execute(run, "cat /data/mender/deployment*.log || true", hosts=get_mender_clients())
            logger.info(output)
        except:
            logger.info("Not able to print client deployment log")

        try:
            logger.info("Printing client systemd log, if possible:")
            output = execute(run, "journalctl -u mender || true", hosts=get_mender_clients())
            logger.info(output)
        except:
            logger.info("Not able to print client systemd log")

        # Note that this is not very fine grained, but running docker-compose -p XXXX ps seems
        # to ignore the filter
        output = subprocess.check_output('docker ps --filter "status=exited"', shell=True)
        logger.info("Containers that exited during the test:")
        for line in output.split('\n'):
            logger.info(line)

def get_valid_image():
    return env.valid_image

def verify_sane_test_environment():
    # check if required tools are in PATH, add any other checks here
    if distutils.spawn.find_executable("mender-artifact") is None:
        raise SystemExit("mender-artifact not found in PATH")

    if distutils.spawn.find_executable("docker") is None:
        raise SystemExit("docker not found in PATH")

    ret = subprocess.call("docker ps > /dev/null", shell=True)
    if ret != 0:
        raise SystemExit("not able to use docker, is your user part of the docker group?")
