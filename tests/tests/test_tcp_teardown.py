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
    # First probe that a process for binary_name exists
    mender_device.run(f"pidof {binary_name}")
    output = mender_device.run(
        f"for pid in `pidof {binary_name}`;"
        + "do cat /proc/$pid/net/tcp;"
        + "done"
        + "| grep -E '[^:]+: [^ ]+ [^ ]+:01BB'"
        + "| wc -l"
    )
    return int(output)


class BaseTestTcpTeardown:
    def test_tcp_teardown(self, standard_setup_one_client):
        """Tests the closing of TCP sockets after HTTP requests on mender-auth and mender-update"""
        mender_device = standard_setup_one_client.device

        # Stop all services
        mender_device.run("systemctl stop mender-connect mender-authd mender-updated")

        # To verify mender-authd, trigger manually a token fetch
        mender_device.run("systemctl start mender-authd")
        time.sleep(5)
        mender_device.run(
            """dbus-send --print-reply --system \\
              --dest=io.mender.AuthenticationManager \\
              /io/mender/AuthenticationManager \\
              io.mender.Authentication1.FetchJwtToken"""
        )
        # The fetch is done async, give it some time to finish
        time.sleep(1)
        assert get_opened_tcp_connections(mender_device, "mender-auth") == 0

        # Accept the device and repeat the test. It should not make a difference
        devauth.accept_devices(1)
        mender_device.run(
            """dbus-send --print-reply --system \\
              --dest=io.mender.AuthenticationManager \\
              /io/mender/AuthenticationManager \\
              io.mender.Authentication1.FetchJwtToken"""
        )
        time.sleep(5)
        assert get_opened_tcp_connections(mender_device, "mender-auth") == 0

        # To test mender-update, set long intervals and manually trigger operations
        set_long_poll_intervals(mender_device)
        mender_device.run("systemctl start mender-updated")
        time.sleep(5)
        assert get_opened_tcp_connections(mender_device, "mender-update") == 0
        assert get_opened_tcp_connections(mender_device, "mender-auth") == 0

        mender_device.run("mender-update check-update")
        time.sleep(5)
        assert get_opened_tcp_connections(mender_device, "mender-update") == 0
        assert get_opened_tcp_connections(mender_device, "mender-auth") == 0

        mender_device.run("mender-update send-inventory")
        time.sleep(5)
        assert get_opened_tcp_connections(mender_device, "mender-update") == 0
        assert get_opened_tcp_connections(mender_device, "mender-auth") == 0


class TestTcpTeardownOpenSource(BaseTestTcpTeardown):
    pass


class TestTcpTeardownEnterprise(BaseTestTcpTeardown):
    pass
