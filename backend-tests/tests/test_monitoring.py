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

import pytest
import re
import time
import uuid

from datetime import datetime

from testutils.api import useradm, devicemonitor, deviceauth, inventory
from testutils.api.client import ApiClient
from testutils.common import (
    clean_mongo,
    create_authset,
    create_org,
    create_random_authset,
    create_user,
    make_accepted_device,
    make_pending_device,
    mongo,
)
from testutils.infra.cli import CliUseradm, CliDeviceauth, CliDeviceMonitor
from testutils.infra.smtpd_mock import smtp_server


@pytest.fixture(scope="function")
def clean_migrated_mongo(clean_mongo):
    CliDeviceauth().migrate()
    CliUseradm().migrate()
    CliDeviceMonitor().migrate()
    yield clean_mongo


@pytest.fixture(scope="function")
def tenants_users(clean_migrated_mongo):
    tenants = []
    for n in range(2):
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "ci.email.tests+" + uuidv4 + "@mender.io",
            "secretsecret",
        )
        tenants.append(create_org(tenant, username, password))

    yield tenants


@pytest.fixture(scope="function")
def user(clean_migrated_mongo):
    yield create_user("user-foo@acme.com", "correcthorse")


@pytest.fixture(scope="function")
def tenants_users_devices(tenants_users):
    uc = ApiClient(useradm.URL_MGMT)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)

    for t in tenants_users:
        user = t.users[0]
        r = uc.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
        assert r.status_code == 200
        utoken = r.text
        t.users[0].token = utoken

        for _ in range(5):
            dev = make_accepted_device(devauthd, devauthm, utoken, t.tenant_token)
            t.devices.append(dev)

    yield tenants_users


@pytest.fixture(scope="function")
def devices(user):
    uc = ApiClient(useradm.URL_MGMT)
    devauthm = ApiClient(deviceauth.URL_MGMT)
    devauthd = ApiClient(deviceauth.URL_DEVICES)

    r = uc.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert r.status_code == 200
    utoken = r.text

    devices = []

    for _ in range(5):
        dev = make_accepted_device(devauthd, devauthm, utoken)
        devices.append(dev)

    yield devices


ONE_MINUTE_SEC = 60.0


class _TestMonitoringAlertsBase:
    useradm = ApiClient(useradm.URL_MGMT)
    devmond = ApiClient(devicemonitor.URL_DEVICES)
    invm = ApiClient(inventory.URL_MGMT)

    def test_alerting_email(self, test_case, user, devices, smtp_server):
        device = devices.pop(1)
        r = self.devmond.with_auth(device.token).call(
            "POST", devicemonitor.URL_ALERT, test_case["alerts"],
        )
        assert r.status_code < 300

        try:
            wait_start = datetime.now()
            smtp_server.await_messages(len(test_case["alerts"]), ONE_MINUTE_SEC)
            wait_time = datetime.now() - wait_start
            # Wait the same amount of time for which we expect
            # to see more messages incomming if there are any.
            time.sleep(wait_time.total_seconds())
        except TimeoutError:
            raise TimeoutError(
                "did not receive the expected number of emails in time (%.0f seconds)"
                % ONE_MINUTE_SEC
            )
        messages = smtp_server.messages()
        assert len(messages) == len(test_case["alerts"])

        regex = test_case.get("email_regex", [])
        if isinstance(regex, str):
            regex = [regex]

        for message in messages:
            data = message.data.decode("utf-8")
            assert device.id in data
            assert user.name in data
            for ex in regex:
                assert re.search(ex, data), "email did not contain expected content"

        rsp = self.invm.with_auth(user.token).call(
            "GET", inventory.URL_DEVICE.format(id=device.id)
        )
        assert rsp.status_code == 200
        alert_count_attrs = {
            x["name"]: x["value"]
            for x in filter(
                lambda x: x["scope"] == "monitor", rsp.json()["attributes"],
            )
        }
        assert len(alert_count_attrs) == 2
        assert alert_count_attrs["alert_count"] == test_case["alert_count"]
        if test_case["alert_count"] > 0:
            assert alert_count_attrs["alerts"] == True
        else:
            assert alert_count_attrs["alerts"] == False


class TestMonitoringAlertsEnterprise(_TestMonitoringAlertsBase):
    useradm = ApiClient(useradm.URL_MGMT)
    devmonit = ApiClient(devicemonitor.URL_DEVICES)

    @pytest.mark.parametrize(
        argnames="test_case",
        argvalues=(
            {
                "alerts": [
                    {
                        "name": "Something terrible may happen!",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "level": "CRITICAL",
                        "subject": {
                            "name": "mender-connect",
                            "status": "killed",
                            "type": "systemd.unit",
                            "details": {
                                "description": "Something terrible actually happened!"
                            },
                        },
                    },
                ],
                "alert_count": 1,
                "email_regex": "(CRITICAL|OK)",
            },
            {
                "alerts": [
                    {
                        "name": "mender-client be like",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "level": "OK",
                        "subject": {
                            "name": "mender-connect",
                            "status": "running",
                            "type": "systemd.unit",
                            "details": {"description": "It's all good"},
                        },
                    },
                    {
                        "name": "sshd systemd unit",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "level": "CRITICAL",
                        "subject": {
                            "name": "sshd",
                            "status": "killed",
                            "type": "systemd.unit",
                            "details": {"description": "Well, this is awkward"},
                        },
                    },
                    {
                        "name": "Go please!",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "level": "CRITICAL",
                        "subject": {
                            "name": "gopls",
                            "status": "killed",
                            "type": "process",
                            "details": {"description": "not again..."},
                        },
                    },
                ],
                "email_regex": "(CRITICAL|OK)",
                "alert_count": 2,
            },
        ),
        ids=["CRITICAL alert", "CRITICAL and OK alerts"],
    )
    def test_alerting_email(self, test_case, tenants_users_devices, smtp_server):
        """
        Checks that each alert a device issues to the backend triggers
        an email sent to the user.
        """
        tenant = tenants_users_devices[0]
        user = tenant.users[0]
        devices = tenant.devices
        super().test_alerting_email(test_case, user, devices, smtp_server)
