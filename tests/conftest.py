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

logging.basicConfig(level=logging.INFO)
logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("paramiko").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

try:
    requests.packages.urllib3.disable_warnings()
except:
    pass

def pytest_addoption(parser):
    parser.addoption("--clients", action="store",
                     help="Comma-seperate mender hosts, example: 10.100.10.11:8822, 10.100.10.12:8822")
    parser.addoption("--gateway", action="store", default="127.0.0.1:8080",
                     help="Host of mender gateway")
    parser.addoption("--api", action="store", default="0.1", help="API version used in HTTP requests")
    parser.addoption("--image", action="store_true", default="core-image-full-cmdline-vexpress-qemu.ext4", help="Valid update image")
    parser.addoption("--runslow", action="store_true", help="run slow tests")
    parser.addoption("--runfast", action="store_true", help="run fast tests")


def pytest_configure(config):
    env.clients = [ip.strip() for ip in config.getoption("clients").split(",")]
    env.mender_gateway = config.getoption("gateway")
    env.api_version = config.getoption("api")
    env.valid_image = config.getoption("image")

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


def get_mender_clients():
    return env.clients


def get_valid_image():
    return env.valid_image
