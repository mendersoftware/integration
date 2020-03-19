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
import os
import socket

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

    def yocto_id_installed_on_machine(self):
        cmd = "mender -show-artifact"
        output = self.run(cmd, hide=True).strip()
        return output

    def get_active_partition(self):
        cmd = "mount | awk '/on \/ / { print $1}'"
        active = self.run(cmd, hide=True)
        return active.strip()

    def get_passive_partition(self):
        active = self.get_active_partition()
        cmd = (
            "fdisk -l | grep $(blockdev --getsz %s) | grep -v %s | awk '{ print $1}'"
            % (active, active)
        )
        passive = self.run(cmd, hide=True)
        return passive.strip()

    def get_reboot_detector(self, host_ip):
        return RebootDetector(self, host_ip)


class RebootDetector:
    # This global one is used to increment each port used.
    port = 8181

    def __init__(self, device, host_ip):
        self.port = RebootDetector.port
        RebootDetector.port += 1
        self.host_ip = host_ip
        self.device = device
        self.server = None

    def __enter__(self):
        local_name = "test.mender-reboot-detector.txt.%s" % self.device.host_string
        with open(local_name, "w") as fd:
            fd.write("%s:%d" % (self.host_ip, self.port))
        try:
            self.device.put(
                local_name, remote_path="/data/mender/test.mender-reboot-detector.txt",
            )
        finally:
            os.unlink(local_name)

        self.device.run("systemctl restart mender-reboot-detector")

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host_ip, self.port))
        self.server.listen(1)

        return self

    def __exit__(self, type, value, trace):
        if self.server:
            self.server.close()
        self.server = None

        cmd = "systemctl stop mender-reboot-detector ; rm -f /data/mender/test.mender-reboot-detector.txt"
        try:
            self.device.run(cmd)
        except:
            logger.error("Unable to stop reboot-detector:\n%s", traceback.format_exc())
            # Only produce our own exception if we won't be hiding an
            # existing one.
            if type is None:
                raise

    def verify_reboot_performed_impl(self, max_wait, number_of_reboots=1):
        up = True
        reboot_count = 0
        start_time = time.time()
        while True:
            try:
                self.server.settimeout(start_time + max_wait - time.time())
                connection, _ = self.server.accept()
            except socket.timeout:
                logger.info("Client did not reboot in %d seconds", max_wait)
                return False

            message = connection.recv(4096).strip()
            connection.close()

            if message == "shutdown":
                logger.debug("Got shutdown message from client")
                if up:
                    up = False
                else:
                    raise RuntimeError(
                        "Received message of shutdown when already shut down??"
                    )
            elif message == "startup":
                logger.debug("Got startup message from client")
                # Tempting to check up flag here, but in the spontaneous
                # reboot case, we may not get the shutdown message.
                up = True
                reboot_count += 1
            else:
                raise RuntimeError(
                    "Unexpected message '%s' from mender-reboot-detector" % message
                )

            if reboot_count >= number_of_reboots:
                logger.info("Client has rebooted %d time(s)", reboot_count)
                return True

    def verify_reboot_performed(self, max_wait=60 * 60, number_of_reboots=1):
        if self.server is None:
            raise RuntimeError(
                "verify_reboot_performed() used outside of 'with' scope."
            )

        logger.info("Waiting for client to reboot %d time(s)", number_of_reboots)
        if not self.verify_reboot_performed_impl(
            max_wait=max_wait, number_of_reboots=number_of_reboots
        ):
            raise RuntimeError("Device never rebooted")

    def verify_reboot_not_performed(self, wait=60):
        if self.server is None:
            raise RuntimeError(
                "verify_reboot_not_performed() used outside of 'with' scope."
            )

        logger.info("Waiting %d seconds to check that client does not reboot", wait)
        if self.verify_reboot_performed_impl(max_wait=wait):
            raise RuntimeError("Device unexpectedly rebooted")


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
