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

import time
import logging

import fabric

logger = logging.getLogger()


class MenderDevice:
    """SSH accessible device with Mender client

    This class presents a convinient interface for tests and helpers to perform
    remote commands execution or sending/receiving files.
    """

    def __init__(self, host_string="localhost:8822", user="root"):
        """Create a MenderDevice object-

        Keyword arguments:
        host_string -- Remote SSH host of the form host:port
        user -- Remote SSH user
        """
        self.host, self.port = host_string.split(":")

    @property
    def host_string(self):
        return "%s:%s" % (self.host, self.port)

    def run(self, cmd, **kw):
        """Run given cmd in remote SSH host

        Argument:
        cmd - sring with the command to execute remotely

        Recognized keyword arguments:
        hide - do not print stdout nor stderr, and do not fail on errors
        warn_only - do not fail on errors
        wait - timeout for how long to retry the execution

        References for Fabric 2 migration:
        - https://www.fabfile.org/upgrading.html#upgrading
        - http://docs.pyinvoke.org/en/latest/api/runners.html#invoke.runners.Runner.run
        - https://docs.fabfile.org/en/1.12.1/api/core/context_managers.html#fabric.context_managers.quiet
        """
        if kw.get("hide") == True:
            del kw["hide"]
            with fabric.api.quiet():
                return self._run(cmd, **kw)
        elif kw.get("warn_only") == True:
            del kw["warn_only"]
            with fabric.api.settings(warn_only=True):
                return self._run(cmd, **kw)
        else:
            return self._run(cmd, **kw)

    def _run(self, cmd, **kw):
        if not fabric.api.env.host_string:
            output = fabric.api.execute(self.run, cmd, hosts=self.host_string, **kw)
            # Fabric's execute returns a dict with the output
            # for each host. Return only our output
            return output[self.host_string]

        return _run(cmd, **kw)

    def put(self, file, local_path=".", remote_path="."):
        """Copy local_path/file into remote_path over SSH connection

        Keyword arguments:
        file - local filename
        local_path - local dirpath
        remote_path - remote dirpath
        """
        if not fabric.api.env.host_string:
            fabric.api.execute(
                self.put, file, local_path, remote_path, hosts=self.host_string
            )
            return

        _put(file, local_path, remote_path)

    def ssh_is_opened(self, wait=60 * 60):
        """Block until SSH connection is established on the device

        Keyword arguments:
        wait - Timeout (in seconds)
        """
        self.run("true", hide=True, wait=wait)


class MenderDeviceGroup:
    """Group of SSH accessible devices with Mender client

    Currently, run/put methods are serialized, but they will be migrated to a parallel execution with Fabric 2
    https://docs.fabfile.org/en/latest/api/group.html
    """

    def __init__(self, host_string_list, user="root"):
        self._devices = []
        for host_string in host_string_list:
            self._devices.append(MenderDevice(host_string))

    def __len__(self):
        return len(self._devices)

    def __getitem__(self, idx):
        return self._devices[idx]

    def run(self, cmd, **kw):
        """Run command for all devices in group sequentially

        see MenderDevice.run
        """
        output_dict = dict()
        for dev in self._devices:
            output = dev.run(cmd, **kw)
            output_dict[dev.host_string] = output
        return output_dict

    def ssh_is_opened(self, wait=60 * 60):
        """Block until SSH connection is established for all devices in group sequentially

        see MenderDevice.ssh_is_opened
        """
        for dev in self._devices:
            dev.ssh_is_opened(wait)


def _ssh_prep_args():
    return _ssh_prep_args_impl("ssh")


def _scp_prep_args():
    return _ssh_prep_args_impl("scp")


def _ssh_prep_args_impl(tool):
    if not fabric.api.env.host_string:
        raise Exception("get()/put() called outside of execute()")

    cmd = "%s -C -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" % tool

    host_parts = fabric.api.env.host_string.split(":")
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


def _put(file, local_path=".", remote_path="."):
    (scp, host, port) = _scp_prep_args()

    fabric.api.local(
        "%s %s %s/%s %s@%s:%s"
        % (scp, port, local_path, file, fabric.api.env.user, host, remote_path)
    )


def _run(cmd, **kw):
    if kw.get("wait") is not None:
        wait = kw["wait"]
        del kw["wait"]
    else:
        wait = 60 * 60

    output = ""
    start_time = time.time()
    sleeptime = 1
    # Use shorter timeout to get a faster cycle. Not recommended though, since
    # in a heavily loaded environment, QEMU might be quite slow to use the
    # connection.
    with fabric.api.settings(timeout=60, abort_exception=Exception):
        while True:
            try:
                output = fabric.api.run(cmd, **kw)
                break
            except Exception:
                if time.time() >= start_time + wait:
                    raise Exception("Could not successfully run: %s" % cmd)
                time.sleep(sleeptime)
                # Back off exponentially to save SSH handshakes in QEMU, which
                # are quite expensive.
                sleeptime *= 2
                continue
            finally:
                # Taken from disconnect_all() in Fabric.
                from fabric.state import connections

                if connections.get(fabric.api.env.host_string) is not None:
                    connections[fabric.api.env.host_string].close()
                    del connections[fabric.api.env.host_string]

    return output
