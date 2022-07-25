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
#

import json
import redo
import uuid

import testutils.api.deviceconnect as deviceconnect
from testutils.common import User, update_tenant, new_tenant_client
from testutils.infra.cli import CliTenantadm

from testutils.api.client import ApiClient
from ..MenderAPI import (
    authentication,
    get_container_manager,
    logger,
    DeviceAuthV2,
)


def prepare_env_for_connect(env):
    uuidv4 = str(uuid.uuid4())
    tname = "test.mender.io-{}".format(uuidv4)
    email = "some.user+{}@example.com".format(uuidv4)
    u = User("", email, "whatsupdoc")
    cli = CliTenantadm(containers_namespace=env.name)
    tid = cli.create_org(tname, u.name, u.pwd, plan="os")

    # FT requires "troubleshoot"
    update_tenant(
        tid, addons=["troubleshoot"], container_manager=get_container_manager(),
    )

    tenant = cli.get_tenant(tid)
    tenant = json.loads(tenant)
    env.tenant = tenant

    auth = authentication.Authentication(
        name="os-tenant", username=u.name, password=u.pwd
    )
    auth.create_org = False
    auth.reset_auth_token()
    devauth_tenant = DeviceAuthV2(auth)

    mender_device = new_tenant_client(env, "mender-client", tenant["tenant_token"])
    mender_device.ssh_is_opened()

    devauth_tenant.accept_devices(1)

    devices = devauth_tenant.get_devices_status("accepted")
    assert 1 == len(devices)

    devid = devices[0]["id"]
    authtoken = auth.get_auth_token()

    wait_for_connect(auth, devid)

    return devid, authtoken, auth, mender_device


def wait_for_connect(auth, devid):
    devconn = ApiClient(
        host=get_container_manager().get_mender_gateway(),
        base_url=deviceconnect.URL_MGMT,
    )

    connected = 0
    for _ in redo.retrier(attempts=12, sleeptime=5):
        logger.info("waiting for device in deviceconnect")
        res = devconn.call(
            "GET",
            deviceconnect.URL_MGMT_DEVICE,
            headers=auth.get_auth_token(),
            path_params={"id": devid},
        )
        if not (res.status_code == 200 and res.json()["status"] == "connected"):
            connected = 0
            continue
        connected += 1
        if connected >= 2:
            break
    else:
        assert False, "timed out waiting for /connect"
