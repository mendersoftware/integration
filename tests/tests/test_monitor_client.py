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
    DeviceMonitor,
    Inventory,
    logger,
)

from testutils.api import useradm
from testutils.api.client import ApiClient
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


def prepare_service_monitoring(mender_device, service_name, use_ctl=False):
    if use_ctl:
        mender_device.run(
            'mender-monitorctl create service "%s" systemd' % (service_name)
        )
        mender_device.run('mender-monitorctl enable service "%s"' % (service_name))
    else:
        try:
            monitor_available_dir = "/etc/mender-monitor/monitor.d/available"
            monitor_enabled_dir = "/etc/mender-monitor/monitor.d/enabled"
            mender_device.run("mkdir -p '%s'" % monitor_available_dir)
            mender_device.run("mkdir -p '%s'" % monitor_enabled_dir)
            mender_device.run("systemctl restart %s" % service_name)
            tmpdir = tempfile.mkdtemp()
            service_check_file = os.path.join(tmpdir, "service_" + service_name + ".sh")
            f = open(service_check_file, "w")
            f.write("SERVICE_NAME=%s\nSERVICE_TYPE=systemd\n" % service_name)
            f.close()
            mender_device.put(
                os.path.basename(service_check_file),
                local_path=os.path.dirname(service_check_file),
                remote_path=monitor_available_dir,
            )
            mender_device.run(
                "ln -s '%s/service_%s.sh' '%s/service_%s.sh'"
                % (
                    monitor_available_dir,
                    service_name,
                    monitor_enabled_dir,
                    service_name,
                )
            )
        finally:
            shutil.rmtree(tmpdir)


def prepare_log_monitoring(
    mender_device,
    service_name,
    log_file,
    log_pattern,
    log_pattern_expiration=None,
    update_check_file_only=False,
    use_ctl=False,
):
    if use_ctl:
        # create log mender-client "State transition: .*" "@journalctl -u mender-client -f"
        mender_device.run(
            'mender-monitorctl create log "%s" "%s" "%s"'
            % (service_name, log_pattern, log_file)
        )
        mender_device.run('mender-monitorctl enable log "%s"' % (service_name))
    else:
        try:
            monitor_available_dir = "/etc/mender-monitor/monitor.d/available"
            monitor_enabled_dir = "/etc/mender-monitor/monitor.d/enabled"
            if not update_check_file_only:
                mender_device.run("mkdir -p '%s'" % monitor_available_dir)
                mender_device.run("mkdir -p '%s'" % monitor_enabled_dir)
            tmpdir = tempfile.mkdtemp()
            service_check_file = os.path.join(tmpdir, "log_" + service_name + ".sh")
            f = open(service_check_file, "w")
            f.write(
                'SERVICE_NAME="%s"\nLOG_FILE="%s"\nLOG_PATTERN="%s"\n'
                % (service_name, log_file, log_pattern)
            )
            if log_pattern_expiration:
                f.write("LOG_PATTERN_EXPIRATION=%d\n" % log_pattern_expiration)
            f.close()
            mender_device.put(
                os.path.basename(service_check_file),
                local_path=os.path.dirname(service_check_file),
                remote_path=monitor_available_dir,
            )
            if not update_check_file_only:
                mender_device.run(
                    "ln -s '%s/log_%s.sh' '%s/log_%s.sh'"
                    % (
                        monitor_available_dir,
                        service_name,
                        monitor_enabled_dir,
                        service_name,
                    )
                )
        finally:
            shutil.rmtree(tmpdir)


