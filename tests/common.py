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
from fabric.contrib.files import *
from fabric.api import *
import time
import pytest
import conftest
import logging
from MenderAPI import adm, deploy, image

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

def put(file, local_path=".", remote_path="."):
    (scp, host, port) = scp_prep_args()

    local("%s %s %s/%s %s@%s:%s" %
          (scp, port, local_path, file, env.user, host, remote_path))


def ssh_prep_args():
    return ssh_prep_args_impl("ssh")


def scp_prep_args():
    return ssh_prep_args_impl("scp")


def ssh_prep_args_impl(tool):
    if not env.host_string:
        raise Exception("get()/put() called outside of execute()")

    cmd = ("%s -C -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" %
           tool)

    host_parts = env.host_string.split(":")
    host = ""
    port = ""
    port_flag = "-p"
    if tool == "scp":
        port_flag = "-P"
    if len(host_parts) == 2:
        host = host_parts[0]
        port = "%s%s" % (port_flag, host_parts[1])
    elif len(host_parts) == 1:
        host = host_parts[0]
        port = ""
    else:
        raise Exception("Malformed host string")

    return (cmd, host, port)



@pytest.fixture()
def bootstrapped_successfully():
    execute(bootstrapped_successfully_impl, hosts=conftest.get_mender_clients())


@parallel
def bootstrapped_successfully_impl():
    if len(adm.get_devices_status("accepted")) == len(conftest.get_mender_clients()):
        return

    # iterate over devices and accept them
    for d in adm.get_devices():
        adm.set_device_status(d["id"], "accepted")

    logger.info("Successfully bootstrap all clients")


def run_after_connect(cmd):
    return ssh_is_opened_impl(cmd)


@pytest.fixture(scope="function")
def ssh_is_opened():
    execute(ssh_is_opened_impl, hosts=conftest.get_mender_clients())


@parallel
def ssh_is_opened_impl(cmd="true", wait=60):
    count = 0

    while count < wait:
        try:
            # no point in printing this with each test
            with quiet():
                return run(cmd)
        except BaseException:
            time.sleep(1)
            count += 1
            continue
        else:
            break

    if count >= 60:
        logging.fail("Unable to connect to host: ", env.host_string)
