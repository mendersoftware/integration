# Copyright 2023 Northern.tech AS
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

import json
import pytest
import time
import uuid

from flaky import flaky

from testutils.api import proto_shell, protomsg
from testutils.infra.cli import CliTenantadm
from testutils.infra.container_manager import factory
from testutils.infra.device import MenderDevice
from ..common_setup import (
    class_persistent_standard_setup_one_client_bootstrapped,
    standard_setup_one_client_bootstrapped,
    enterprise_no_client_class,
    enterprise_no_client,
)
from ..MenderAPI import (
    DeviceAuthV2,
    Authentication,
    DeviceConnect,
    get_container_manager,
    set_container_manager,
    logger,
)
from testutils.common import User, update_tenant
from .common_connect import wait_for_connect

container_factory = factory.get_factory()


class _TestRemoteTerminalBase:
    def test_regular_protocol_commands(self, docker_env_flaky_test):
        """
        Ticket: QA-504
        Reason: The test fails due to the fact that the websocket connection is broken,
                and the mender-connect can't recover from situation when shell could not
                be stopped, and the session is left as empty with non-existent process
                (see MEN-6137) while many other things timeout.
        """

        self.assert_env(docker_env_flaky_test)

        with docker_env_flaky_test.devconnect.get_websocket() as ws:
            # Start shell.
            receive_timeout_s = 16
            shell_ready = False
            for i in range(1, 8):
                try:
                    shell = proto_shell.ProtoShell(ws)
                    body = shell.startShell()
                    if shell.protomsg.props["status"] != protomsg.PROP_STATUS_NORMAL:
                        raise TypeError("status is not PROP_STATUS_NORMAL")
                    assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
                    if body != proto_shell.MSG_BODY_SHELL_STARTED:
                        raise TypeError("body is not MSG_BODY_SHELL_STARTED")
                    assert body == proto_shell.MSG_BODY_SHELL_STARTED

                    # Drain any initial output from the prompt. It should end in either "# "
                    # (root) or "$ " (user).
                    output = shell.recvOutput(receive_timeout_s)
                    if shell.protomsg.props["status"] != protomsg.PROP_STATUS_NORMAL:
                        raise TypeError("status is not PROP_STATUS_NORMAL")
                    assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
                    if not output[-2:].decode() in [
                        "# ",
                        "$ ",
                    ]:
                        raise TypeError(
                            "shell output " + output[-2:].decode() + " is not expected"
                        )
                    assert output[-2:].decode() in [
                        "# ",
                        "$ ",
                    ], "Could not detect shell prompt."
                    shell_ready = True
                    break
                except TypeError as e:
                    ws = docker_env_flaky_test.devconnect.get_websocket()
                    time.sleep(receive_timeout_s)
                    continue
                if shell_ready:
                    break
            if not shell_ready:
                raise RuntimeError("shell is not ready")

            # Starting the shell again should be a no-op. It should return that
            # it is already started, as long as the shell limit is 1. MEN-4240.
            body = shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_ERROR
            assert body == b"failed to start shell: shell is already running"

            # Make sure we do not get any new output, it should be the same shell as before.
            output = shell.recvOutput(receive_timeout_s)
            assert (
                output == b""
            ), "Unexpected output received when relauncing already launched shell."

            # Test if a simple command works.
            shell.sendInput("ls /\n".encode())
            output = shell.recvOutput(receive_timeout_s)
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            output = output.decode()
            assert "usr" in output
            assert "etc" in output

            # Try to stop shell.
            body = shell.stopShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert body is None

            # Repeat stopping and verify the error
            body = shell.stopShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_ERROR
            assert b"session not found" in body, body

            # Make sure we can not send anything to the shell.
            shell.sendInput("ls /\n".encode())
            output = shell.recvOutput(receive_timeout_s)
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_ERROR
            output = output.decode()
            assert "usr" not in output
            assert "etc" not in output
            assert "session not found" in output, output

            # Start it again.
            shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL

            # Drain any initial output from the prompt. It should end in either "# "
            # (root) or "$ " (user).
            output = shell.recvOutput(receive_timeout_s)
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert output[-2:].decode() in [
                "# ",
                "$ ",
            ], "Could not detect shell prompt."

    def test_dbus_reconnect(self, docker_env):
        self.assert_env(docker_env)

        with docker_env.devconnect.get_websocket():
            # Nothing to do, just connecting successfully is enough.
            pass

        # Test that mender-connect recovers if it initially has no DBus
        # connection. This is important because we don't have DBus activation
        # enabled in the systemd service file, so it's a race condition who gets
        # to the DBus service first.
        docker_env.device.run(
            f"systemctl --job-mode=ignore-dependencies stop mender-updated"
        )
        docker_env.device.run(
            "systemctl --job-mode=ignore-dependencies restart mender-connect"
        )

        time.sleep(10)

        # At this point, mender-connect will already have queried DBus.
        docker_env.device.run(
            f"systemctl --job-mode=ignore-dependencies start mender-updated"
        )

        with docker_env.devconnect.get_websocket():
            # Nothing to do, just connecting successfully is enough.
            pass

    def test_websocket_reconnect(self, docker_env):
        self.assert_env(docker_env)

        with docker_env.devconnect.get_websocket():
            # Nothing to do, just connecting successfully is enough.
            pass

        # Test that mender-connect recovers if it loses the connection to deviceconnect.
        docker_env.restart_service("mender-deviceconnect")

        time.sleep(10)

        with docker_env.devconnect.get_websocket():
            # Nothing to do, just connecting successfully is enough.
            pass

    def test_bogus_shell_message(self, docker_env):
        self.assert_env(docker_env)

        with docker_env.devconnect.get_websocket() as ws:
            prot = protomsg.ProtoMsg(proto_shell.PROTO_TYPE_SHELL)

            prot.clear()
            prot.setTyp("bogusmessage")
            msg = prot.encode(b"")
            ws.send(msg)

            msg = ws.recv()
            prot.decode(msg)
            assert prot.props["status"] == protomsg.PROP_STATUS_ERROR
            assert prot.protoType == proto_shell.PROTO_TYPE_SHELL
            assert prot.typ == "bogusmessage"

    def test_in_poor_network_environment(self, docker_env):
        self.assert_env(docker_env)

        receive_timeout_s = 16

        def is_shell_working(shell):
            # Test if a simple command works.
            shell.sendInput("ls /\n".encode())
            output = shell.recvOutput(receive_timeout_s)
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            output = output.decode()
            assert "usr" in output
            assert "etc" in output

        def detect_shell_prompt(shell):
            # Drain any initial output from the prompt. It should end in either "# "
            # (root) or "$ " (user).
            output = shell.recvOutput(receive_timeout_s)
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert output[-2:].decode() in [
                "# ",
                "$ ",
            ], "Could not detect shell prompt."

        with docker_env.devconnect.get_websocket() as ws:
            shell = proto_shell.ProtoShell(ws)
            body = shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert body == proto_shell.MSG_BODY_SHELL_STARTED

            detect_shell_prompt(shell)
            is_shell_working(shell)

        docker_env.device.run(
            "iptables -A OUTPUT -j DROP --destination docker.mender.io"
        )

        # Plenty of time for the session to mess up
        time.sleep(60)

        # Re-enable a good connection
        docker_env.device.run("iptables -D OUTPUT 1")
        time.sleep(30)

        # mender-connect should have "healed" now and be able to start a new shell
        with docker_env.devconnect.get_websocket() as ws:
            shell = proto_shell.ProtoShell(ws)
            body = shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert body == proto_shell.MSG_BODY_SHELL_STARTED

            detect_shell_prompt(shell)
            is_shell_working(shell)

    @flaky(max_runs=3)
    def test_session_recording(self, docker_env):
        self.assert_env(docker_env)

        def get_cmd(ws, timeout=1):
            pmsg = protomsg.ProtoMsg(proto_shell.PROTO_TYPE_SHELL)
            body = b""
            try:
                while True:
                    msg = ws.recv(timeout)
                    b = pmsg.decode(msg)
                    if pmsg.typ == proto_shell.MSG_TYPE_SHELL_COMMAND:
                        body += b
            except TimeoutError:
                return body

        session_id = ""
        session_bytes = b""
        with docker_env.devconnect.get_websocket() as ws:
            # Start shell.
            shell = proto_shell.ProtoShell(ws)
            body = shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert body == proto_shell.MSG_BODY_SHELL_STARTED

            assert shell.sid is not None
            session_id = shell.sid

            """ Record a series of commands """
            shell.sendInput("echo 'now you see me'\n".encode())
            session_bytes += get_cmd(ws)
            # Disable echo
            shell.sendInput("stty -echo\n".encode())
            shell.sendInput('echo "echo disabled $?"\n'.encode())
            for i in range(10):
                session_bytes += get_cmd(ws)
                if b"echo disabled 0" in session_bytes:
                    break
                time.sleep(1)
            shell.sendInput('echo "now you don\'t" > /dev/null\n'.encode())
            session_bytes += get_cmd(ws)
            shell.sendInput("# Invisible comment\n".encode())
            session_bytes += get_cmd(ws)
            # Turn echo back on
            shell.sendInput("stty echo\n".encode())
            shell.sendInput('echo "echo enabled $?"\n'.encode())
            for i in range(10):
                session_bytes += get_cmd(ws)
                if b"echo enabled 0" in session_bytes:
                    break
                time.sleep(1)
            session_bytes += get_cmd(ws)
            shell.sendInput("echo 'and now echo is back on'\n".encode())
            session_bytes += get_cmd(ws)

            body = shell.stopShell()
            assert (
                shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            ), f"Body is: {body}"
            assert body is None

        # Sleep for a second to make sure the session log propagate to the DB.
        time.sleep(1)

        playback_bytes = b""
        with docker_env.devconnect.get_playback_websocket(session_id, sleep_ms=0) as ws:
            playback_bytes = get_cmd(ws)

        assert playback_bytes == session_bytes

        assert b"now you see me" in playback_bytes
        assert b"echo 'now you see me'" in playback_bytes

        # Check that the commands after echo was disabled is not present in the log
        assert b"# Invisible comment" not in playback_bytes
        assert b'echo "now you don\'t" > /dev/null' not in playback_bytes

        # ... and after echo is enabled
        assert b"echo 'and now echo is back on'" in playback_bytes

    def assert_env(self, docker_env):
        """Check extra env vars  used by base test funcs - make sure they're set.
        Mostly important for custom setups.
        """
        assert (
            docker_env.device is not None
        ), "docker_env must have a designated 'device'"
        assert (
            docker_env.devconnect is not None
        ), "docker_env must have a set up 'devconnect' instance"
        proxy_connected_timeout_s = 15 * 60
        docker_env.device.run(
            """dbus-send --print-reply --system \\
              --dest=io.mender.AuthenticationManager \\
              /io/mender/AuthenticationManager \\
              io.mender.Authentication1.FetchJwtToken""",
            wait=proxy_connected_timeout_s,
        )
        output = docker_env.device.run(
            "dbus-send --system --dest=io.mender.AuthenticationManager --print-reply /io/mender/AuthenticationManager io.mender.Authentication1.GetJwtToken"
        )
        logger.info("assert_env: GetJWT: returns: '%s'" % (output))

        # MenderAPI is a (partially) global object, which does not play well with these tests that
        # combine class and function scoped fixtures. Set always the container manager so that each
        # test correctly access its own environment from MenderAPI code.
        set_container_manager(docker_env)


