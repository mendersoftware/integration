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

import json
import os
import pytest
import tempfile
import uuid

from .. import conftest
from ..common_setup import enterprise_no_client
from ..MenderAPI import logger, Authentication, DeviceAuthV2, Deployments
from testutils.infra.cli import CliTenantadm
from testutils.common import Tenant, User, new_tenant_client
from .common_artifact import get_script_artifact
from .mendertesting import MenderTesting


def make_script_artifact(artifact_name, device_type, output_path):
    script = b"""\
#! /bin/bash

set -xe

# Just give it a little bit of time
sleep 6s

touch /tmp/retry-attempts
attempts=$(cat /tmp/retry-attempts)
attempts=$((attempts+1))

# Increment the retry count
echo "$attempts" > /tmp/retry-attempts

if [[ $attempts -lt 3 ]]; then
    exit 1
fi

# Successful update after three attempts
exit 0
"""
    return get_script_artifact(script, artifact_name, device_type, output_path)


@pytest.mark.skip(reason="FIXME: QA-817")
@pytest.mark.usefixtures("enterprise_no_client")
class TestDeploymentRetryEnterprise(MenderTesting):
    """Tests the retry deployment functionality"""

    @MenderTesting.fast
    def test_deployment_retry_failed_update(self, enterprise_no_client):
        """Tests that a client installing a deployment created with a retry limit

        This is done through setting up a new tenant on the enterprise plan,
        with a device bootstrapped to the tenant. Then an Artifact is created
        which contains a script, for the script update module. The script will
        store a retry-count in a temp-file on the device, and fail, as long as
        the retry-count < 3. On the third go, the script will, pass, and along
        with it, so should the update.

        """

        env = enterprise_no_client

        # Create an enterprise plan tenant
        uuidv4 = str(uuid.uuid4())
        tname = "test.mender.io-{}".format(uuidv4)
        email = "some.user+{}@example.com".format(uuidv4)
        u = User("", email, "whatsupdoc")
        cli = CliTenantadm(containers_namespace=env.name)
        tid = cli.create_org(tname, u.name, u.pwd, plan="enterprise")
        tenant = cli.get_tenant(tid)
        tenant = json.loads(tenant)
        ttoken = tenant["tenant_token"]
        logger.info(f"tenant json: {tenant}")
        tenant = Tenant("tenant", tid, ttoken)
        tenant.users.append(u)

        # And authorize the user to the tenant account
        auth = Authentication(name="enterprise-tenant", username=u.name, password=u.pwd)
        auth.create_org = False
        auth.reset_auth_token()
        devauth = DeviceAuthV2(auth)
        deploy = Deployments(auth, devauth)

        # Add a client to the tenant
        device = new_tenant_client(
            enterprise_no_client, "mender-client", tenant.tenant_token
        )
        devauth.accept_devices(1)

        with tempfile.NamedTemporaryFile() as tf:

            artifact = make_script_artifact(
                "retry-artifact", conftest.machine_name, tf.name
            )

            deploy.upload_image(artifact)

            devices = list(
                set([device["id"] for device in devauth.get_devices_status("accepted")])
            )
            assert len(devices) == 1

            deployment_id = deploy.trigger_deployment(
                "retry-test", artifact_name="retry-artifact", devices=devices, retries=3
            )
            logger.info(deploy.get_deployment(deployment_id))

            # Now just wait for the update to succeed
            deploy.check_expected_statistics(deployment_id, "success", 1)
            deploy.check_expected_status("finished", deployment_id)

            # Verify the update was actually installed on the device
            out = device.run("mender-update show-artifact").strip()
            assert out == "retry-artifact"

            # Verify the number of attempts taken to install the update
            out = device.run("cat /tmp/retry-attempts").strip()
            assert out == "3"
