# Copyright 2022 Northern.tech AS
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

from testutils.api import proto_shell, protomsg
from testutils.infra.cli import CliTenantadm
from testutils.infra.container_manager import factory
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra.device import MenderDevice
from ..common_setup import (
    class_persistent_standard_setup_one_client_bootstrapped,
    enterprise_no_client_class,
)
from ..MenderAPI import (
    devconnect,
    devauth,
    reset_mender_api,
    DeviceAuthV2,
    Authentication,
    DeviceConnect,
    get_container_manager,
)
from testutils.common import User, update_tenant
from .common_connect import wait_for_connect

container_factory = factory.get_factory()


class _TestRemoteTerminalBase:
    def test_regular_protocol_commands(self, docker_env):
        self.assert_env(docker_env)

        with docker_env.devconnect.get_websocket() as ws:
            # Start shell.
            shell = proto_shell.ProtoShell(ws)
            body = shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert body == proto_shell.MSG_BODY_SHELL_STARTED

            # Drain any initial output from the prompt. It should end in either "# "
            # (root) or "$ " (user).
            output = shell.recvOutput()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert output[-2:].decode() in [
                "# ",
                "$ ",
            ], "Could not detect shell prompt."

            # Starting the shell again should be a no-op. It should return that
            # it is already started, as long as the shell limit is 1. MEN-4240.
            body = shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_ERROR
            assert body == b"failed to start shell: shell is already running"

            # Make sure we do not get any new output, it should be the same shell as before.
            output = shell.recvOutput()
            assert (
                output == b""
            ), "Unexpected output received when relauncing already launched shell."

            # Test if a simple command works.
            shell.sendInput("ls /\n".encode())
            output = shell.recvOutput()
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
            output = shell.recvOutput()
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
            output = shell.recvOutput()
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
        client_service_name = docker_env.device.get_client_service_name()
        docker_env.device.run(
            f"systemctl --job-mode=ignore-dependencies stop {client_service_name}"
        )
        docker_env.device.run(
            "systemctl --job-mode=ignore-dependencies restart mender-connect"
        )

        time.sleep(10)

        # At this point, mender-connect will already have queried DBus.
        docker_env.device.run(
            f"systemctl --job-mode=ignore-dependencies start {client_service_name}"
        )

        with docker_env.devconnect.get_websocket():
            # Nothing to do, just connecting successfully is enough.
            pass

    @pytest.mark.skipif(
        isK8S(), reason="not testable in a staging or production environment"
    )
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
            # reset terminal first (QA-409)
            terminal_reset_sleep_s = 8
            shell.sendInput("echo;\n".encode())
            time.sleep(terminal_reset_sleep_s)
            shell.sendInput("reset;\n".encode())
            time.sleep(terminal_reset_sleep_s)
            shell.sendInput("stty -echo\n".encode())
            time.sleep(1)

            session_bytes += get_cmd(ws)
            shell.sendInput('echo "now you don\'t" > /dev/null\n'.encode())
            session_bytes += get_cmd(ws)
            shell.sendInput("# Invisible comment\n".encode())
            session_bytes += get_cmd(ws)
            # Turn echo back on
            time.sleep(1)
            shell.sendInput("stty echo\n".encode())
            time.sleep(1)
            session_bytes += get_cmd(ws)
            shell.sendInput("echo 'and now echo is back on'\n".encode())
            session_bytes += get_cmd(ws)

            body = shell.stopShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
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


class _TestRemoteTerminalBaseBogusProtoMessage:
    def test_bogus_proto_message(self, docker_env):
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


class TestRemoteTerminal(
    _TestRemoteTerminalBase, _TestRemoteTerminalBaseBogusProtoMessage
):
    @pytest.fixture(autouse=True, scope="class")
    def docker_env(self, class_persistent_standard_setup_one_client_bootstrapped):
        env = class_persistent_standard_setup_one_client_bootstrapped
        env.devconnect = devconnect
        yield env


class TestRemoteTerminal_1_0(_TestRemoteTerminalBase):
    """
    This set of tests uses mender-connect v1.0
    """

    @pytest.fixture(autouse=True, scope="class")
    def docker_env(self, request):
        env = container_factory.getMenderClient_2_5()
        request.addfinalizer(env.teardown)
        env.setup()

        env.populate_clients(replicas=1)

        clients = env.get_mender_clients()
        assert len(clients) == 1, "Failed to setup client"
        env.device = MenderDevice(clients[0])
        env.device.ssh_is_opened()

        reset_mender_api(env)
        devauth.accept_devices(1)

        env.devconnect = devconnect
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


class TestRemoteTerminalEnterprise_1_0(_TestRemoteTerminalBase):
    """
    This set of tests uses mender-connect v1.0
    """

    @pytest.fixture(autouse=True, scope="class")
    def docker_env(self, request):
        env = container_factory.getMenderClient_2_5(enterprise=True)
        request.addfinalizer(env.teardown)
        env.setup()

        reset_mender_api(env)
        device, devconn = connected_device(env)

        env.device = device
        env.devconnect = devconn

        yield env
