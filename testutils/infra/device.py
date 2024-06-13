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

import time
import logging
import traceback
import os
import redo
import socket
import subprocess
import time
from typing import Dict

logger = logging.getLogger()


class Result:
    def __init__(self, stdout, stderr, exited):
        self.stdout = stdout
        self.stderr = stderr
        self.exited = exited
        self.return_code = exited


class Connection:
    def __init__(self, host, user, port, connect_timeout, connect_kwargs={}):
        self.host = host
        self.user = user
        self.port = port
        self.connect_timeout = connect_timeout
        self.connect_kwargs = connect_kwargs

        self.key_filename = None

        for k in connect_kwargs.keys():
            if k == "key_filename":
                self.key_filename = connect_kwargs[k]

    def get_connect_args(self):
        if self.key_filename is not None:
            key_arg = ["-i", self.key_filename]
        else:
            key_arg = []

        args = (
            ["ssh"]
            + key_arg
            + [
                "-p",
                str(self.port),
                "-o",
                f"ConnectTimeout={self.connect_timeout}",
                "-o",
                "ServerAliveInterval=60",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "StrictHostKeyChecking=no",
                f"{self.user}@{self.host}",
            ]
        )

        return args

    def run(self, command, warn=False, hide=False, echo=False, popen=False):
        ssh_command = self.get_connect_args() + [command]

        if echo:
            print(command)

        if popen:
            return subprocess.Popen(ssh_command)
        else:
            try:
                proc = subprocess.run(ssh_command, check=not warn, capture_output=True)
                returncode = proc.returncode
            except subprocess.CalledProcessError as e:
                returncode = e.returncode
                if returncode != 255:
                    raise

            if returncode == 255:
                raise ConnectionError(
                    f"Could not connect using command '{ssh_command}'"
                )

            stdout = proc.stdout.decode()
            stderr = proc.stderr.decode()

            if not hide:
                print(stdout)
                print(stderr)

            return Result(stdout, stderr, returncode)


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
        self.user = user
        self._conn = Connection(
            host=self.host,
            user=self.user,
            port=self.port,
            connect_timeout=60,
            connect_kwargs={
                "password": "",
                "banner_timeout": 60,
                "auth_timeout": 60,
                "look_for_keys": False,
                "allow_agent": False,
            },
        )
        self._service_name = None

    @property
    def host_string(self):
        return "%s:%s" % (self.host, self.port)

    def run(self, cmd, **kw) -> str:
        """Run given cmd in remote SSH host

        Argument:
        cmd - string with the command to execute remotely

        Recognized keyword arguments:
        hide - do not print stdout nor stderr, and do not fail on errors
        warn_only - do not fail on errors
        wait - timeout for how long to retry the execution
        """
        # TODO: Rework tests using warn_only and remove it
        # TODO: Revisit tests using hide and check if they expect errors
        if kw.get("warn_only") == True:
            del kw["warn_only"]
            kw["warn"] = True
        if kw.get("hide") == True:
            kw["warn"] = True
        return _run(self._conn, cmd, **kw).stdout

    def put(self, file, local_path=".", remote_path="."):
        """Copy local_path/file into remote_path over SSH connection

        Keyword arguments:
        file - local filename
        local_path - local dirpath
        remote_path - remote dirpath
        """

        _put(self, file, local_path, remote_path)

    def ssh_is_opened(self, wait=10 * 60):
        """Block until SSH connection is established on the device

        Keyword arguments:
        wait - Timeout (in seconds)
        """
        waited = -1
        t0 = int(time.time())
        raise_exception = None
        for _ in redo.retrier(max_sleeptime=wait, attempts=wait, sleeptime=1):
            try:
                self.run("true", hide=True, wait=wait)
                raise_exception = None
                break
            except Exception as e:
                raise_exception = e
            finally:
                waited = int(time.time()) - t0
        if raise_exception:
            logger.error("Can't open ssh after %d s of waiting and trying" % waited)
            raise (raise_exception)

    def yocto_id_installed_on_machine(self):
        cmd = "mender-update show-artifact"
        output = self.run(cmd, hide=True).strip()
        return output

    def get_active_partition(self):
        cmd = r"mount | awk '/on \/ / { print $1}'"
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
    def __init__(self, device, host_ip):
        self.host_ip = host_ip
        self.device = device
        self.server = None

    def __enter__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host_ip, 0))
        addr, port = self.server.getsockname()
        self.port = port

        local_name = "test.mender-reboot-detector.txt.%s" % self.device.host_string
        with open(local_name, "w") as fd:
            fd.write("%s:%d" % (self.host_ip, self.port))
        try:
            self.device.put(
                local_name, remote_path="/data/mender/test.mender-reboot-detector.txt"
            )
        finally:
            os.unlink(local_name)

        self.device.run("systemctl restart mender-reboot-detector")

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

            message = connection.recv(4096).decode().strip()
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

    def verify_reboot_performed(self, max_wait=10 * 60, number_of_reboots=1):
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

    Currently, run/put methods are serialized, but they could be migrated to a parallel execution
    ref https://docs.fabfile.org/en/latest/api/group.html
    However there is a real challenge in the underlying _run method to be able to handle GroupException
    """

    def __init__(self, host_string_list, user="root"):
        self._devices = []
        for host_string in host_string_list:
            self._devices.append(MenderDevice(host_string))

    def __len__(self):
        return len(self._devices)

    def __getitem__(self, idx):
        return self._devices[idx]

    def append(self, new_device: MenderDevice):
        """Append new_device to the group."""
        assert isinstance(new_device, MenderDevice)
        self._devices.append(new_device)

    def run(self, cmd, **kw) -> Dict:
        """Run command for all devices in group sequentially

        see MenderDevice.run
        """
        output_dict = dict()
        for dev in self._devices:
            output = dev.run(cmd, **kw)
            output_dict[dev.host_string] = output
        return output_dict

    def ssh_is_opened(self, wait=10 * 60):
        """Block until SSH connection is established for all devices in group sequentially

        see MenderDevice.ssh_is_opened
        """
        for dev in self._devices:
            dev.ssh_is_opened(wait)


def _ssh_prep_args(device):
    return _ssh_prep_args_impl(device, "ssh")


def _scp_prep_args(device):
    return _ssh_prep_args_impl(device, "scp")


def _ssh_prep_args_impl(device, tool):
    cmd = "%s -C -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" % tool

    host_parts = device.host_string.split(":")
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


def _put(device, file, local_path=".", remote_path="."):
    (scp, host, port) = _scp_prep_args(device)
    for i in range(3):
        try:
            subprocess.check_output(
                f"{scp} -O {port} {local_path}/{file} {device.user}@{host}:{remote_path}",
                shell=True,
            )
        except subprocess.CalledProcessError as e:
            # we tried three times, give up
            if i == 2:
                logger.info("CalledProcessError.output = %r", e.output)
                raise
            # wait two seconds before trying again
            time.sleep(2)
        else:
            break


# TODO: Revisit this arbitrary value.
_DEFAULT_WAIT_TIME = 10 * 60


def _run(conn, cmd, **kw):
    if kw.get("wait") is not None:
        wait = kw["wait"]
        del kw["wait"]
    else:
        wait = _DEFAULT_WAIT_TIME

    result = None
    start_time = time.time()
    sleeptime = 1
    while time.time() < start_time + wait:
        # Back off exponentially to save SSH handshakes in QEMU, which
        # are quite expensive.
        time.sleep(sleeptime)
        sleeptime *= 2

        try:
            result = conn.run(cmd, **kw)
            break
        except ConnectionError as e:
            logger.info(f"Got SSH exception while connecting to host {conn.host}: {e}")
            time.sleep(60)
            continue
        except OSError as e:
            # The OSError is happening while there is no QEMU instance initialized
            logger.info(
                "Got OSError exception while connecting to host %s: %s",
                conn.host,
                str(e),
            )
            if "Cannot assign requested address" not in str(e):
                raise e
            continue
        except Exception as e:
            logger.exception(
                f"Generic exception happened while connecting to host {conn.host}"
            )
            raise e
    else:
        raise RuntimeError(
            f"Could not successfully run command after {wait} seconds on host {conn.host}: {cmd}"
        )

    return result
