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
import logging
import time

HAVE_TOKEN_TIMEOUT = 60 * 5
MENDER_STORE = '/data/mender/mender-store'


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


def run(cmd, *args, **kw):
    if kw.get('wait') is not None:
        wait = kw['wait']
        del kw['wait']
    else:
        wait = 60*60

    output = ""
    start_time = time.time()
    sleeptime = 1
    # Use shorter timeout to get a faster cycle. Not recommended though, since
    # in a heavily loaded environment, QEMU might be quite slow to use the
    # connection.
    with settings(timeout=60, abort_exception=Exception):
        while True:
            try:
                import fabric.api
                output = fabric.api.run(cmd, *args, **kw)
                break
            except Exception as e:
                if time.time() >= start_time + wait:
                    raise Exception("Could not connect to device")
                time.sleep(sleeptime)
                # Back off exponentially to save SSH handshakes in QEMU, which
                # are quite expensive.
                sleeptime *= 2
                continue
            finally:
                # Taken from disconnect_all() in Fabric.
                from fabric.state import connections
                if connections.get(env.host_string) is not None:
                    connections[env.host_string].close()
                    del connections[env.host_string]
    return output

# For now just alias sudo() to run(), since we always run as root. This may need
# to be changed later.
def sudo(*args, **kw):
    run(*args, **kw)


def have_token():
    """ Make sure the MENDER_STORE file exists after sometime, else fail test """

    sleepsec = 0
    while sleepsec < HAVE_TOKEN_TIMEOUT:
        try:
            run('strings {} | grep authtoken'.format(MENDER_STORE))
            return
        except Exception:
            sleepsec += 5
            time.sleep(5)
            logging.info("waiting for mender-store file, sleepsec: {}".format(sleepsec))

    assert sleepsec <= HAVE_TOKEN_TIMEOUT, "timeout for mender-store file exceeded"
