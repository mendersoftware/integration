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

import logging
import pytest
import time

from testutils.api import proto_shell
from testutils.api.proto_shell import WRONG_BEHAVIOR
from ..common_setup import class_persistent_standard_setup_one_client_bootstrapped
from ..MenderAPI import devconnect

if WRONG_BEHAVIOR:
    logger = logging.getLogger("websockets")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())


class TestMenderShell:
    def test_regular_protocol_commands(
        self, class_persistent_standard_setup_one_client_bootstrapped
    ):
        device = class_persistent_standard_setup_one_client_bootstrapped.device

        if WRONG_BEHAVIOR:
            # MEN-4273.
            device.run(
                """sed -i -e '2i"SkipVerify": true,' /etc/mender/mender-shell.conf"""
            )
            device.run("systemctl restart mender-shell")

        with devconnect.get_websocket() as ws:
            # Start shell.
            shell = proto_shell.ProtoShell(ws)
            body = shell.startShell()
            assert body == b"Shell started"

            # Drain any initial output from the prompt. It should end in either "# "
            # (root) or "$ " (user).
            output = shell.recvOutput()
            assert output[-2:].decode() in [
                "# ",
                "$ ",
            ], "Could not detect shell prompt."

            # Starting the shell again should be a no-op. It should return that
            # it is already started, as long as the shell limit is 1. MEN-4240.
            body = shell.startShell()
            assert body == b"failed to start shell: shell is already running"

            # Make sure we do not get any new output, it should be the same shell as before.
            output = shell.recvOutput()
            assert output == b"", "Unexpected output received when relauncing already launched shell."

            # Test if a simple command works.
            shell.sendInput("ls /\n".encode())
            output = shell.recvOutput()
            output = output.decode()
            assert "usr" in output
            assert "etc" in output

            # Try to stop shell.
            body = shell.stopShell()
            assert body is None

            # Repeat stopping should be no-op.
            body = shell.stopShell()
            assert body is None

            # Make sure we can not send anything to the shell.
            shell.sendInput("ls /\n".encode())
            output = shell.recvOutput()
            output = output.decode()
            assert "usr" not in output
            assert "etc" not in output
            assert False, "TODO: Check for error here."

            # Start it again.
            shell.startShell()

            if not WRONG_BEHAVIOR:
                # Drain any initial output from the prompt. It should end in either "# "
                # (root) or "$ " (user).
                # MEN-4240 or MEN-4141, possibly a combination.
                output = shell.recvOutput()
                assert output[-2:].decode() in [
                    "# ",
                    "$ ",
                ], "Could not detect shell prompt."

    def test_dbus_reconnect(
        self, class_persistent_standard_setup_one_client_bootstrapped
    ):
        device = class_persistent_standard_setup_one_client_bootstrapped.device

        if WRONG_BEHAVIOR:
            # MEN-4273.
            device.run(
                """sed -i -e '2i"SkipVerify": true,' /etc/mender/mender-shell.conf"""
            )
            device.run("systemctl restart mender-shell")

        with devconnect.get_websocket() as ws:
            # Nothing to do, just connecting successfully is enough.
            pass

        # Test that mender-shell recovers if it initially has no DBus
        # connection. This is important because we don't have DBus activation
        # enabled in the systemd service file, so it's a race condition who gets
        # to the DBus service first.
        device.run("systemctl --job-mode=ignore-dependencies stop mender-client")
        device.run("systemctl --job-mode=ignore-dependencies restart mender-shell")

        time.sleep(10)

        # At this point, mender-shell will already have queried DBus.
        device.run("systemctl --job-mode=ignore-dependencies start mender-client")

        with devconnect.get_websocket() as ws:
            # Nothing to do, just connecting successfully is enough.
            pass

    def test_websocket_reconnect(
        self, class_persistent_standard_setup_one_client_bootstrapped
    ):
        device = class_persistent_standard_setup_one_client_bootstrapped.device

        if WRONG_BEHAVIOR:
            # MEN-4273.
            device.run(
                """sed -i -e '2i"SkipVerify": true,' /etc/mender/mender-shell.conf"""
            )
            device.run("systemctl restart mender-shell")

        with devconnect.get_websocket() as ws:
            # Nothing to do, just connecting successfully is enough.
            pass

        # Test that mender-shell recovers if it loses the connection to deviceconnect.
        class_persistent_standard_setup_one_client_bootstrapped.restart_service(
            "mender-deviceconnect"
        )

        time.sleep(10)

        with devconnect.get_websocket() as ws:
            # Nothing to do, just connecting successfully is enough.
            pass

    def test_wrong_behavior_fixed(self):
        assert (
            False
        ), "This is the failure you SHOULD reach if everything else is passing. Once all occurrences of WRONG_BEHAVIOR have been removed, this test can be removed as well."
