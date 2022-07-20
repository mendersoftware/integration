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

from testutils.api import useradm
from testutils.api.client import ApiClient
from testutils.infra.smtpd_mock import smtp_server

from testutils.common import (
    clean_mongo,
    create_org,
    mongo,
)


class TestPasswordResetEnterprise:

    uc = ApiClient(useradm.URL_MGMT)

    def test_password_reset(self, clean_mongo, smtp_server):
        uuidv4 = str(uuid.uuid4())
        tenant, email, password = (
            "test.mender.io-" + uuidv4,
            "ci.email.tests+" + uuidv4 + "@mender.io",
            "secretsecret",
        )
        create_org(tenant, email, password)
        new_password = "new.password$$"

        r = self.uc.post(useradm.URL_PASSWORD_RESET_START, body={"email": email})
        assert r.status_code == 202
        # wait for the password reset email
        message = None
        for i in range(15):
            messages = smtp_server.filtered_messages(email)
            if len(messages) > 0:
                message = messages[0]
                break
            time.sleep(1)
        # be sure we received the email
        assert message is not None
        assert message.data != ""
        # extract the secret hash from the link
        match = re.search(
            r"https://hosted.mender.io/ui/password/([a-z0-9\-]+)",
            message.data.decode("utf-8"),
        )
        secret_hash = match.group(1)
        assert secret_hash != ""
        # reset the password
        r = self.uc.post(
            useradm.URL_PASSWORD_RESET_COMPLETE,
            body={"secret_hash": secret_hash, "password": new_password},
        )
        assert r.status_code == 202
        # try to login using the new password
        r = self.uc.call("POST", useradm.URL_LOGIN, auth=(email, new_password))
        assert r.status_code == 200
        assert bool(r.text)

    def test_password_reset_non_existent_email(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_PASSWORD_RESET_START,
            body={"email": "this.email.does.not.exist@mender.io"},
        )
        assert r.status_code == 202

    def test_password_reset_empty_email(self, clean_mongo):
        r = self.uc.post(useradm.URL_PASSWORD_RESET_START, body={"email": ""})
        assert r.status_code == 400

    def test_password_reset_invalid_body(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_PASSWORD_RESET_START, body={"email": ["email@mender.io"]}
        )
        assert r.status_code == 400

    def test_password_reset_complete_invalid_secret(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_PASSWORD_RESET_COMPLETE,
            body={"secret_hash": "dummy", "password": "newe password"},
        )
        assert r.status_code == 400

    def test_password_reset_complete_invalid_body(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_PASSWORD_RESET_COMPLETE,
            body={"secret_hash": ["dummy"], "password": "newe password"},
        )
        assert r.status_code == 400