def prepare_dbus_monitoring(
    mender_device,
    dbus_name,
    log_pattern=None,
    dbus_pattern=None,
    alert_expiration=None,
):
    try:
        monitor_available_dir = "/etc/mender-monitor/monitor.d/available"
        monitor_enabled_dir = "/etc/mender-monitor/monitor.d/enabled"
        mender_device.run("mkdir -p '%s'" % monitor_available_dir)
        mender_device.run("mkdir -p '%s'" % monitor_enabled_dir)
        tmpdir = tempfile.mkdtemp()
        dbus_check_file = os.path.join(tmpdir, "dbus_%s.sh" % dbus_name)
        f = open(dbus_check_file, "w")
        f.write("DBUS_NAME=%s\n" % dbus_name)
        if log_pattern:
            f.write("DBUS_PATTERN=%s\n" % log_pattern)
        if dbus_pattern:
            f.write("DBUS_WATCH_PATTERN=%s\n" % dbus_pattern)
        if alert_expiration:
            f.write("DBUS_ALERT_EXPIRATION=%s\n" % alert_expiration)
        f.close()
        mender_device.put(
            os.path.basename(dbus_check_file),
            local_path=os.path.dirname(dbus_check_file),
            remote_path=monitor_available_dir,
        )
        mender_device.run(
            "ln -s '%s/dbus_test.sh' '%s/dbus_test.sh'"
            % (monitor_available_dir, monitor_enabled_dir)
        )
    finally:
        shutil.rmtree(tmpdir)