class _TestRemoteTerminalBaseBogusProtoMessage:
    def test_bogus_proto_message(self, docker_env):
        self.assert_env(docker_env)

        with docker_env.devconnect.get_websocket() as ws:
            prot = protomsg.ProtoMsg(12345)

            prot.clear()
            prot.setTyp(proto_shell.MSG_TYPE_SPAWN_SHELL)
            msg = prot.encode(b"")
            ws.send(msg)

            data = ws.recv()
            rsp = protomsg.ProtoMsg(0xFFFF)
            rsp.decode(data)
            assert rsp.typ == "error"
            body = rsp.body
            assert isinstance(body.get("err"), str) and len(body.get("err")) > 0


class TestRemoteTerminalOpenSource(
    _TestRemoteTerminalBase, _TestRemoteTerminalBaseBogusProtoMessage
):
    @pytest.fixture(scope="class")
    def docker_env(self, class_persistent_standard_setup_one_client_bootstrapped):
        env = class_persistent_standard_setup_one_client_bootstrapped
        auth = Authentication()
        env.devconnect = DeviceConnect(auth, DeviceAuthV2(auth))
        yield env

    @pytest.fixture(scope="function")
    def docker_env_flaky_test(self, standard_setup_one_client_bootstrapped):
        env = standard_setup_one_client_bootstrapped
        auth = Authentication()
        env.devconnect = DeviceConnect(auth, DeviceAuthV2(auth))
        yield env


