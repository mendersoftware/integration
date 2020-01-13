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
from testutils.infra.container_manager import log_files

logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("paramiko").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("filelock").setLevel(logging.INFO)
logger = log.setup_custom_logger("root", "master")
logging.getLogger().setLevel(logging.INFO)

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


def pytest_runtest_setup(item):
    logger = log.setup_custom_logger("root", item.name)
    logger.info("%s is starting.... " % item.name)

def pytest_exception_interact(node, call, report):
    if report.failed:
        logging.error("Test %s failed with exception:\n%s" % (str(node), call.excinfo.getrepr()))
        for log in log_files:
            logger.info("printing content of : %s" % log)
            logger.info("Running with PID: %d, PPID: %d" % (os.getpid(), os.getppid()))
            with open(log) as f:
                for line in f.readlines():
                    logger.info("%s: %s" % (log, line))

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


@pytest.mark.hookwrapper
def pytest_runtest_makereport(item, call):
    pytest_html = item.config.pluginmanager.getplugin('html')
    if pytest_html is None:
        yield
        return
    outcome = yield
    report = outcome.get_result()
    extra = getattr(report, 'extra', [])
    if report.failed:
        url = ""
        if os.getenv("UPLOAD_BACKEND_LOGS_ON_FAIL", False):
            if len(log_files) > 0:
                # we already have s3cmd configured on our build machine, so use it directly
                s3_object_name = str(uuid.uuid4()) + ".log"
                ret = subprocess.call("s3cmd put %s s3://mender-backend-logs/%s" % (log_files[-1], s3_object_name), shell=True)
                if int(ret) == 0:
                    url = "https://s3-eu-west-1.amazonaws.com/mender-backend-logs/" + s3_object_name
                else:
                    logger.warn("uploading backend logs failed.")
            else:
                logger.warn("no log files found, did the backend actually start?")
        else:
            logger.warn("not uploading backend log files because UPLOAD_BACKEND_LOGS_ON_FAIL not set")

        # always add url to report
        extra.append(pytest_html.extras.url(url))
        report.extra = extra

def pytest_unconfigure(config):
    for log in log_files:
        try:
            os.remove(log)
        except:
            pass

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
