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

import testutils.api.tenantadm_v2 as tenantadm_v2
from testutils.api import useradm
from testutils.api.client import ApiClient
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra.smtpd_mock import smtp_server

from testutils.common import (
    clean_mongo,
    create_org,
    mongo,
)

api_tadm_v2 = ApiClient(tenantadm_v2.URL_MGMT, host=tenantadm_v2.HOST, schema="http://")
api_useradm = ApiClient(useradm.URL_MGMT)


class TestContactSupportEnterprise:
    def test_contact_support_bad_request(self, clean_mongo):
        uuidv4 = str(uuid.uuid4())
        tenant, email, password = (
            "test.mender.io-" + uuidv4,
            "some.user-" + uuidv4 + "@example.com",
            "secretsecret",
        )
        create_org(tenant, email, password)

        r = api_useradm.call("POST", useradm.URL_LOGIN, auth=(email, password))
        assert r.status_code == 200
        utoken = r.text
        r = api_tadm_v2.with_auth(utoken).call(
            "POST", tenantadm_v2.URL_CONTACT_SUPPORT, body={"foo": "bar"}
        )
        assert r.status_code == 400

    @pytest.mark.skipif(
        isK8S(), reason="not testable in a staging or production environment"
    )
    def test_contact_support(self, clean_mongo, smtp_server):
        uuidv4 = str(uuid.uuid4())
        tenant, email, password = (
            "test.mender.io-" + uuidv4,
            "some.user-" + uuidv4 + "@example.com",
            "secretsecret",
        )
        org = create_org(tenant, email, password)

        r = api_useradm.call("POST", useradm.URL_LOGIN, auth=(email, password))
        assert r.status_code == 200
        utoken = r.text
        r = api_tadm_v2.with_auth(utoken).call(
            "POST",
            tenantadm_v2.URL_CONTACT_SUPPORT,
            body={"subject": "foo", "body": "bar"},
        )
        assert r.status_code == 202
        # wait for the email
        message = None
        for i in range(15):
            messages = smtp_server.filtered_messages("support@mender.io")
            if len(messages) > 0:
                message = messages[0]
                break
            time.sleep(1)

        # be sure we received the email
        assert message is not None
        assert message.data != ""

        # and the email is properly formatted
        data = message.data.decode("utf-8")
        match = re.search(r"Subject: ([a-z0-9\-]+)", data,)
        subject = match.group(1)
        assert re.search(r"Subject: foo", data) is not None
        assert re.search(r"From: no-reply@hosted.mender.io", data) is not None
        assert re.search(r"To: support@mender.io", data) is not None
        assert re.search(r"Organization ID: " + org.id, data) is not None
        assert re.search(r"Organization name: " + tenant, data) is not None
        assert re.search(r"Plan name: os", data) is not None
        assert re.search(r"User ID: " + org.users[0].id, data) is not None
        assert re.search(r"User Email: " + email, data) is not None
        assert re.search(r"bar", data) is not None
