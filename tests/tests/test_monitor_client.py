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

import datetime
import json
import os
import os.path
import pytest
import shutil
import tempfile
import time
import uuid
import inspect

from email.parser import Parser
from email.policy import default
from redo import retriable
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
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra import smtpd_mock
from testutils.common import User, new_tenant_client
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

# tests constants
mailbox_path = "/var/spool/mail/local"
wait_for_alert_interval_s = 8 if not isK8S() else 32
alert_expiration_time_seconds = 32 if not isK8S() else 64
expected_from = (
    "no-reply@hosted.mender.io"
    if not isK8S()
    else "Mender <no-reply@staging.hosted.mender.io>"
)


@retriable(sleeptime=60, attempts=5)
def get_and_parse_email_n(env, address, n):
    mail, messages = get_and_parse_email(env, address)
    assert len(messages) >= n
    return mail, messages


def get_and_parse_email(env, address):
    # get the message from gmail
    if isK8S():
        smtp = smtpd_mock.smtp_server_gmail()
        mail = ""
        headers = []
        messages = smtp.filtered_messages(address)
        messages.reverse()
        for m in messages:
            data = m.data.decode("utf-8")
            mail += data + "\n"
            headers.append(Parser(policy=default).parsestr(data))
        logger.info([(x["Date"], x["Subject"]) for x in headers])
        return mail, headers
    # get the email from the SMTP server
    else:
        mail = env.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        # read spool line by line, eval(line).decode('utf-8') for each line in lines
        # between start and end of message
        # concat and create header object for each
        headers = []
        message_string = ""
        device_date = None
        for line in mail.splitlines():
            if line.startswith(message_mail_options_prefix):
                continue
            if message_start == line:
                message_string = ""
                device_date = None
                continue
            if message_end == line:
                if device_date is not None:
                    logger.debug(f"using device_date {device_date}")
                    message_string = (
                        device_date.strftime("Date: %a, %m %b %Y %H:%M:%S +0200")
                        + "\n"
                        + message_string
                    )
                    logger.debug("msg:%s" % message_string)
                h = Parser(policy=default).parsestr(message_string)
                headers.append(h)
                continue
            # extra safety, we are supposed to only eval b'string' lines
            if not line.startswith("b'"):
                continue
            line_string = eval(line).decode("utf-8")
            message_string = message_string + line_string + "\n"
            # get the date from b'Time on device: Thu, 01 Dec 2022 14:01:01 UTC' line
            if line_string.startswith("Time on device: "):
                device_date = datetime.datetime.strptime(
                    line_string, "Time on device: %a, %d %b %Y %H:%M:%S %Z"
                )
                logger.debug(f"parsed device_date {device_date}")

    # log all messages for debug
    for m in headers:
        logger.debug("got message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             Bcc: %s", m["Bcc"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])

    return mail, headers


def assert_valid_alert(message, bcc, subject):
    assert isK8S() or "Bcc" in message
    assert "From" in message
    assert "Subject" in message
    assert isK8S() or message["Bcc"] == bcc
    assert message["From"] == expected_from
    assert message["Subject"].startswith(subject)


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
    mender_device, dbus_name, log_pattern=None, dbus_pattern=None
):
    try:
        monitor_available_dir = "/etc/mender-monitor/monitor.d/available"
        monitor_enabled_dir = "/etc/mender-monitor/monitor.d/enabled"
        mender_device.run("mkdir -p '%s'" % monitor_available_dir)
        mender_device.run("mkdir -p '%s'" % monitor_enabled_dir)
        tmpdir = tempfile.mkdtemp()
        dbus_check_file = os.path.join(tmpdir, "dbus_test.sh")
        f = open(dbus_check_file, "w")
        f.write("DBUS_NAME=%s\n" % dbus_name)
        if log_pattern:
            f.write("DBUS_PATTERN=%s\n" % log_pattern)
        if dbus_pattern:
            f.write("DBUS_WATCH_PATTERN=%s\n" % dbus_pattern)
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


def prepare_dockerevents_monitoring(
    mender_device, container_name, alert_expiration="", action="restart"
):
    mender_device.run(
        "mender-monitorctl create dockerevents container_%s_%s %s %s %s"
        % (container_name, action, container_name, action, alert_expiration)
    )
    mender_device.run(
        "mender-monitorctl enable dockerevents container_%s_%s"
        % (container_name, action)
    )