def connected_device(env):
    uuidv4 = str(uuid.uuid4())
    tname = "test.mender.io-{}".format(uuidv4)
    email = "some.user+{}@example.com".format(uuidv4)
    u = User("", email, "whatsupdoc")
    cli = CliTenantadm(containers_namespace=env.name)
    tid = cli.create_org(tname, u.name, u.pwd, plan="enterprise")
    update_tenant(
        tid, addons=["troubleshoot"], container_manager=get_container_manager(),
    )
    tenant = cli.get_tenant(tid)
    tenant = json.loads(tenant)
    ttoken = tenant["tenant_token"]

    auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
    auth.create_org = False
    auth.reset_auth_token()
    devauth = DeviceAuthV2(auth)

    env.new_tenant_client("mender-client", ttoken)
    device = MenderDevice(env.get_mender_clients()[0])
    devauth.accept_devices(1)

    devices = devauth.get_devices_status("accepted")
    assert 1 == len(devices)

    wait_for_connect(auth, devices[0]["id"])

    devconn = DeviceConnect(auth, devauth)

    return device, devconn


class TestRemoteTerminalEnterprise(
    _TestRemoteTerminalBase, _TestRemoteTerminalBaseBogusProtoMessage
):
    @pytest.fixture(scope="class")
    def docker_env(self, enterprise_no_client_class):
        """Class-level customized docker_env (MT, 1 device, "enterprise" plan).

        The min. plan for most RT features is 'os', but we're also
        testing session logging - which is 'enterprise', so we need highest
        common denominator.
        """

        env = enterprise_no_client_class

        device, devconn = connected_device(env)

        env.device = device
        env.devconnect = devconn

        yield env

    @pytest.fixture(scope="function")
    def docker_env_flaky_test(self, enterprise_no_client):
        env = enterprise_no_client

        device, devconn = connected_device(env)

        env.device = device
        env.devconnect = devconn

        yield env