class TestMonitorClientEnterprise:
    """Tests for the Monitor client"""

    def prepare_env(self, env, user_name):
        u = User("", user_name, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=env.name)
        tid = cli.create_org("monitor-tenant", u.name, u.pwd, plan="enterprise")

        # at the moment we do not have a notion of a monitor add-on in the
        # backend, but this will be needed here, see MEN-4809
        # update_tenant(
        #  tid, addons=["monitor"], container_manager=get_container_manager(),
        # )

        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)

        auth = authentication.Authentication(
            name="monitor-tenant", username=u.name, password=u.pwd
        )
        auth.create_org = False
        auth.reset_auth_token()
        devauth_tenant = DeviceAuthV2(auth)

        env.new_tenant_client("configuration-test-container", tenant["tenant_token"])
        env.device = mender_device = MenderDevice(env.get_mender_clients()[0])
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

    def get_alerts_and_alert_count_for_device(self, inventory, devid):
        r = inventory.get_device(devid)
        assert r.status_code == 200
        inventory_data = r.json()
        alert_count = alerts = None
        for inventory_item in inventory_data["attributes"]:
            if (
                inventory_item["scope"] == "monitor"
                and inventory_item["name"] == "alert_count"
            ):
                alert_count = inventory_item["value"]
            elif (
                inventory_item["scope"] == "monitor"
                and inventory_item["name"] == "alerts"
            ):
                alerts = inventory_item["value"]
        return alerts, alert_count

    def test_monitorclient_alert_email(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        service_name = "crond"
        user_name = "bugs.bunny@acme.org"
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)
        logger.info("test_monitorclient_alert_email: env ready.")

        logger.info(
            "test_monitorclient_alert_email: email alert on systemd service not running scenario."
        )
        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) > 0
        m = messages[0]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
        )
        assert not "${workflow.input." in mail
        logger.info("test_monitorclient_alert_email: got CRITICAL alert email.")

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (False, 0) == (alerts, alert_count)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        for m in messages:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             Bcc: %s", m["Bcc"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])

        messages_count = len(messages)
        assert messages_count > 1
        m = messages[1]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_monitorclient_alert_email: got OK alert email.")

        logger.info(
            "test_monitorclient_alert_email: email alert on log file containing a pattern scenario."
        )
        log_file = "/tmp/mylog.log"
        log_pattern = "session opened for user [a-z]*"

        service_name = "mylog"
        prepare_log_monitoring(
            mender_device, service_name, log_file, log_pattern,
        )
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("echo 'some line 1' >> " + log_file)
        mender_device.run("echo 'some line 2' >> " + log_file)
        time.sleep(wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)
        assert messages_count == len(messages)

        mender_device.run(
            "echo -ne 'a new session opened for user root now\nsome line 3\n' >> "
            + log_file
        )

        time.sleep(wait_for_alert_interval_s)
        mender_device.run("echo 'some line 4' >> " + log_file)
        mender_device.run("echo 'some line 5' >> " + log_file)

        time.sleep(2 * wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        m = messages[-1]
        logger.debug("got message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             Bcc: %s", m["Bcc"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"].startswith(
            "CRITICAL: Monitor Alert for Log file contains "
            + log_pattern
            + " on "
            + devid
        )

        pattern_expiration_seconds = 32
        logger.info(
            "test_monitorclient_alert_email: CRITICAL received; setting pattern expiration time=%ds and waiting.",
            pattern_expiration_seconds,
        )
        prepare_log_monitoring(
            mender_device,
            service_name,
            log_file,
            log_pattern,
            log_pattern_expiration=pattern_expiration_seconds,
            update_check_file_only=True,
        )
        time.sleep(2 * wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        m = messages[-1]
        logger.debug("got message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             Bcc: %s", m["Bcc"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"] == (
            "OK: Monitor Alert for Log file contains " + log_pattern + " on " + devid
        )
        logger.info(
            "test_monitorclient_alert_email: got OK alert email after log pattern expiration."
        )
        device_monitor = DeviceMonitor(auth)
        alerts = device_monitor.get_alerts(devid)
        assert len(alerts) > 1
        assert "subject" in alerts[1]
        assert "details" in alerts[1]["subject"]
        assert "line_matching" in alerts[1]["subject"]["details"]
        assert "data" in alerts[1]["subject"]["details"]["line_matching"]
        assert (
            "a new session opened for user root now"
            == alerts[1]["subject"]["details"]["line_matching"]["data"]
        )
        assert "subject" in alerts[1]
        assert "details" in alerts[1]["subject"]
        assert "lines_before" in alerts[1]["subject"]["details"]
        assert len(alerts[1]["subject"]["details"]["lines_before"]) == 2
        assert len(alerts[1]["subject"]["details"]["lines_after"]) == 1
        assert "data" in alerts[1]["subject"]["details"]["lines_before"][0]
        assert "data" in alerts[1]["subject"]["details"]["lines_before"][1]
        assert (
            "some line 1" == alerts[1]["subject"]["details"]["lines_before"][0]["data"]
        )
        assert (
            "some line 2" == alerts[1]["subject"]["details"]["lines_before"][1]["data"]
        )
        assert "data" in alerts[1]["subject"]["details"]["lines_after"][0]
        assert (
            "some line 3" == alerts[1]["subject"]["details"]["lines_after"][0]["data"]
        )
        logger.debug(
            "test_monitorclient_alert_email: got %s alerts" % json.dumps(alerts)
        )
        logger.debug(
            "test_monitorclient_alert_email: got line -B1: '%s' from alerts"
            % alerts[1]["subject"]["details"]["lines_before"][0]["data"]
        )
        logger.debug(
            "test_monitorclient_alert_email: got line -B2: '%s' from alerts"
            % alerts[1]["subject"]["details"]["lines_before"][1]["data"]
        )
        logger.debug(
            "test_monitorclient_alert_email: got line -A1: '%s' from alerts"
            % alerts[1]["subject"]["details"]["lines_after"][0]["data"]
        )

        logger.info(
            "test_monitorclient_alert_email: email alert a pattern found in the journalctl output scenario."
        )
        service_name = "mender-client"
        prepare_log_monitoring(
            mender_device,
            service_name,
            "@journalctl -u " + service_name,
            "State transition: .*",
        )
        mender_device.run("systemctl restart mender-monitor")
        time.sleep(wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        m = messages[-1]
        logger.debug("got message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             Bcc: %s", m["Bcc"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"].startswith(
            "CRITICAL: Monitor Alert for Log file contains State transition:"
        )
        assert not "${workflow.input" in mail

        logger.info(
            "test_monitorclient_alert_email: email alert on streaming logs pattern expiration scenario."
        )
        prepare_log_monitoring(
            mender_device,
            service_name,
            "@tail -f " + log_file,
            log_pattern,
            log_pattern_expiration=pattern_expiration_seconds,
            update_check_file_only=True,
        )
        mender_device.run("systemctl restart mender-monitor")
        mender_device.run(
            "echo -ne 'another line\na new session opened for user root now\nsome line 3\n' >> "
            + log_file
        )

        logger.info(
            "test_monitorclient_alert_email: '@tail -f logfile' scenario, waiting %ds for pattern to expire."
            % (2 * pattern_expiration_seconds)
        )
        time.sleep(2 * pattern_expiration_seconds)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        m = messages[-1]
        logger.debug("got message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             Bcc: %s", m["Bcc"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"] == (
            "OK: Monitor Alert for Log file contains " + log_pattern + " on " + devid
        )
        logger.info(
            "test_monitorclient_alert_email: got OK alert email after log pattern expiration in case of streaming log file."
        )

    def test_monitorclient_flapping(self, monitor_commercial_setup_no_client):
        """Tests the monitor client flapping support"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 120
        service_name = "crond"
        user_name = "bugs.bunny@monitoring.acme.org"
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        logger.info("test_monitorclient_flapping: env ready.")

        prepare_service_monitoring(mender_device, service_name)

        max_start_stop_iterations = 32
        not_running_time = 2.2
        logger.info(
            "test_monitorclient_flapping: running stop/start for %s, %d interations, sleep in-between: %.1fs"
            % (service_name, max_start_stop_iterations, not_running_time)
        )
        while max_start_stop_iterations > 0:
            max_start_stop_iterations = max_start_stop_iterations - 1
            mender_device.run("systemctl stop %s" % service_name)
            time.sleep(not_running_time)
            mender_device.run("systemctl start %s" % service_name)
            time.sleep(not_running_time)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        assert len(messages) > 1
        messages_count_flapping = len(messages)
        for m in messages:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             Bcc: %s", m["Bcc"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])
        m = messages[-1]
        logger.debug("(1) last message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             Bcc: %s", m["Bcc"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for Service "
            + service_name
            + " going up and down on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_monitorclient_flapping: got CRITICAL alert email.")

        logger.info(
            "test_monitorclient_flapping: waiting for %s seconds"
            % wait_for_alert_interval_s
        )
        time.sleep(wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        m = messages[-1]
        logger.debug("(2) last message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             Bcc: %s", m["Bcc"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert messages_count_flapping + 1 == len(messages)
        assert (
            m["Subject"]
            == "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_monitorclient_flapping: got OK alert email.")

    def test_monitorclient_alert_email_rbac(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting respecting RBAC"""
        # first let's get the OK and CRITICAL email alerts {{{
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        service_name = "crond"
        user_name = "bugs.bunny@acme.org"
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)
        logger.info("test_monitorclient_alert_email_rbac: env ready.")

        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)
        assert len(messages) > 0

        m = messages[0]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_monitorclient_alert_email_rbac: got CRITICAL alert email.")

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (False, 0) == (alerts, alert_count)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        for m in messages:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             Bcc: %s", m["Bcc"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])

        messages_count = len(messages)
        assert messages_count > 1
        m = messages[1]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_monitorclient_alert_email_rbac: got OK alert email.")
        # }}} we got the CRITICAL and OK emails

        # let's add a role, that will allow user to view only devices of given group {{{
        uadm = ApiClient(
            host=get_container_manager().get_mender_gateway(),
            base_url=useradm.URL_MGMT,
        )

        role = {
            "name": "deviceaccess",
            "permissions": [
                {
                    "action": "VIEW_DEVICE",
                    "object": {"type": "DEVICE_GROUP", "value": "fullTestDevices"},
                }
            ],
        }
        res = uadm.call(
            "POST", useradm.URL_ROLES, headers=auth.get_auth_token(), body=role
        )
        assert res.status_code == 201
        logger.info(
            "test_monitorclient_alert_email_rbac: added role: restrict access to a group."
        )
        # }}} role added

        # let's set the role for the user {{{
        res = uadm.call("GET", useradm.URL_USERS, headers=auth.get_auth_token())
        assert res.status_code == 200
        logger.info(
            "test_monitorclient_alert_email_rbac: "
            "get users: http rc: %d; response body: '%s'; "
            % (res.status_code, res.json())
        )
        users = res.json()
        res = uadm.call(
            "PUT",
            useradm.URL_USERS_ID.format(id=users[0]["id"]),
            headers=auth.get_auth_token(),
            body={"roles": ["deviceaccess"]},
        )
        assert res.status_code == 204
        logger.info("test_monitorclient_alert_email_rbac: role assigned to user.")
        # }}} user has access only to fullTestDevices group

        # let's stop the service by name=service_name
        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)
        assert len(messages) == messages_count
        # we did not receive any email -- user has no access to the device
        logger.info(
            "test_monitorclient_alert_email_rbac: did not receive CRITICAL email alert."
        )

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)
        assert len(messages) == messages_count
        # we did not receive any email -- user has no access to the device
        logger.info(
            "test_monitorclient_alert_email_rbac: did not receive OK email alert."
        )

    def test_monitorclient_alert_store(self, monitor_commercial_setup_no_client):
        """Tests the monitor client alert local store"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        service_name = "rpcbind"
        user_name = "bugs.bunny@acme.org"
        devid, authtoken, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        logger.info("test_monitorclient_alert_store: env ready.")

        logger.info(
            "test_monitorclient_alert_store: store alerts when offline scenario."
        )

        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        logger.info(
            "test_monitorclient_alert_store disabling access to docker.mender.io (point to localhost in /etc/hosts)"
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 docker.mender.io' /etc/hosts")
        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(wait_for_alert_interval_s)
        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) == 0
        logger.info("test_monitorclient_alert_store: got no alerts, device is offline.")

        logger.info(
            "test_monitorclient_alert_store re-enabling access to docker.mender.io (restoring /etc/hosts)"
        )
        mender_device.run("mv /etc/hosts.backup /etc/hosts")
        logger.info("test_monitorclient_alert_store waiting for alerts to come.")
        time.sleep(8 * wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        for m in messages:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             Bcc: %s", m["Bcc"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])

        assert len(messages) > 1
        m = messages[0]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_monitorclient_alert_store: got CRITICAL alert email.")

        m = messages[1]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_monitorclient_alert_store: got OK alert email.")

    def test_dbus_subsystem(self, monitor_commercial_setup_no_client):
        """Test the dbus subsystem"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        dbus_name = "test"
        user_name = "bugs.bunny@acme.org"
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        logger.info("test_dbus_subsystem: env ready.")

        logger.info("test_dbus_subsystem: email alert on dbus signal scenario.")
        prepare_dbus_monitoring(mender_device, dbus_name)
        time.sleep(2 * wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) > 0
        m = messages[0]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_dbus_subsystem: got CRITICAL alert email.")

    def test_dbus_pattern_match(self, monitor_commercial_setup_no_client):
        """Test the dbus subsystem"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        dbus_name = "test"
        user_name = "bugs.bunny@acme.org"
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        logger.info("test_dbus_pattern_match: env ready.")

        logger.info(
            "test_dbus_pattern_match: email alert on dbus signal pattern match scenario."
        )
        alert_expiration_seconds = 16
        prepare_dbus_monitoring(
            mender_device,
            dbus_name,
            log_pattern="member=JobNew",
            alert_expiration=alert_expiration_seconds,
        )
        time.sleep(2 * wait_for_alert_interval_s)
        mender_device.run("echo trigger event")
        mender_device.run("echo trigger event")
        time.sleep(2 * wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) > 0
        m = messages[0]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_dbus_pattern_match: got CRITICAL alert email.")

        # t="/tmp/bp0"
        # logger.info("waiting for %s"%t)
        # while not os.path.exists(t):
        #     time.sleep(0.1)
        logger.info("test_dbus_pattern_match: waiting for pattern to expire.")
        time.sleep(1.5*alert_expiration_seconds)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) > 1
        m = messages[1]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "OK: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info(
            "test_dbus_pattern_match: got OK alert email after expiration time passed."
        )
        # t="/tmp/bp1"
        # logger.info("waiting for %s"%t)
        # while not os.path.exists(t):
        #     time.sleep(0.1)

    def test_dbus_bus_filter(self, monitor_commercial_setup_no_client):
        """Test the dbus subsystem"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        dbus_name = "test"
        user_name = "bugs.bunny@acme.org"
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        logger.info("test_dbus_bus_filter: env ready.")

        logger.info(
            "test_dbus_bus_filter: email alert on single dbus filter signal scenario."
        )
        alert_expiration_seconds = 16
        prepare_dbus_monitoring(
            mender_device,
            dbus_name,
            dbus_pattern="type='signal',interface='org.freedesktop.systemd1.Manager',member=JobNew",
            alert_expiration=alert_expiration_seconds,
        )
        time.sleep(2 * wait_for_alert_interval_s)
        mender_device.run("echo trigger event")
        mender_device.run("echo trigger event")
        time.sleep(2 * wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) > 0
        m = messages[0]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info("test_dbus_bus_filter: got CRITICAL alert email.")

        # t="/tmp/bp2"
        # logger.info("waiting for %s"%t)
        # while not os.path.exists(t):
        #     time.sleep(0.1)
        logger.info("test_dbus_bus_filter: waiting for pattern to expire.")
        time.sleep(1.5 * alert_expiration_seconds)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) > 1
        m = messages[1]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "OK: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info(
            "test_dbus_bus_filter: got OK alert email after expiration time passed."
        )
        # t="/tmp/bp3"
        # logger.info("waiting for %s"%t)
        # while not os.path.exists(t):
        #     time.sleep(0.1)

    def test_monitorclient_logs_and_services(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting for multiple services with extra checks"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        user_name = "bugs.bunny@acme.org"
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)
        logger.info("test_monitorclient_alert_email: env ready.")

        logger.info(
            "test_monitorclient_logs_and_services: email alert on systemd service not running scenario."
        )
        for service_name in ["crond", "mender-connect"]:
            prepare_service_monitoring(mender_device, service_name, use_ctl=True)

        time.sleep(2 * wait_for_alert_interval_s)

        for service_name in ["crond", "mender-connect"]:
            mender_device.run("systemctl stop %s" % service_name)
            logger.info(
                "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
            )
            time.sleep(wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 2) == (alerts, alert_count)

        for service_name in ["crond", "mender-connect"]:
            mender_device.run("systemctl start %s" % service_name)
            logger.info(
                "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
            )
            time.sleep(wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (False, 0) == (alerts, alert_count)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        assert "Content-Type: multipart/alternative;" in mail
        assert "Content-Type: text/html" in mail
        assert "Content-Type: text/plain" in mail
        assert devid in mail
        assert service_name in mail
        assert not "${workflow.input." in mail
        messages = parse_email(mail)
        messages_count = len(messages)
        assert messages_count == 4
        for m in messages:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             To: %s", m["Bcc"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])

        assert len(messages) > 0
        i = 0
        for service_name in ["crond", "mender-connect"]:
            m = messages[i]
            i = i + 1
            assert "Bcc" in m
            assert "From" in m
            assert "Subject" in m
            assert m["Bcc"] == user_name
            assert m["From"] == expected_from
            assert (
                m["Subject"]
                == "CRITICAL: Monitor Alert for Service "
                + service_name
                + " not running on "
                + devid
            )
            logger.info(
                "test_monitorclient_logs_and_services: got CRITICAL alert email for %s."
                % service_name
            )

        for service_name in ["crond", "mender-connect"]:
            m = messages[i]
            i = i + 1
            assert "Bcc" in m
            assert "From" in m
            assert "Subject" in m
            assert m["Bcc"] == user_name
            assert m["From"] == expected_from
            assert (
                m["Subject"]
                == "OK: Monitor Alert for Service "
                + service_name
                + " not running on "
                + devid
            )
            assert not "${workflow.input" in mail
            logger.info(
                "test_monitorclient_logs_and_services: got OK alert email for %s."
                % service_name
            )

        logger.info(
            "test_monitorclient_logs_and_services: email alert on log file containing a pattern scenario."
        )
        log_file = "/tmp/mylog.log"
        log_pattern = "session opened for user [a-z]*"

        service_name = "mylog"
        prepare_log_monitoring(
            mender_device, service_name, log_file, log_pattern, use_ctl=True
        )
        prepare_log_monitoring(
            mender_device,
            service_name + "-tail",
            "@tail -f " + log_file,
            log_pattern,
            use_ctl=True,
        )
        mender_device.run("systemctl restart mender-monitor")
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("echo 'some line 1' >> " + log_file)
        mender_device.run("echo 'some line 2' >> " + log_file)
        time.sleep(wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)
        assert messages_count == len(messages)

        mender_device.run(
            "echo -ne 'a new session opened for user root now\nsome line 3\n' >> "
            + log_file
        )
        time.sleep(wait_for_alert_interval_s)

        mender_device.run("echo 'some line 4' >> " + log_file)
        mender_device.run("echo 'some line 5' >> " + log_file)

        mender_device.run(
            "echo -ne 'a new session opened for user root now\nsome line 3\n' >> "
            + log_file
        )
        time.sleep(wait_for_alert_interval_s)

        time.sleep(2 * wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        assert messages_count > 3
        for m in [messages[-1], messages[-2]]:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             To: %s", m["Bcc"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])
            assert "Bcc" in m
            assert "From" in m
            assert "Subject" in m
            assert m["Bcc"] == user_name
            assert m["From"] == expected_from
            assert m["Subject"].startswith(
                "CRITICAL: Monitor Alert for Log file contains "
                + log_pattern
                + " on "
                + devid
            )

    def test_monitorclient_send_saved_alerts_on_network_issues(
        self, monitor_commercial_setup_no_client
    ):
        """Tests that the client does indeed cache alerts and resend them in the face
        of issues, like network connectivity"""

        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "noreply@mender.io"
        user_name = "bugs.bunny@acme.org"

        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)
        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: env ready."
        )

        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: email alert on systemd service not running scenario."
        )

        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues disabling access to docker.mender.io (point to localhost in /etc/hosts)"
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 docker.mender.io' /etc/hosts")

        log_file_name = "/tmp/mylog.log"
        log_file = "@tail -f " + log_file_name
        log_pattern = "session opened for user [a-z]*"

        service_name = "mylog"
        prepare_log_monitoring(
            mender_device, service_name, log_file, log_pattern,
        )

        # The file needs to exist beforehand, otherwise the monitoring will just exit with a ERRNOEXIST
        mender_device.run("touch " + log_file_name)
        mender_device.run("systemctl restart mender-monitor")
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("echo 'some line 1' >> " + log_file_name)
        mender_device.run("echo 'some line 2' >> " + log_file_name)
        mender_device.run(
            "echo 'a new session opened for user root now' >> " + log_file_name
        )
        mender_device.run(
            "echo -ne 'some line 4\nsome line 5\nsome line 6\n' >> " + log_file_name
        )
        time.sleep(2 * wait_for_alert_interval_s)
        mender_device.run(
            "echo 'a new session opened for user root now' >> " + log_file_name
        )
        mender_device.run("echo -ne 'some line 7\nsomeline 8\n' >> " + log_file_name)
        time.sleep(4 * wait_for_alert_interval_s)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)

        assert len(messages) == 0
        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: got no alerts, device is offline."
        )

        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues re-enabling access to docker.mender.io (restoring /etc/hosts)"
        )
        mender_device.run("cp /etc/hosts.backup /etc/hosts")
        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues waiting for alerts to come."
        )
        time.sleep(wait_for_alert_interval_s * 10)

        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        for m in messages:
            logger.debug("got message:")
            logger.debug("             body: %s", m.get_body().get_content())
            logger.debug("             To: %s", m["To"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])

        output = mender_device.run(
            "journalctl -u mender-monitor --output=cat --no-pager --reverse"
        )

        assert len(messages) == 2, output
        for m in [messages[0], messages[1]]:
            assert "Bcc" in m
            assert "From" in m
            assert "Subject" in m
            assert m["Bcc"] == user_name
            assert m["From"] == expected_from
            assert m["Subject"].startswith(
                "CRITICAL: Monitor Alert for Log file contains "
                + log_pattern
                + " on "
                + devid
            )
            assert not "${workflow.input" in mail
            logger.info(
                "test_monitorclient_send_saved_alerts_on_network_issues: got CRITICAL alert email."
            )

        m = messages[-1]
        assert "Bcc" in m
        assert "From" in m
        assert "Subject" in m
        assert m["Bcc"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"].startswith(
            "CRITICAL: Monitor Alert for Log file contains "
            + log_pattern
            + " on "
            + devid
        )
        assert not "${workflow.input" in mail
        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: got OK alert email."
        )
