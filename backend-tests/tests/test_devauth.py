# Copyright 2020 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
import pytest
import base64
import json

import testutils.api.useradm as useradm
from testutils.api.client import ApiClient
import testutils.api.deviceauth as deviceauth_v1
import testutils.api.deviceauth_v2 as deviceauth_v2

from common import mongo, clean_mongo, create_org, make_accepted_device, Tenant


dauthd = ApiClient(deviceauth_v1.URL_DEVICES)
dauthm = ApiClient(deviceauth_v2.URL_MGMT)


def make_tenant_and_accepted_dev(name, uname, plan):
    tenant = create_org(name, uname, "correcthorse", plan=plan)
    user = tenant.users[0]
    tenant.users = [user]

    r = ApiClient(useradm.URL_MGMT).call(
        "POST", useradm.URL_LOGIN, auth=(user.name, user.pwd)
    )
    assert r.status_code == 200
    utok = r.text

    dev = make_accepted_device(dauthd, dauthm, utok, tenant.tenant_token)

    tenant.devices = [dev]
    tenant.plan = plan

    return tenant


@pytest.fixture(scope="function")
def tenants_and_accepted_devs(clean_mongo):
    tos = make_tenant_and_accepted_dev("tenant-os", "user@tenant-os.com", "os")

    tpro = make_tenant_and_accepted_dev(
        "tenant-pro", "user@tenant-pro.com", "professional"
    )

    tent = make_tenant_and_accepted_dev(
        "tenant-ent", "user@tenant-ent.com", "enterprise"
    )

    return [tos, tpro, tent]


class TestAuthReqEnterprise:
    def test_ok(self, tenants_and_accepted_devs):
        """ Basic JWT inspection: are we getting the right claims?
        """
        for t in tenants_and_accepted_devs:
            dev = t.devices[0]
            aset = dev.authsets[0]

            body, sighdr = deviceauth_v1.auth_req(
                aset.id_data, aset.pubkey, aset.privkey, t.tenant_token
            )

            r = dauthd.call("POST", deviceauth_v1.URL_AUTH_REQS, body, headers=sighdr)

            assert r.status_code == 200
            token = r.text

            payload = token.split(".")[1]
            payload = base64.b64decode(payload + "==")
            payload = json.loads(payload.decode("utf-8"))

            # standard claims
            assert payload["sub"] == dev.id
            assert payload["iss"] == "Mender"
            assert payload["jti"] is not None
            assert payload["exp"] is not None

            # custom claims
            assert payload["mender.plan"] == t.plan
            assert payload["mender.tenant"] == t.id
            assert payload["mender.device"]
