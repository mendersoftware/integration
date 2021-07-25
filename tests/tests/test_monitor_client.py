# Copyright 2021 Northern.tech AS
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
import os
import os.path
import shutil
import tempfile
import time

from email.parser import Parser
from email.policy import default
from ..common_setup import monitor_commercial_setup_no_client

from ..MenderAPI import (
    authentication,
    get_container_manager,
    DeviceAuthV2,
    logger,
)

from testutils.infra.container_manager import factory
from testutils.infra.device import MenderDevice
from testutils.common import Tenant, User, update_tenant
from testutils.infra.cli import CliTenantadm

container_factory = factory.get_factory()
connect_service_name = "mender-connect"

# the smtpd saves messages in the following format:
# ---------- MESSAGE FOLLOWS ----------
# b'Subject: it is fine'
# b'From: me@me.pl'
# b'To: local@local.pl'
# b'X-Peer: 127.0.0.1'
# b''
# b'hej'
# b''
# b':)'
# b''
# b'local'
# ------------ END MESSAGE ------------
message_start = "---------- MESSAGE FOLLOWS ----------"
message_end = "------------ END MESSAGE ------------"
message_mail_options_prefix = "mail options:"


def parse_email(spool):
    # read spool line by line, eval(line).decode('utf-8') for each line in lines
    # between start and end of message
    # concat and create header object for each
    headers = []
    message_string = ""
    for line in spool.splitlines():
        if line.startswith(message_mail_options_prefix):
            continue
        if message_start == line:
            message_string = ""
            continue
        if message_end == line:
            headers.append(Parser(policy=default).parsestr(message_string))
            continue
        # extra safety, we are supposed to only eval b'string' lines
        if not line.startswith("b'"):
            continue
        message_string = message_string + eval(line).decode("utf-8") + "\n"
    return headers


def prepare_service_monitoring(mender_device, service_name):
    try:
        monitor_available_dir = "/etc/mender-monitor/monitor.d/available"
        monitor_enabled_dir = "/etc/mender-monitor/monitor.d/enabled"
        mender_device.run("mkdir -p '%s'" % monitor_available_dir)
        mender_device.run("mkdir -p '%s'" % monitor_enabled_dir)
        mender_device.run("systemctl restart %s" % service_name)
        tmpdir = tempfile.mkdtemp()
        service_check_file = os.path.join(tmpdir, "service_cron.sh")
        f = open(service_check_file, "w")
        f.write("SERVICE_NAME=%s\nSERVICE_TYPE=systemd\n" % service_name)
        f.close()
        mender_device.put(
            os.path.basename(service_check_file),
            local_path=os.path.dirname(service_check_file),
            remote_path=monitor_available_dir,
        )
        mender_device.run(
            "ln -s '%s/service_cron.sh' '%s/service_cron.sh'"
            % (monitor_available_dir, monitor_enabled_dir)
        )
    finally:
        shutil.rmtree(tmpdir)


class TestMonitorClientEnterprise:
    """Tests for the Monitor client"""

    def prepare_env(self, env, user_name):
        u = User("", user_name, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=env.name)
        tid = cli.create_org("os-tenant", u.name, u.pwd, plan="os")

        # at the moment we do not have a notion of a monitor add-on in the
        # backend, but this will be needed here, see MEN-4809
        # update_tenant(
        #  tid, addons=["monitor"], container_manager=get_container_manager(),
        # )

        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)

        auth = authentication.Authentication(
            name="os-tenant", username=u.name, password=u.pwd
        )
        auth.create_org = False
        auth.reset_auth_token()
        devauth_tenant = DeviceAuthV2(auth)

        env.new_tenant_client("configuration-test-container", tenant["tenant_token"])
        mender_device = MenderDevice(env.get_mender_clients()[0])
        mender_device.ssh_is_opened()

        devauth_tenant.accept_devices(1)

        devices = list(
            set(
                [
                    device["id"]
                    for device in devauth_tenant.get_devices_status("accepted")
                ]
            )
        )
        assert 1 == len(devices)

        devid = devices[0]
        authtoken = auth.get_auth_token()

        return devid, authtoken, auth, mender_device

    def test_monitorclient_alert_email(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "alert@mender.io"
        service_name = "crond"
        user_name = "bugs.bunny@acme.org"
        devid, authtoken, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        logger.info("test_monitorclient_alert_email: env ready.")

        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) > 0
        m = messages[0]
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "[CRITICAL] " + service_name + " on " + devid + " status: not-running"
        )
        logger.info("test_monitorclient_alert_email: got CRITICAL alert email.")

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        for m in messages:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             To: %s", m["To"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])

        assert len(messages) > 1
        m = messages[1]
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"] == "[OK] " + service_name + " on " + devid + " status: running"
        )
        logger.info("test_monitorclient_alert_email: got OK alert email.")
