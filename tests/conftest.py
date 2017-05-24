#!/usr/bin/python
# Copyright 2016 Mender Software AS
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
import logging
import requests
from common_docker import stop_docker_compose, log_files
import random
import filelock
import uuid
import subprocess
import os

logging.basicConfig(level=logging.INFO)
logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("paramiko").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
docker_compose_instance = "mender" + str(random.randint(0, 9999999))

docker_lock = filelock.FileLock("docker_lock")
extra_files = []
inline_logs = False

try:
    requests.packages.urllib3.disable_warnings()
except:
    pass


def pytest_addoption(parser):
    parser.addoption("--clients", action="store", default="localhost:8080",
                     help="Comma-seperate mender hosts, example: 10.100.10.11:8822, 10.100.10.12:8822")
    parser.addoption("--gateway", action="store", default="127.0.0.1:8080",
                     help="Host of mender gateway")
    parser.addoption("--api", action="store", default="0.1", help="API version used in HTTP requests")
    parser.addoption("--image", action="store_true", default="core-image-full-cmdline-vexpress-qemu.ext4", help="Valid update image")
    parser.addoption("--runslow", action="store_true", help="run slow tests")
    parser.addoption("--runfast", action="store_true", help="run fast tests")
    parser.addoption("--runnightly", action="store_true", help="run nightly (very slow) tests")
    parser.addoption("--runs3", action="store_true", help="run fast tests")

    parser.addoption("--docker-compose-file", action="append", help="Additional docker-compose files to use for test")
    parser.addoption("--no-teardown", action="store_true", help="Don't tear down environment after tests are run")
    parser.addoption("--inline-logs", action="store_true", help="Don't redirect docker-compose logs to a file")


def pytest_configure(config):
    env.api_version = config.getoption("api")
    env.valid_image = config.getoption("image")

    extra_files = config.getoption("--docker-compose-file")
    inline_logs = config.getoption("--inline-logs")

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
    env.banner_timeout = 60


def pytest_exception_interact(node, call, report):
    if report.failed:
        for log in log_files:
            logging.info("printing content of : %s" % log)
            with open(log) as f:
                for line in f.readlines():
                    print line,


def pytest_unconfigure(config):
    if not config.getoption("--no-teardown"):
        stop_docker_compose()

    for log in log_files:
        try:
            os.remove(log)
        except:
            pass


def pytest_runtest_teardown(item, nextitem):
    if nextitem is None:
        stop_docker_compose()


def get_valid_image():
    return env.valid_image


def pytest_assertrepr_compare(op, left, right):
    """ catch all failed asserts in order to grab backend logs """
    logs_to_include = []

    if os.getenv("UPLOAD_BACKEND_LOGS_ON_FAIL", False):
        for logs in log_files:
            # we already have s3cmd configured on our build machine, so use it directly
            s3_object_name = str(uuid.uuid4()) + ".log"
            ret = subprocess.call("s3cmd put %s s3://mender-backend-logs/%s" % (logs, s3_object_name), shell=True)
            if int(ret) == 0:
                logs_to_include.append("https://s3-eu-west-1.amazonaws.com/mender-backend-logs/" + s3_object_name)
            else:
                logging.warn("uploading backend logs failed.")
    else:
        logging.warn("not uploading backend log files because UPLOAD_BACKEND_LOGS_ON_FAIL not set")

    if len(logs_to_include):
        return ["failed: assert %s %s %s" % (left, op, right), "backend logs: %s" % ('\n'.join(logs_to_include))]
    else:
        return ["failed: assert %s %s %s" % (left, op, right)]
