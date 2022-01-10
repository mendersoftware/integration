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

from testutils.common import clean_mongo, create_org, mongo


class TestVerifyEmailEnterprise:

    uc = ApiClient(useradm.URL_MGMT)

    def test_verify_email(self, clean_mongo, smtp_server):
        uuidv4 = str(uuid.uuid4())
        tenant, email, password = (
            "test.mender.io-" + uuidv4,
            "ci.email.tests+" + uuidv4 + "@mender.io",
            "secretsecret",
        )
        create_org(tenant, email, password)

        # login and try to enable two factor authentication
        # it shouldn't be possible since the user email address
        # has not been verified
        r = self.uc.call("POST", useradm.URL_LOGIN, auth=(email, password))
        assert r.status_code == 200
        utoken = r.text

        r = self.uc.with_auth(utoken).call(
            "POST", useradm.URL_2FA_ENABLE, path_params={"id": "me"}
        )
        assert r.status_code == 403

        # verify user email address
        r = self.uc.post(useradm.URL_VERIFY_EMAIL_START, body={"email": email})
        assert r.status_code == 202
        # wait for the verification email
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
            r"https://hosted.mender.io/ui/#/activate/([a-z0-9\-]+)",
            message.data.decode("utf-8"),
        )
        secret_hash = match.group(1)
        assert secret_hash != ""
        # complete the email address
        r = self.uc.post(
            useradm.URL_VERIFY_EMAIL_COMPLETE, body={"secret_hash": secret_hash}
        )
        assert r.status_code == 204

        # try to enable two factor authentication after email address verification
        # now it should be possible
        r = self.uc.with_auth(utoken).call(
            "POST", useradm.URL_SETTINGS, body={"2fa": "enabled"}
        )
        assert r.status_code == 201

    def test_verify_email_non_existent_email(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_VERIFY_EMAIL_START,
            body={"email": "this.email.does.not.exist@mender.io"},
        )
        assert r.status_code == 202

    def test_verify_email_empty_email(self, clean_mongo):
        r = self.uc.post(useradm.URL_VERIFY_EMAIL_START, body={"email": ""})
        assert r.status_code == 400

    def test_verify_email_invalid_body(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_VERIFY_EMAIL_START, body={"email": ["email@mender.io"]}
        )
        assert r.status_code == 400

    def test_verify_email_complete_invalid_secret(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_VERIFY_EMAIL_COMPLETE, body={"secret_hash": "dummy"}
        )
        assert r.status_code == 400

    def test_verify_email_complete_invalid_body(self, clean_mongo):
        r = self.uc.post(
            useradm.URL_VERIFY_EMAIL_COMPLETE, body={"secret_hash": ["dummy"]}
        )
        assert r.status_code == 400
