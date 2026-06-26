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
from redo import retriable
from websockets.exceptions import WebSocketException

from testutils.api import proto_shell, protomsg
from testutils.infra.cli import CliTenantadm
from testutils.infra.container_manager import factory
from testutils.infra.device import MenderDevice
from ..common_setup import (
    standard_setup_one_docker_client_bootstrapped,
    enterprise_one_docker_client_bootstrapped,
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
    @flaky(max_runs=3)
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
            shell = proto_shell.ProtoShell(ws)
            body = shell.startShell()
            assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
            assert body == proto_shell.MSG_BODY_SHELL_STARTED

            # Drain any initial output from the prompt. It should end in either "# "
            # (root) or "$ " (user).
            output = shell.recvOutput(receive_timeout_s)
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

    def test_websocket_reconnect(self, docker_env):
        self.assert_env(docker_env)

        with docker_env.devconnect.get_websocket():
            # Nothing to do, just connecting successfully is enough.
            pass

        # Test that mender-connect recovers if it loses the connection to deviceconnect.
        docker_env.restart_service("mender-deviceconnect")

        # mender-connect needs time to re-establish its session after
        # deviceconnect restarts; until it does, the mgmt /connect endpoint
        # returns HTTP 404 ("device disconnected"). Poll instead of a fixed
        # sleep that races the reconnect. (QA-1527)
        @retriable(
            attempts=24,
            sleeptime=5,
            sleepscale=1,
            jitter=0,
            retry_exceptions=(WebSocketException,),
        )
        def assert_websocket_connects():
            with docker_env.devconnect.get_websocket():
                # Connecting successfully is enough.
                pass

        assert_websocket_connects()

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

    @flaky(max_runs=3)
    @pytest.mark.timeout(1200)
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

        # Poll the full open-and-start-shell sequence until it succeeds. After a
        # network outage the device reconnects to deviceconnect only after
        # connection backoff and the session can flap, so neither a fixed sleep
        # nor polling get_websocket() (which only checks the management side)
        # is reliable:
        #   - the mgmt /connect endpoint returns HTTP 404 ("device
        #     disconnected") until the device side is back, and
        #   - a just-reconnected session may not answer startShell yet
        #     (recv times out).
        # Retrying the whole sequence is the only signal that proves a working
        # shell. 48 * 5s = 240s covers the worst-case recovery after the 128s
        # drop below; retriable re-raises the last error if it never recovers.
        # AssertionErrors are not retried, so a genuine protocol failure still
        # fails fast. (QA-1527)
        @retriable(
            attempts=48,
            sleeptime=5,
            sleepscale=1,
            jitter=0,
            retry_exceptions=(WebSocketException, TimeoutError),
        )
        def assert_working_shell():
            with docker_env.devconnect.get_websocket() as ws:
                shell = proto_shell.ProtoShell(ws)
                body = shell.startShell()
                if (
                    shell.protomsg.props["status"] != protomsg.PROP_STATUS_NORMAL
                    and body
                    and b"already running" in body
                ):
                    # A shell started by a previous attempt that flapped mid-use
                    # may not be reaped yet (the shell limit is 1 per device).
                    # Treat it as not-ready and let the retry wait for the device
                    # to release it instead of failing on the assert below.
                    raise TimeoutError("shell from a previous attempt is still running")
                assert shell.protomsg.props["status"] == protomsg.PROP_STATUS_NORMAL
                assert body == proto_shell.MSG_BODY_SHELL_STARTED

                detect_shell_prompt(shell)
                is_shell_working(shell)

        assert_working_shell()

        docker_env.device.run("apt-get update")
        docker_env.device.run("apt-get install -y iptables")
        docker_env.device.run(
            "iptables -A OUTPUT -j DROP --destination docker.mender.io"
        )

        # Plenty of time for the session to mess up
        # see also QA-1591: the DROP will not cause ICMP response so we rely on the
        # TCP RTO which means sometimes we need additional time to sleep.
        # this was exposed by the move to docker client in those tests, as the
        # network stack acts differently
        time.sleep(128)

        # Re-enable a good connection
        docker_env.device.run("iptables -D OUTPUT 1")

        # mender-connect's reconnect backoff escalates per-attempt and caps at
        # 30 minutes (see connectionmanager/exponentialbackoff.go in
        # mender-connect); after a 128s outage the backoff timer can leave the
        # next reconnect attempt minutes away, which is not testable in a CI
        # window. Restart mender-connect so the fresh process starts at
        # attempts=0 and reconnects on its first cycle. The entrypoint's
        # supervise loop respawns it; this mirrors the canonical pattern used
        # by test_filetransfer.update_limits(). (QA-1527, QA-1591)
        docker_env.device.run("kill -TERM `pidof mender-connect` 2>/dev/null || true")

        # Poll until a working shell can be opened end-to-end.
        assert_working_shell()

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
    @pytest.fixture(scope="function")
    def docker_env(self, standard_setup_one_docker_client_bootstrapped):
        env = standard_setup_one_docker_client_bootstrapped
        auth = Authentication()
        env.devconnect = DeviceConnect(auth, DeviceAuthV2(auth))
        yield env

    @pytest.fixture(scope="function")
    def docker_env_flaky_test(
        self, request, standard_setup_one_docker_client_bootstrapped
    ):
        env = standard_setup_one_docker_client_bootstrapped
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
        tid,
        addons=["troubleshoot"],
        container_manager=get_container_manager(),
    )
    tenant = cli.get_tenant(tid)
    tenant = json.loads(tenant)
    ttoken = tenant["tenant_token"]

    auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
    auth.create_org = False
    auth.reset_auth_token()
    devauth = DeviceAuthV2(auth)

    env.new_tenant_docker_client("mender-client", ttoken)
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
    @pytest.fixture(scope="function")
    def docker_env(self, enterprise_one_docker_client_bootstrapped):
        """Class-level customized docker_env (MT, 1 device, "enterprise" plan).

        The min. plan for most RT features is 'os', but we're also
        testing session logging - which is 'enterprise', so we need highest
        common denominator.
        """

        env = enterprise_one_docker_client_bootstrapped

        device, devconn = connected_device(env)

        env.device = device
        env.devconnect = devconn

        yield env

    @pytest.fixture(scope="function")
    def docker_env_flaky_test(self, enterprise_one_docker_client_bootstrapped):
        env = enterprise_one_docker_client_bootstrapped

        device, devconn = connected_device(env)

        env.device = device
        env.devconnect = devconn

        yield env
