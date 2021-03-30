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

import redo

import testutils.api.deviceconnect as deviceconnect

from testutils.api.client import ApiClient
from ..MenderAPI import (
    get_container_manager,
    logger,
)


def wait_for_connect(auth, devid):
    devconn = ApiClient(
        host=get_container_manager().get_mender_gateway(),
        base_url=deviceconnect.URL_MGMT,
    )

    for _ in redo.retrier(attempts=60, sleeptime=1):
        logger.info("waiting for device in deviceconnect")
        res = devconn.call(
            "GET",
            deviceconnect.URL_MGMT_DEVICE,
            headers=auth.get_auth_token(),
            path_params={"id": devid},
        )
        if res.status_code == 200 and res.json()["status"] == "connected":
            break
    else:
        assert False, "timed out waiting for /connect"