class TestMonitorClientEnterprise:
    """Tests for the Monitor client"""

    def prepare_env(self, env, user_name):
        u = User("", user_name, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=env.name)

        uuidv4 = str(uuid.uuid4())
        name = "test.mender.io-" + uuidv4
        tid = cli.create_org(name, u.name, u.pwd, plan="enterprise", addons=["monitor"])

        # at the moment we do not have a notion of a monitor add-on in the
        # backend, but this will be needed here, see MEN-4809
        # update_tenant(
        #  tid, addons=["monitor"], container_manager=get_container_manager(),
        # )

        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)

        auth = authentication.Authentication(name=name, username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth_tenant = DeviceAuthV2(auth)

        mender_device = new_tenant_client(env, "mender-client", tenant["tenant_token"])
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

        logger.info("%s: env ready.", inspect.stack()[1].function)

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
        service_name = "crond"
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)

        logger.info(
            "test_monitorclient_alert_email: email alert on systemd service not running scenario."
        )
        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert len(messages) > 0
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        assert "${workflow.input." not in mail
        logger.info("test_monitorclient_alert_email: got CRITICAL alert email.")

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (False, 0) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 2
        )
        messages_count = len(messages)
        assert messages_count >= 2
        assert_valid_alert(
            messages[1],
            user_name,
            "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        assert "${workflow.input" not in mail
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

        time.sleep(2 * wait_for_alert_interval_s)
        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count
        )
        assert messages_count == len(messages)

        mender_device.run(
            "echo -ne 'a new session opened for user root now\nsome line 3\n' >> "
            + log_file
        )

        time.sleep(wait_for_alert_interval_s)
        mender_device.run("echo 'some line 4' >> " + log_file)
        mender_device.run("echo 'some line 5' >> " + log_file)

        time.sleep(2 * wait_for_alert_interval_s)
        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count + 1
        )
        messages_count = len(messages)
        assert_valid_alert(
            messages[-1],
            user_name,
            "CRITICAL: Monitor Alert for Log file contains "
            + log_pattern
            + " on "
            + devid,
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
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count + 1
        )
        messages_count = len(messages)
        assert_valid_alert(
            messages[-1],
            user_name,
            "OK: Monitor Alert for Log file contains " + log_pattern + " on " + devid,
        )
        # in each CRITICAL and OK email we expect the pattern to be present at least 3 times
        assert mail.count(log_pattern) >= 6
        # in each CRITICAL and OK email we expect the log path to be present at least 1 time
        assert mail.count(log_pattern) >= 2
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
        service_name = "crond"
        prepare_log_monitoring(
            mender_device,
            service_name,
            "@journalctl -f -u " + service_name,
            ": Started .*",
        )
        mender_device.run("echo -ne > /tmp/mylog.log")
        mender_device.run("systemctl restart mender-monitor")
        time.sleep(wait_for_alert_interval_s)
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count + 1
        )
        messages_count = len(messages)
        assert_valid_alert(
            messages[-1],
            user_name,
            "CRITICAL: Monitor Alert for Log file contains : Started",
        )
        assert "${workflow.input" not in mail

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
        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count + 1
        )
        assert_valid_alert(
            messages[-1],
            user_name,
            "OK: Monitor Alert for Log file contains " + log_pattern + " on " + devid,
        )
        logger.info(
            "test_monitorclient_alert_email: got OK alert email after log pattern expiration in case of streaming log file."
        )

    def test_monitorclient_alert_email_with_group(
        self, monitor_commercial_setup_no_client
    ):
        """Tests the monitor client email alerting with device in a static group"""
        service_name = "crond"
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        device_static_group = "localGroup0"
        inventory = Inventory(auth)
        inventory.put_device_in_group(devid, device_static_group)

        logger.info(
            "test_monitorclient_alert_email_with_group: email alert on systemd service not running scenario."
        )
        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert len(messages) > 0
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
            + " in group: "
            + device_static_group,
        )
        assert "${workflow.input." not in mail
        logger.info(
            "test_monitorclient_alert_email_with_group: got CRITICAL alert email."
        )

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (False, 0) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 2
        )
        messages_count = len(messages)
        assert messages_count >= 2
        assert_valid_alert(
            messages[1],
            user_name,
            "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid
            + " in group: "
            + device_static_group,
        )
        assert "${workflow.input" not in mail
        logger.info("test_monitorclient_alert_email_with_group: got OK alert email.")

    def test_monitorclient_flapping(self, monitor_commercial_setup_no_client):
        """Tests the monitor client flapping support"""
        wait_for_alert_interval_s = 120 if not isK8S() else 240
        service_name = "crond"
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

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

        logger.info(
            "test_monitorclient_flapping: waiting for %s seconds"
            % (2 * wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)
        mail, messages = get_and_parse_email(
            monitor_commercial_setup_no_client, user_name
        )
        messages_flipping = list(
            filter(lambda x: "going up and down" in x["Subject"], messages)
        )
        assert len(messages_flipping) >= 1
        messages_count_flapping = messages.index(messages_flipping[-1]) + 1
        assert_valid_alert(
            messages_flipping[-1],
            user_name,
            "CRITICAL: Monitor Alert for Service "
            + service_name
            + " going up and down on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_monitorclient_flapping: got CRITICAL alert email.")

        logger.info(
            "test_monitorclient_flapping: waiting for %s seconds"
            % wait_for_alert_interval_s
        )

        time.sleep(2 * wait_for_alert_interval_s)
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count_flapping + 1,
        )
        assert messages_count_flapping + 1 <= len(messages)
        assert_valid_alert(
            messages[-1],
            user_name,
            "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_monitorclient_flapping: got OK alert email.")

    def test_monitorclient_alert_email_rbac(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting respecting RBAC"""
        # first let's get the OK and CRITICAL email alerts {{{
        service_name = "crond"
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)

        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert len(messages) > 0

        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_monitorclient_alert_email_rbac: got CRITICAL alert email.")

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (False, 0) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 2
        )
        messages_count = len(messages)
        assert messages_count >= 2
        assert_valid_alert(
            messages[1],
            user_name,
            "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        assert "${workflow.input" not in mail
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

        time.sleep(2 * wait_for_alert_interval_s)
        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count
        )
        assert len(messages) == messages_count
        # we did not receive any email -- user has no access to the device
        logger.info(
            "test_monitorclient_alert_email_rbac: did not receive CRITICAL email alert."
        )

        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )

        time.sleep(2 * wait_for_alert_interval_s)
        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, messages_count
        )
        assert len(messages) == messages_count
        # we did not receive any email -- user has no access to the device
        logger.info(
            "test_monitorclient_alert_email_rbac: did not receive OK email alert."
        )

    def test_monitorclient_alert_store(self, monitor_commercial_setup_no_client):
        """Tests the monitor client alert local store"""
        service_name = "rpcbind"
        hostname = os.environ.get("GATEWAY_HOSTNAME", "docker.mender.io")
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        logger.info(
            "test_monitorclient_alert_store: store alerts when offline scenario."
        )

        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        logger.info(
            "test_monitorclient_alert_store: disabling access to %s (point to localhost in /etc/hosts)"
            % hostname
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 %s' /etc/hosts" % hostname)
        mender_device.run("systemctl restart mender-authd")
        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        expected_alerts_count = 1  # one for CRITICAL, because we stopped the service
        time.sleep(wait_for_alert_interval_s)
        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        expected_alerts_count = (
            expected_alerts_count + 1
        )  # one for OK, because we started the service

        time.sleep(2 * wait_for_alert_interval_s)
        _, messages = get_and_parse_email(monitor_commercial_setup_no_client, user_name)
        assert len(messages) == 0
        logger.info("test_monitorclient_alert_store: got no alerts, device is offline.")

        logger.info(
            "test_monitorclient_alert_store: re-enabling access to %s (restoring /etc/hosts)"
            % hostname
        )
        mender_device.run("mv /etc/hosts.backup /etc/hosts")
        logger.info("test_monitorclient_alert_store: waiting for alerts to come.")

        time.sleep(8 * wait_for_alert_interval_s)
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 2
        )
        logger.info("got %d alert messages", len(messages))

        assert len(messages) > 1

        # if running on Kubernetes, therefore using a real mailbox, we need to explicitly
        # sort the emails by subject to avoid wrong-order issues because of delivery time
        # with QA-510, we bring the sorting of emails according to an alert time as noted
        # on a device. the staging could use the same, leaving it as is, since the staging
        # tests need some attention in other places.
        if isK8S():
            messages.sort(key=lambda x: x["Subject"])
        else:
            messages.sort(key=lambda x: x["Date"])

        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_monitorclient_alert_store: got CRITICAL alert email.")

        assert_valid_alert(
            messages[1],
            user_name,
            "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_monitorclient_alert_store: got OK alert email.")

        logger.info("test_monitorclient_alert_store: large alert store (MEN-5133).")
        log_file = "/tmp/mylog.log"
        log_pattern = "session opened for user [a-z]*"

        service_name = "mylog"
        prepare_log_monitoring(
            mender_device, service_name, log_file, log_pattern,
        )
        mender_device.run("touch '" + log_file + "'")
        logger.info(
            "test_monitorclient_alert_store: large store disabling access to %s (point to localhost in /etc/hosts)"
            % hostname
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 %s' /etc/hosts" % hostname)
        mender_device.run("systemctl restart mender-authd")

        patterns_count = 30
        expected_alerts_count = (
            expected_alerts_count + 1
        )  # one for all the patterns detected in log (changed with MEN-5458)
        for i in range(patterns_count):
            mender_device.run(
                "for i in {1..4}; do echo 'some line '$i >> " + log_file + "; done"
            )
            mender_device.run(
                "echo 'the session session opened for user tests' >> " + log_file
            )
            mender_device.run(
                "for i in {6..9}; do echo 'some line '$i >> " + log_file + "; done"
            )
            time.sleep(wait_for_alert_interval_s)

        logger.info(
            "test_monitorclient_alert_store: re-enabling access to %s (restoring /etc/hosts)"
            % hostname
        )
        mender_device.run("mv /etc/hosts.backup /etc/hosts")
        time.sleep(
            9 * wait_for_alert_interval_s
        )  # at the moment we send stored alerts every minute

        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, expected_alerts_count
        )
        assert len(messages) >= expected_alerts_count
        logger.info("got %d alert messages." % len(messages))

    def test_dbus_subsystem(self, monitor_commercial_setup_no_client):
        """Test the dbus subsystem"""
        dbus_name = "test"
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        logger.info("test_dbus_subsystem: email alert on dbus signal scenario.")
        prepare_dbus_monitoring(mender_device, dbus_name)

        time.sleep(2 * wait_for_alert_interval_s)
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert len(messages) > 0
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_dbus_subsystem: got CRITICAL alert email.")

    def test_dbus_pattern_match(self, monitor_commercial_setup_no_client):
        """Test the dbus subsystem"""
        dbus_name = "test"
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        logger.info(
            "test_dbus_pattern_match: email alert on dbus signal pattern match scenario."
        )
        prepare_dbus_monitoring(mender_device, dbus_name, log_pattern="mender")

        time.sleep(2 * wait_for_alert_interval_s)
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert len(messages) > 0
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_dbus_pattern_match: got CRITICAL alert email.")

    def test_dbus_bus_filter(self, monitor_commercial_setup_no_client):
        """Test the dbus subsystem"""
        dbus_name = "test"
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        logger.info(
            "test_dbus_bus_filter: email alert on single dbus filter signal scenario."
        )
        prepare_dbus_monitoring(
            mender_device,
            dbus_name,
            dbus_pattern="type='signal',interface='io.mender.Authentication1'",
        )

        time.sleep(2 * wait_for_alert_interval_s)
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert len(messages) > 0
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_dbus_bus_filter: got CRITICAL alert email.")

    def test_monitorclient_logs_and_services(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting for multiple services with extra checks"""
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)

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

        time.sleep(2 * wait_for_alert_interval_s)
        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 4
        )
        assert "Content-Type: multipart/alternative;" in mail
        assert "Content-Type: text/html" in mail
        assert "Content-Type: text/plain" in mail
        assert devid in mail
        assert service_name in mail
        assert "${workflow.input." not in mail
        assert len(messages) == 4

        # if running on Kubernetes, therefore using a real mailbox, we need to explicitly
        # sort the emails by subject to avoid wrong-order issues because of delivery time
        # with QA-510, we bring the sorting of emails according to an alert time as noted
        # on a device. the staging could use the same, leaving it as is, since the staging
        # tests need some attention in other places.
        if isK8S():
            messages.sort(key=lambda x: x["Subject"])
        else:
            messages.sort(key=lambda x: x["Date"])

        i = 0
        for service_name in ["crond", "mender-connect"]:
            assert_valid_alert(
                messages[i],
                user_name,
                "CRITICAL: Monitor Alert for Service "
                + service_name
                + " not running on "
                + devid,
            )
            logger.info(
                "test_monitorclient_logs_and_services: got CRITICAL alert email for %s."
                % service_name
            )
            i = i + 1

        for service_name in ["crond", "mender-connect"]:
            assert_valid_alert(
                messages[i],
                user_name,
                "OK: Monitor Alert for Service "
                + service_name
                + " not running on "
                + devid,
            )
            logger.info(
                "test_monitorclient_logs_and_services: got OK alert email for %s."
                % service_name
            )
            i = i + 1

        assert "${workflow.input" not in mail
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

        time.sleep(2 * wait_for_alert_interval_s)
        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 4
        )
        assert 4 == len(messages)

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
        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 5
        )
        assert len(messages) == 5
        # after MEN-5458 we expect only one critical for the log subsystem
        for m in [messages[-1]]:
            assert_valid_alert(
                m,
                user_name,
                "CRITICAL: Monitor Alert for Log file contains "
                + log_pattern
                + " on "
                + devid,
            )

        fds_count_timeout_s = 64
        max_fds_count_diff = 3
        logger.info(
            "test_monitorclient_logs_and_services: checking open file descriptors"
        )
        time.sleep(fds_count_timeout_s * 0.25)
        fds_count0 = mender_device.run(
            "ls /proc/$(cat /var/run/monitoring-client.pid)/fd | wc -l"
        )
        assert fds_count0.rstrip().isnumeric()
        fds_count0 = int(fds_count0.rstrip())
        logger.info(
            "test_monitorclient_logs_and_services: currently %s fds open" % fds_count0
        )
        time.sleep(4 * fds_count_timeout_s)
        fds_count1 = mender_device.run(
            "ls /proc/$(cat /var/run/monitoring-client.pid)/fd | wc -l"
        )
        assert fds_count1.rstrip().isnumeric()
        fds_count1 = int(fds_count1.rstrip())
        logger.info(
            "test_monitorclient_logs_and_services: currently %s fds open" % fds_count0
        )
        assert abs(fds_count1 - fds_count0) <= max_fds_count_diff
        logger.info(
            "test_monitorclient_logs_and_services: fds count have not increased"
        )

    def test_monitorclient_logs_and_surround(self, monitor_commercial_setup_no_client):
        """Tests more lines of logs surrounding a line matching a pattern"""
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)

        logger.info(
            "test_monitorclient_logs_and_surround: lines surrounding a pattern scenario."
        )
        log_file = "/tmp/mylog.long.log"
        log_pattern = "session opened for user \\w+"
        service_name = "mylog"

        lines_before_count = 64
        lines_after_count = 64
        for n in range(lines_before_count - 1):
            mender_device.run(
                "echo 'some long line of logs number: " + str(n) + "' >> " + log_file
            )
        mender_device.run(
            "echo 'a new session opened for user root now' >> " + log_file
        )
        for n in range(lines_after_count - 1):
            mender_device.run(
                "echo 'some long line of logs number: " + str(n) + "' >> " + log_file
            )
        prepare_log_monitoring(
            mender_device, service_name + "-pcre", log_file, log_pattern, use_ctl=True,
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Log file contains "
            + log_pattern
            + " on "
            + devid,
        )
        device_monitor = DeviceMonitor(auth)
        alerts = device_monitor.get_alerts(devid)
        assert len(alerts) == 1
        assert len(alerts[0]["subject"]["details"]["lines_before"]) == 30
        assert len(alerts[0]["subject"]["details"]["lines_after"]) == 30

    def test_monitorclient_logs_and_patterns(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting for a Perl compatible regex"""
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)

        logger.info(
            "test_monitorclient_logs_and_patterns: email alert on log file containing a pattern scenario."
        )
        log_file = "/tmp/mylog.log"
        log_pattern = "session opened for user \\w+"
        service_name = "mylog"

        mender_device.run("echo 'some line 1' >> " + log_file)
        mender_device.run("echo 'some line 2' >> " + log_file)
        prepare_log_monitoring(
            mender_device,
            service_name + "-pcre",
            "@tail -f " + log_file,
            log_pattern,
            use_ctl=True,
        )
        mender_device.run("systemctl restart mender-monitor")
        time.sleep(2 * wait_for_alert_interval_s)

        mender_device.run(
            "echo -ne 'a new session opened for user root now\nsome line 3\n' >> "
            + log_file
        )
        time.sleep(wait_for_alert_interval_s)

        mender_device.run("echo 'some line 4' >> " + log_file)
        mender_device.run("echo 'some line 5' >> " + log_file)

        mender_device.run(
            "echo -ne 'a new session opened for user root now\nsome line 5\n' >> "
            + log_file
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        _, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Log file contains "
            + log_pattern
            + " on "
            + devid,
        )

    def test_monitorclient_send_saved_alerts_on_network_issues(
        self, monitor_commercial_setup_no_client
    ):
        """Tests that the client does indeed cache alerts and resend them in the face
        of issues, like network connectivity"""

        hostname = os.environ.get("GATEWAY_HOSTNAME", "docker.mender.io")
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: email alert on log file containing a pattern scenario with flaky network."
        )

        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: disabling access to %s (point to localhost in /etc/hosts)"
            % hostname
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 %s' /etc/hosts" % hostname)
        mender_device.run("systemctl restart mender-authd")

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

        _, messages = get_and_parse_email(monitor_commercial_setup_no_client, user_name)
        assert len(messages) == 0
        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: got no alerts, device is offline."
        )

        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: re-enabling access to %s (restoring /etc/hosts)"
            % hostname
        )
        mender_device.run("cp /etc/hosts.backup /etc/hosts")
        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: waiting for alerts to come."
        )
        time.sleep(wait_for_alert_interval_s * 10)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 2
        )

        output = mender_device.run(
            "journalctl --unit mender-monitor --output cat --no-pager --reverse"
        )

        assert len(messages) == 2, output
        for m in [messages[0], messages[1]]:
            assert_valid_alert(
                m,
                user_name,
                "CRITICAL: Monitor Alert for Log file contains "
                + log_pattern
                + " on "
                + devid,
            )
            logger.info(
                "test_monitorclient_send_saved_alerts_on_network_issues: got CRITICAL alert email."
            )

        assert_valid_alert(
            messages[-1],
            user_name,
            "CRITICAL: Monitor Alert for Log file contains "
            + log_pattern
            + " on "
            + devid,
        )
        assert not "${workflow.input" in mail
        logger.info(
            "test_monitorclient_send_saved_alerts_on_network_issues: got CRITICAL alert email."
        )

    def test_monitorclient_send_configuration_data(
        self, monitor_commercial_setup_no_client
    ):
        """Tests the monitor client configuration push"""
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        logger.info(
            "test_monitorclient_send_configuration_data: push configuration scenario."
        )
        mender_device.run(
            "sed -i.backup -e 's/CONFPUSH_INTERVAL=.*/CONFPUSH_INTERVAL=8/' /usr/share/mender-monitor/config/config.sh"
        )
        prepare_service_monitoring(mender_device, "crond", use_ctl=True)
        prepare_service_monitoring(mender_device, "dbus", use_ctl=True)
        prepare_log_monitoring(
            mender_device, "syslog", "/var/log/syslog", "root.*access", use_ctl=True
        )
        prepare_log_monitoring(
            mender_device,
            "clientlogs",
            "@journalctl -u mender-authd -f",
            "[Ee]rror.*",
            use_ctl=True,
        )
        mender_device.run("systemctl restart mender-monitor")
        device_monitor = DeviceMonitor(auth)
        wait_iterations = wait_for_alert_interval_s
        while wait_iterations > 0:
            time.sleep(1)
            configuration = device_monitor.get_configuration(devid)
            if len(configuration) == 4:
                break
            wait_iterations = wait_iterations - 1

        assert len(configuration) == 4
        for entity in [
            {"name": "crond.sh", "type": "service"},
            {"name": "dbus.sh", "type": "service"},
            {"name": "syslog.sh", "type": "log"},
            {"name": "clientlogs.sh", "type": "log"},
        ]:
            found = False
            for c in configuration:
                assert "name" in c
                assert "type" in c
                assert "status" in c
                assert c["status"] == "enabled"
                if entity["name"] == c["name"] and entity["type"] == c["type"]:
                    found = True
                    break
            assert found

    def test_monitorclient_remove_old_alerts(self, monitor_commercial_setup_no_client):
        """Tests the removal of older alerts from the persistent store"""
        alert_resend_interval_s = 4
        alert_max_age = 16
        hostname = os.environ.get("GATEWAY_HOSTNAME", "docker.mender.io")
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        logger.info(
            "test_monitorclient_remove_old_alerts: remove old alerts from store scenario."
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 %s' /etc/hosts" % hostname)
        mender_device.run("systemctl restart mender-authd")

        mender_device.run(
            "sed -i.backup -e 's/ALERT_STORE_MAX_RECORD_AGE_S=.*/ALERT_STORE_MAX_RECORD_AGE_S="
            + str(alert_max_age)
            + "/' "
            + "-e 's/DEFAULT_ALERT_STORE_RESEND_INTERVAL_S=.*/DEFAULT_ALERT_STORE_RESEND_INTERVAL_S="
            + str(alert_resend_interval_s)
            + "/' "
            + "-e 's/SEND_ALERT_MAX_INTERVAL_S=.*/SEND_ALERT_MAX_INTERVAL_S=0"
            + "/' /usr/share/mender-monitor/config/config.sh"
        )

        mender_device.run(
            "bash -c 'cd /usr/share/mender-monitor && . lib/fixlenstore-lib.sh; for i in {1..4}; do fixlenstore_put key${i}; sleep 2; done;'"
        )
        mender_device.run("systemctl restart mender-monitor")
        time.sleep(alert_resend_interval_s)
        output = mender_device.run(
            "bash -c 'cd /usr/share/mender-monitor && . lib/fixlenstore-lib.sh; keys_nolock | wc -l;'"
        )
        logger.info("test_monitorclient_remove_old_alerts got %s keys" % output)
        assert output == "2\n"

        time.sleep(alert_resend_interval_s)
        output = mender_device.run(
            "bash -c 'cd /usr/share/mender-monitor && . lib/fixlenstore-lib.sh; keys_nolock | wc -l;'"
        )
        logger.info("test_monitorclient_remove_old_alerts got %s keys" % output)
        assert output == "0\n"

        mender_device.run(
            "mv /usr/share/mender-monitor/config/config.sh.backup /usr/share/mender-monitor/config/config.sh"
        )
        mender_device.run("systemctl restart mender-monitor")

    def test_monitorclient_alert_store_discard_http_400(
        self, monitor_commercial_setup_no_client
    ):
        """Tests that malformed alerts in the store (HTTP 400) are discarded"""
        service_name = "crond"
        hostname = os.environ.get("GATEWAY_HOSTNAME", "docker.mender.io")
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )

        prepare_service_monitoring(mender_device, service_name)
        time.sleep(2 * wait_for_alert_interval_s)

        logger.info(
            "test_monitorclient_alert_store_discard_http_400: disabling access to %s (point to localhost in /etc/hosts)"
            % hostname
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 %s' /etc/hosts" % hostname)
        mender_device.run("systemctl restart mender-authd")
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

        _, messages = get_and_parse_email(monitor_commercial_setup_no_client, user_name)
        assert len(messages) == 0
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: got no alerts, device is offline."
        )

        logger.info(
            "test_monitorclient_alert_store_discard_http_400: manipulating local store."
        )
        num_alerts_valid = mender_device.run(
            "bash -c '"
            "cd /usr/share/mender-monitor;"
            ". lib/fixlenstore-lib.sh;"
            "fixlenstore_count;"
            "'"
        ).strip()
        assert int(num_alerts_valid) == 2
        num_alerts_corrupted = mender_device.run(
            "bash -c '"
            "cd /usr/share/mender-monitor;"
            ". lib/fixlenstore-lib.sh;"
            'fixlenstore_put "invalid json break here";'
            'fixlenstore_put "something else there";'
            "fixlenstore_count;"
            "'"
        ).strip()
        assert int(num_alerts_corrupted) == 4

        logger.info(
            "test_monitorclient_alert_store_discard_http_400: re-enabling access to %s (restoring /etc/hosts)"
            % hostname
        )
        mender_device.run("mv /etc/hosts.backup /etc/hosts")
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: waiting for alerts (not) to come."
        )
        time.sleep(8 * wait_for_alert_interval_s)

        _, messages = get_and_parse_email(monitor_commercial_setup_no_client, user_name)
        assert len(messages) == 0
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: got no alerts, were they discarded?"
        )

        num_alerts_after_discard = mender_device.run(
            "bash -c '"
            "cd /usr/share/mender-monitor;"
            ". lib/fixlenstore-lib.sh;"
            "fixlenstore_count;"
            "'"
        ).strip()
        assert int(num_alerts_after_discard) == 0
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: store is empty, they were discarded!"
        )

        logger.info(
            "test_monitorclient_alert_store_discard_http_400: disabling again access to %s (point to localhost in /etc/hosts)"
            % hostname
        )
        mender_device.run("sed -i.backup -e '$a127.2.0.1 %s' /etc/hosts" % hostname)
        mender_device.run("systemctl restart mender-authd")
        mender_device.run("systemctl stop %s" % service_name)
        logger.info(
            "Stopped %s, sleeping %ds." % (service_name, wait_for_alert_interval_s)
        )
        expected_alerts_count = 1  # one for CRITICAL, because we stopped the service
        time.sleep(wait_for_alert_interval_s)
        mender_device.run("systemctl start %s" % service_name)
        logger.info(
            "Started %s, sleeping %ds" % (service_name, wait_for_alert_interval_s)
        )
        expected_alerts_count = (
            expected_alerts_count + 1
        )  # one for OK, because we started the service
        time.sleep(2 * wait_for_alert_interval_s)

        _, messages = get_and_parse_email(monitor_commercial_setup_no_client, user_name)
        assert len(messages) == 0
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: got no alerts, device is offline."
        )

        logger.info(
            "test_monitorclient_alert_store_discard_http_400: re-enabling again access to %s (restoring /etc/hosts)"
            % hostname
        )
        mender_device.run("mv /etc/hosts.backup /etc/hosts")
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: waiting for alerts to come."
        )
        time.sleep(8 * wait_for_alert_interval_s)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, expected_alerts_count,
        )
        assert len(messages) >= expected_alerts_count

        # if running on Kubernetes, therefore using a real mailbox, we need to explicitly
        # sort the emails by subject to avoid wrong-order issues because of delivery time
        # with QA-510, we bring the sorting of emails according to an alert time as noted
        # on a device. the staging could use the same, leaving it as is, since the staging
        # tests need some attention in other places.
        if isK8S():
            messages.sort(key=lambda x: x["Subject"])
        else:
            messages.sort(key=lambda x: x["Date"])

        assert "${workflow.input" not in mail
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: got CRITICAL alert email."
        )

        assert_valid_alert(
            messages[1],
            user_name,
            "OK: Monitor Alert for Service "
            + service_name
            + " not running on "
            + devid,
        )
        logger.info(
            "test_monitorclient_alert_store_discard_http_400: got OK alert email."
        )

    def mock_docker_events(self, mender_device):
        docker_events_exec = """
#!/bin/bash

while [ ! -f /tmp/docker_restart ]; do
 sleep 1;
done

cat <<EOF
2022-04-21T11:00:54.473698242+01:00 container kill 91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f (image=alpine, name=mycontainer, signal=15)
2022-04-21T11:01:04.608227731+01:00 container kill 91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f (image=alpine, name=mycontainer, signal=9)
2022-04-21T11:01:04.808707990+01:00 container die 91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f (exitCode=137, image=alpine, name=mycontainer)
2022-04-21T11:01:05.276636214+01:00 network disconnect a8a7c0f83bc81948886602fb3752fa5e63cc80c5997e696384ecefad8540cf32 (container=91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f, name=bridge, type=bridge)
2022-04-21T11:01:05.370419301+01:00 container stop 91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f (image=alpine, name=mycontainer)
2022-04-21T11:01:05.643509121+01:00 network connect a8a7c0f83bc81948886602fb3752fa5e63cc80c5997e696384ecefad8540cf32 (container=91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f, name=bridge, type=bridge)
2022-04-21T11:01:06.701635304+01:00 container start 91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f (image=alpine, name=mycontainer)
2022-04-21T11:01:06.701815043+01:00 container restart 91ee1d4888921c267bcaab048bd964778333d9d09db399a47d1ca9784441b69f (image=alpine, name=mycontainer)
EOF
while :; do
 sleep 2;
 [ ! -f /tmp/docker_restart ] && break;
done;
while [ ! -f /tmp/docker_restart ]; do
 sleep 1;
done
        """
        tmpdir = tempfile.mkdtemp()
        try:
            mender_device.run("mkdir -p /tmp/bin || true")
            docker_exec_file = os.path.join(tmpdir, "docker")
            with open(docker_exec_file, "w") as fd:
                fd.write(docker_events_exec)
            mender_device.put(
                os.path.basename(docker_exec_file),
                local_path=os.path.dirname(docker_exec_file),
                remote_path="/bin",
            )
            # lets assume we are not running tests in the rofs
            mender_device.run("chmod 755 /bin/docker")
        finally:
            shutil.rmtree(tmpdir)

    @pytest.fixture(scope="function")
    def setup_dockerevents(
        self, monitor_commercial_setup_no_client, action, container_name
    ):
        user_name = "ci.email.tests+{}@mender.io".format(str(uuid.uuid4()))
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        inventory = Inventory(auth)

        logger.info(
            "test_monitorclient_dockerevents: email alert on container %s restart scenario."
            % container_name
        )
        self.mock_docker_events(mender_device)
        prepare_dockerevents_monitoring(
            mender_device,
            container_name,
            str(alert_expiration_time_seconds),
            action=action,
        )
        # restart below is required as dockerevents is built upon log subsystem in the streaming from command mode
        mender_device.run("systemctl restart mender-monitor")
        time.sleep(2 * wait_for_alert_interval_s)
        return user_name, devid, mender_device, inventory

    @pytest.mark.parametrize("container_name", ["mycontainer"])
    @pytest.mark.parametrize("action", ["restart"])
    def test_monitorclient_dockerevents(
        self,
        monitor_commercial_setup_no_client,
        setup_dockerevents,
        action,
        container_name,
    ):
        """Tests the monitor client docker events subsystem"""
        user_name, devid, mender_device, inventory = setup_dockerevents
        mender_device.run("touch /tmp/docker_restart")
        logger.info(
            "restarted %s, sleeping %ds." % (container_name, wait_for_alert_interval_s)
        )
        time.sleep(2 * wait_for_alert_interval_s)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (True, 1) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        assert len(messages) > 0
        assert_valid_alert(
            messages[0],
            user_name,
            "CRITICAL: Monitor Alert for Docker container "
            + container_name
            + " "
            + action
            + " on "
            + devid,
        )
        assert "${workflow.input." not in mail
        logger.info("test_monitorclient_dockerevents: got CRITICAL alert email.")

        mender_device.run("rm -f /tmp/docker_restart")
        logger.info(
            "test_monitorclient_dockerevents: emulated restarts finished. waiting for OK."
        )
        time.sleep(alert_expiration_time_seconds)

        alerts, alert_count = self.get_alerts_and_alert_count_for_device(
            inventory, devid
        )
        assert (False, 0) == (alerts, alert_count)

        mail, messages = get_and_parse_email_n(
            monitor_commercial_setup_no_client, user_name, 1
        )
        messages_count = len(messages)
        assert messages_count > 0
        assert_valid_alert(
            messages[1],
            user_name,
            "OK: Monitor Alert for Docker container "
            + container_name
            + " "
            + action
            + " on "
            + devid,
        )
        assert "${workflow.input" not in mail
        logger.info("test_monitorclient_dockerevents: got OK alert email.")
