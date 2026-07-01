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
#

import json
import os.path
import tempfile
import time

from ..common_setup import standard_setup_one_client
from ..MenderAPI import devauth, logger


def set_long_poll_intervals(mender_device):
    with tempfile.NamedTemporaryFile(mode="w") as tf:
        output = mender_device.run("cat /etc/mender/mender.conf")
        config = json.loads(output)
        config["InventoryPollIntervalSeconds"] = 3600
        config["UpdatePollIntervalSeconds"] = 3600
        json.dump(config, tf)
        tf.flush()
        mender_device.put(
            os.path.basename(tf.name),
            local_path=os.path.dirname(tf.name),
            remote_path="/etc/mender/mender.conf",
        )
        output = mender_device.run("cat /etc/mender/mender.conf")
        logger.warning(output)


def get_opened_tcp_connections(mender_device, binary_name):
    # Count only ESTABLISHED (state 01 in /proc/net/tcp) connections to the
    # server's HTTPS port (:01BB == 443). A connection that mender has already
    # closed lingers briefly in TIME_WAIT (state 06) and other post-close states;
    # those are NOT a leaked/open socket, so counting them would make this test
    # race the kernel's normal connection teardown and fail spuriously.
    mender_device.run(f"pidof {binary_name}")
    output = mender_device.run(
        f"for pid in `pidof {binary_name}`;"
        + "do cat /proc/$pid/net/tcp;"
        + "done"
        + "| grep -E '[^:]+: [^ ]+ [^ ]+:01BB 01'"
        + "| wc -l"
    )
    return int(output)


def assert_no_open_tcp_connections(mender_device, binary_name, timeout=30):
    """Wait until binary_name has no ESTABLISHED connection to the server.

    The socket close happens asynchronously after the HTTP request finishes, so
    poll instead of asserting once after a fixed sleep (which races the close).
    """
    deadline = time.time() + timeout
    while True:
        count = get_opened_tcp_connections(mender_device, binary_name)
        if count == 0:
            return
        if time.time() >= deadline:
            assert count == 0, (
                f"{binary_name} still has {count} ESTABLISHED connection(s) "
                f"to the server after {timeout}s"
            )
        time.sleep(1)


class BaseTestTcpTeardown:
    def test_tcp_teardown(self, standard_setup_one_client):
        """Tests the closing of TCP sockets after HTTP requests on mender-auth and mender-update"""
        mender_device = standard_setup_one_client.device

        # Stop all services
        mender_device.run("systemctl stop mender-connect mender-authd mender-updated")

        # To verify mender-authd, trigger manually a token fetch
        mender_device.run("systemctl start mender-authd")
        time.sleep(5)
        mender_device.run("""dbus-send --print-reply --system \\
              --dest=io.mender.AuthenticationManager \\
              /io/mender/AuthenticationManager \\
              io.mender.Authentication1.FetchJwtToken""")
        # The fetch is done async; poll until the socket is torn down.
        assert_no_open_tcp_connections(mender_device, "mender-auth")

        # Accept the device and repeat the test. It should not make a difference
        devauth.accept_devices(1)
        mender_device.run("""dbus-send --print-reply --system \\
              --dest=io.mender.AuthenticationManager \\
              /io/mender/AuthenticationManager \\
              io.mender.Authentication1.FetchJwtToken""")
        assert_no_open_tcp_connections(mender_device, "mender-auth")

        # To test mender-update, set long intervals and manually trigger operations
        set_long_poll_intervals(mender_device)
        mender_device.run("systemctl start mender-updated")
        # let mender-updated come up before checking it is idle (long poll intervals)
        time.sleep(5)
        assert_no_open_tcp_connections(mender_device, "mender-update")
        assert_no_open_tcp_connections(mender_device, "mender-auth")

        mender_device.run("mender-update check-update")
        assert_no_open_tcp_connections(mender_device, "mender-update")
        assert_no_open_tcp_connections(mender_device, "mender-auth")

        mender_device.run("mender-update send-inventory")
        assert_no_open_tcp_connections(mender_device, "mender-update")
        assert_no_open_tcp_connections(mender_device, "mender-auth")


class TestTcpTeardownOpenSource(BaseTestTcpTeardown):
    pass


class TestTcpTeardownEnterprise(BaseTestTcpTeardown):
    pass
