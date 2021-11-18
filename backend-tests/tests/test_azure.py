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

import pytest
import logging

from testutils.api import azure
import testutils.api.useradm as useradm
from testutils.api.client import ApiClient

from testutils.common import (
    Authset,
    create_org,
    create_user,
    clean_mongo,
    mongo_cleanup,
    mongo,
)


def create_tenant_test_setup(user_name, tenant_name, password, plan="enterprise"):
    """
    Creates a tenant, and a user belonging to the tenant
    """
    tenant = create_org(tenant_name, user_name, password, plan=plan)
    user = tenant.users[0]
    r = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert r.status_code == 200
    user.utoken = r.text
    tenant.users = [user]
    return tenant


def create_user_test_setup(user_name, password):
    """
    Creates a a user
    """
    user = create_user(user_name, password)
    useradmm = ApiClient(useradm.URL_MGMT)
    # log in user
    r = useradmm.call("POST", useradm.URL_LOGIN, auth=(user.name, user.pwd))
    assert r.status_code == 200
    user.utoken = r.text
    return user


class _TestAzureBase:
    azure_api = ApiClient(base_url=azure.URL_MGMT, host=azure.HOST, schema="http://")

    def save_settings(self, user, settings):
        r = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("PUT", azure.URL_SETTINGS, settings)
        )
        return r

    def get_settings(self, user):
        r = (
            self.azure_api.with_auth(user.utoken)
            .with_header("Content-Type", "application/json")
            .call("GET", azure.URL_SETTINGS)
        )
        return r


class TestAzureSettingsEnterprise(_TestAzureBase):
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    def test_get_and_set(self, clean_mongo):
        """
        Check that we can set and get settings
        """
        self.logger.info("creating tenant and user")
        t = create_tenant_test_setup(
            "azureuser0@mender.io", "t0", "somepassword10101010"
        )

        for expected_settings in [
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=OldKey"
            },
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=NewKey"
            },
        ]:
            r = super().save_settings(t.users[0], expected_settings)
            assert r.status_code == 204
            self.logger.info("saved settings")

            self.logger.info("getting settings")
            r = super().get_settings(t.users[0])
            assert r.status_code == 200
            self.logger.info("got settings: %s" % r.text)
            r_json = r.json()
            assert "connection_string" in r_json.keys()
            actual = r_json["connection_string"]
            # Check for equality by parts:
            # Check that actual properties are a subset of expected settings
            for part in actual.split(";"):
                assert part in expected_settings["connection_string"]
            # Check that expected properties are a subset of actual settings
            for part in expected_settings["connection_string"].split(";"):
                assert part in actual


class TestAzureSettings(_TestAzureBase):
    @property
    def logger(self):
        return logging.getLogger(self.__class__.__name__)

    def test_get_and_set(self, clean_mongo):
        """
        Check that we can set and get settings
        """
        self.logger.info("creating tenant and user")
        u = create_user_test_setup("azureuser0@mender.io", "somepassword10101010")

        for expected_settings in [
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=OldKey"
            },
            {
                "connection_string": "HostName=localhost;SharedAccessKey=thisIsBase64;SharedAccessKeyName=NewKey"
            },
        ]:
            r = super().save_settings(u, expected_settings)
            assert r.status_code == 204
            self.logger.info("saved settings")

            self.logger.info("getting settings")
            r = super().get_settings(u)
            assert r.status_code == 200
            self.logger.info("got settings: %s" % r.text)
            r_json = r.json()
            assert "connection_string" in r_json.keys()
            actual = r_json["connection_string"]
            # Check for equality by parts:
            # Check that actual properties are a subset of expected settings
            for part in actual.split(";"):
                assert part in expected_settings["connection_string"]
            # Check that expected properties are a subset of actual settings
            for part in expected_settings["connection_string"].split(";"):
                assert part in actual
