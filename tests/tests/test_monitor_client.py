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


def prepare_log_monitoring(mender_device, service_name, log_file, log_pattern):
    try:
        monitor_available_dir = "/etc/mender-monitor/monitor.d/available"
        monitor_enabled_dir = "/etc/mender-monitor/monitor.d/enabled"
        mender_device.run("mkdir -p '%s'" % monitor_available_dir)
        mender_device.run("mkdir -p '%s'" % monitor_enabled_dir)
        mender_device.run("systemctl restart %s" % service_name)
        tmpdir = tempfile.mkdtemp()
        service_check_file = os.path.join(tmpdir, "log_" + service_name + ".sh")
        f = open(service_check_file, "w")
        f.write(
            'SERVICE_NAME="%s"\nLOG_FILE="%s"\nLOG_PATTERN="%s"\n'
            % (service_name, log_file, log_pattern)
        )
        f.close()
        mender_device.put(
            os.path.basename(service_check_file),
            local_path=os.path.dirname(service_check_file),
            remote_path=monitor_available_dir,
        )
        mender_device.run(
            "ln -s '%s/log_%s.sh' '%s/log_%s.sh'"
            % (monitor_available_dir, service_name, monitor_enabled_dir, service_name)
        )
    finally:
        shutil.rmtree(tmpdir)


def prepare_dbus_monitoring(mender_device, dbus_name):
    try:
        monitor_available_dir = "/etc/mender-monitor/monitor.d/available"
        monitor_enabled_dir = "/etc/mender-monitor/monitor.d/enabled"
        mender_device.run("mkdir -p '%s'" % monitor_available_dir)
        mender_device.run("mkdir -p '%s'" % monitor_enabled_dir)
        tmpdir = tempfile.mkdtemp()
        dbus_check_file = os.path.join(tmpdir, "dbus_%s.sh" % dbus_name)
        f = open(dbus_check_file, "w")
        f.write("DBUS_NAME=%s\n" % dbus_name)
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

    def test_monitorclient_alert_email(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "alert@mender.io"
        service_name = "crond"
        user_name = "bugs.bunny@acme.org"
        devid, _, _, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
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
            == "CRITICAL: Monitor Alert for Service not running on " + devid
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

        messages_count = len(messages)
        assert messages_count > 1
        m = messages[1]
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"] == "OK: Monitor Alert for Service not running on " + devid
        logger.info("test_monitorclient_alert_email: got OK alert email.")

        logger.info(
            "test_monitorclient_alert_email: email alert on log file containing a pattern scenario."
        )
        log_file = "/tmp/mylog.log"
        log_pattern = "session opened for user [a-z]*"
        mender_device.run("echo 'some line' >> " + log_file)
        prepare_log_monitoring(
            mender_device, service_name, log_file, log_pattern,
        )
        time.sleep(2 * wait_for_alert_interval_s)
        mender_device.run("echo 'some line' >> " + log_file)
        time.sleep(wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        messages = parse_email(mail)
        assert messages_count == len(messages)

        mender_device.run(
            "echo 'a new session opened for user root now' >> " + log_file
        )
        time.sleep(wait_for_alert_interval_s)
        mender_device.run("echo 'some line' " + log_file)
        time.sleep(2 * wait_for_alert_interval_s)
        mail = monitor_commercial_setup_no_client.get_file("local-smtp", mailbox_path)
        logger.debug("got mail: '%s'", mail)
        messages = parse_email(mail)
        m = messages[-1]
        logger.debug("got message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             To: %s", m["To"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"].startswith(
            "CRITICAL: Monitor Alert for Log file contains "
            + log_pattern
            + " on "
            + devid
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
        logger.debug("             To: %s", m["To"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"].startswith(
            "CRITICAL: Monitor Alert for Log file contains State transition:"
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
            logger.debug("             To: %s", m["To"])
            logger.debug("             From: %s", m["From"])
            logger.debug("             Subject: %s", m["Subject"])
        m = messages[-1]
        logger.debug("(1) last message:")
        logger.debug("             body: %s", m.get_body().get_content())
        logger.debug("             To: %s", m["To"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for Service going up and down on " + devid
        )
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
        logger.debug("             To: %s", m["To"])
        logger.debug("             From: %s", m["From"])
        logger.debug("             Subject: %s", m["Subject"])
        assert messages_count_flapping + 1 == len(messages)
        assert m["Subject"] == "OK: Monitor Alert for Service not running on " + devid
        logger.info("test_monitorclient_flapping: got OK alert email.")

    def test_monitorclient_alert_email_rbac(self, monitor_commercial_setup_no_client):
        """Tests the monitor client email alerting respecting RBAC"""
        # first let's get the OK and CRITICAL email alerts {{{
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "alert@mender.io"
        service_name = "crond"
        user_name = "bugs.bunny@acme.org"
        devid, _, auth, mender_device = self.prepare_env(
            monitor_commercial_setup_no_client, user_name
        )
        logger.info("test_monitorclient_alert_email_rbac: env ready.")

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
            == "CRITICAL: Monitor Alert for Service not running on " + devid
        )
        logger.info("test_monitorclient_alert_email_rbac: got CRITICAL alert email.")

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

        messages_count = len(messages)
        assert messages_count > 1
        m = messages[1]
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"] == "OK: Monitor Alert for Service not running on " + devid
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
        expected_from = "alert@mender.io"
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
            "test_monitorclient_alert_store disabling accces to docker.mender.io (point to localhost in /etc/hosts)"
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
            "test_monitorclient_alert_store re-enabling accces to docker.mender.io (restoring /etc/hosts)"
        )
        mender_device.run("mv /etc/hosts.backup /etc/hosts")
        logger.info("test_monitorclient_alert_store waiting for alerts to come.")
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
        m = messages[0]
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for Service not running on " + devid
        )
        logger.info("test_monitorclient_alert_store: got CRITICAL alert email.")

        m=messages[1]
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert m["Subject"] == "OK: Monitor Alert for Service not running on " + devid

        logger.info("test_monitorclient_alert_store: got OK alert email")

    def test_dbus_subsystem(self, monitor_commercial_setup_no_client):
        """Test the dbus subsystem"""
        mailbox_path = "/var/spool/mail/local"
        wait_for_alert_interval_s = 8
        expected_from = "alert@mender.io"
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
        assert "To" in m
        assert "From" in m
        assert "Subject" in m
        assert m["To"] == user_name
        assert m["From"] == expected_from
        assert (
            m["Subject"]
            == "CRITICAL: Monitor Alert for D-Bus signal arrived on bus system bus on "
            + devid
        )
        logger.info("test_dbus_subsystem: got CRITICAL alert email.")
