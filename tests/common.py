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
from fabric.contrib.files import *
from fabric.api import *
from requests.auth import HTTPBasicAuth
import time

# This is used to remember which docker-compose setup we're currently running.
# This is for optimization purposes to avoid respawning the docker-compose
# environment if we don't have to.
SETUP_TYPE = None

ST_NoClient = 0
ST_OneClient = 1
ST_OneClientBootstrapped = 2
ST_TwoClientsBootstrapped = 3
ST_OneClientsBootstrapped_AWS_S3 = 4
ST_SignedClient = 5
ST_ShortLivedAuthToken = 6
ST_CustomSetup = 7
ST_MultiTenancyNoClient = 8



def setup_type():
    return SETUP_TYPE


def set_setup_type(type):
    global SETUP_TYPE
    SETUP_TYPE = type

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


def run_after_connect(cmd, wait = 300):
    output = ""
    start_time = time.time()
    # Use shorter timeout to get a faster cycle.
    with settings(timeout = 5, abort_exception = Exception):
        while True:
            attempt_time = time.time()
            try:
                output = run(cmd)
                break
            except Exception as e:
                print("Could not connect to host %s: %s" % (env.host_string, e))
                if attempt_time >= start_time + wait:
                    raise Exception("Could not reconnect to QEMU")
                now = time.time()
                if now - attempt_time < 5:
                    time.sleep(5 - (now - attempt_time))
                continue
    return output

