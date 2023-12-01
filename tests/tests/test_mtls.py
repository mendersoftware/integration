# Copyright 2023 Northern.tech AS
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
import os.path
import pytest
import re
import shutil
import tempfile
import time

from testutils.common import create_org
from testutils.infra.container_manager import factory
from testutils.infra.container_manager.kubernetes_manager import isK8S
from testutils.infra.device import MenderDevice

from .. import conftest
from ..MenderAPI import reset_mender_api, auth, deploy, devauth, logger
from .common_artifact import get_script_artifact
from .mendertesting import MenderTesting

container_factory = factory.get_factory()


@pytest.fixture(scope="function")
def setup_ent_mtls(request):
    env = container_factory.get_mtls_setup()
    request.addfinalizer(env.teardown)
    env.setup()

    mtls_username = "mtls@mender.io"
    mtls_password = "correcthorsebatterystaple"

    env.tenant = create_org(
        "Mender",
        mtls_username,
        mtls_password,
        containers_namespace=env.name,
        container_manager=env,
    )
    env.user = env.tenant.users[0]
    env.start_mtls_ambassador()

    reset_mender_api(env)

    auth.username = mtls_username
    auth.password = mtls_password
    auth.multitenancy = True
    auth.current_tenant = env.tenant

    env.stop_api_gateway()

    # start a new mender client
    env.new_mtls_client("mender-client", env.tenant.tenant_token)
    env.device = MenderDevice(env.get_mender_clients()[0])
    env.device.ssh_is_opened()

    return env


def make_script_artifact(artifact_name, device_type, output_path):
    script = b"""\
#! /bin/bash

set -xe

# Just give it a little bit of time
sleep 6s

# Successful update
exit 0
"""
    return get_script_artifact(script, artifact_name, device_type, output_path)


@pytest.mark.skipif(
    isK8S(), reason="not relevant in a staging or production environment"
)
class TestClientMTLSEnterprise:
    wait_for_device_timeout_seconds = 64

    def hsm_setup(self, pin, ssl_engine_id, device):
        algorithm = "rsa"
        key = f"/var/lib/mender/client.1.{algorithm}.key"
        script = f"""\
#!/bin/bash
echo "module: /usr/lib/softhsm/libsofthsm2.so" > /usr/share/p11-kit/modules/softhsm2.module
softhsm2-util --init-token --free --label unittoken1 --pin {pin} --so-pin 0002
pkcs11-tool --module /usr/lib/softhsm/libsofthsm2.so --login --pin {pin} --write-object "{key}" --type privkey --id 0909 --label privatekey
"""
        tmpdir = tempfile.mkdtemp()
        initialize_hsm_script = os.path.join(tmpdir, "init-hsm.sh")
        try:
            with open(initialize_hsm_script, "w") as fd:
                fd.write(script)
            device.put(
                os.path.basename(initialize_hsm_script),
                local_path=os.path.dirname(initialize_hsm_script),
                remote_path="/tmp",
            )
            device.run("chmod 755 /tmp/" + os.path.basename(initialize_hsm_script))
            device.run("/tmp/" + os.path.basename(initialize_hsm_script))
        finally:
            shutil.rmtree(tmpdir)

    def setup_openssl_conf(hsm_implementation):
        device.run("cp /etc/ssl/openssl.cnf /etc/ssl/openssl.cnf.backup")
        if hsm_implementation == "engine":
            conf = f"""
            [openssl_init]
            engines = engine_section

            [engine_section]
            pkcs11 = pkcs11_section

            [pkcs11_section]
            engine_id = {ssl_engine_id}
            """

            device.run(f"echo -ne {conf} >> /etc/ssl/openssl.cnf")
        elif hsm_implementation == "provider":
            conf = """
            [openssl_init]
            providers = provider_sect

            [provider_sect]
            default = default_sect
            pkcs11 = pkcs11_sect

            [pkcs11_sect]
            activate = 1
            module = /usr/lib/ossl-modules/pkcs11.so
            """
            device.run(f"echo -ne {conf} >> /etc/ssl/openssl.cnf")

    def hsm_get_key_uri(self, pin, ssl_engine_id, device):
        pt11tool_output = device.run(
            "p11tool --login --provider=/usr/lib/softhsm/libsofthsm2.so --set-pin="
            + pin
            + " --list-all-privkeys"
        ).rstrip("\n")
        key_uri = re.search(r"URL:\s(.*)", pt11tool_output).group(1)
        key_uri = key_uri + ";pin-value=" + pin

        return key_uri

    def hsm_cleanup(self, device):
        device.run("mv /etc/ssl/openssl.cnf.backup /etc/ssl/openssl.cnf || true")

    def common_test_mtls_enterprise(self, env, algorithm=None, use_hsm=False):
        # upload the certificates
        basedir = os.path.join(os.path.dirname(__file__), "..", "..",)
        certs = os.path.join(basedir, "extra", "mtls", "certs",)

        env.device.put(
            "tenant.ca.crt",
            local_path=os.path.join(certs, "tenant-ca"),
            remote_path="/etc/ssl/certs",
        )
        env.device.run("update-ca-certificates")

        if algorithm is not None:
            env.device.put(
                f"client.1.{algorithm}.crt",
                local_path=os.path.join(certs, "client"),
                remote_path="/var/lib/mender",
            )
            env.device.put(
                f"client.1.{algorithm}.key",
                local_path=os.path.join(certs, "client"),
                remote_path="/var/lib/mender",
            )

        env.device.run("systemctl stop mender-authd")
        tmpdir = tempfile.mkdtemp()

        ssl_engine_id = "pkcs11"
        pin = "0001"
        if algorithm is not None and use_hsm is True:
            self.hsm_setup(pin, ssl_engine_id, env.device)
            key_uri = self.hsm_get_key_uri(pin, ssl_engine_id, env.device)

        try:
            # retrieve the original configuration file
            output = env.device.run("cat /etc/mender/mender.conf")
            config = json.loads(output)
            # replace mender.conf with an mTLS enabled one
            config["ServerURL"] = "https://mtls-ambassador:8080"
            config["SkipVerify"] = True
            if algorithm is not None:
                if use_hsm is True:
                    config["HttpsClient"] = {
                        "SSLEngine": ssl_engine_id,
                        "Certificate": f"/var/lib/mender/client.1.{algorithm}.crt",
                        "Key": key_uri,
                    }
                    logger.info('client key set to "%s"' % key_uri)
                else:
                    config["HttpsClient"] = {
                        "Certificate": f"/var/lib/mender/client.1.{algorithm}.crt",
                        "Key": f"/var/lib/mender/client.1.{algorithm}.key",
                    }
            if "ArtifactVerifyKey" in config:
                del config["ArtifactVerifyKey"]
            mender_conf = os.path.join(tmpdir, "mender.conf")
            with open(mender_conf, "w") as fd:
                json.dump(config, fd)
            env.device.put(
                os.path.basename(mender_conf),
                local_path=os.path.dirname(mender_conf),
                remote_path="/etc/mender",
            )
        finally:
            shutil.rmtree(tmpdir)

        # start the api gateway
        env.start_api_gateway()

        # start the Mender client
        logger.info("starting the client.")
        env.device.run("systemctl daemon-reload")
        env.device.run("systemctl start mender-authd")

    @MenderTesting.fast
    @pytest.mark.parametrize("algorithm", ["rsa", "ec256", "ed25519"])
    def test_mtls_enterprise(self, setup_ent_mtls, algorithm):

        self.common_test_mtls_enterprise(setup_ent_mtls, algorithm, use_hsm=False)

        # prepare a test artifact
        with tempfile.NamedTemporaryFile() as tf:
            artifact = make_script_artifact(
                "mtls-artifact", conftest.machine_name, tf.name
            )
            deploy.upload_image(artifact)

        for device in devauth.get_devices_status("pending"):
            devauth.decommission(device["id"])

        i = self.wait_for_device_timeout_seconds
        while i > 0:
            i = i - 1
            time.sleep(1)
            devices = list(
                set([device["id"] for device in devauth.get_devices_status("accepted")])
            )
            if len(devices) > 0:
                break

        # deploy the update to the device
        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert len(devices) == 1
        deployment_id = deploy.trigger_deployment(
            "mtls-test", artifact_name="mtls-artifact", devices=devices,
        )

        # now just wait for the update to succeed
        deploy.check_expected_statistics(deployment_id, "success", 1)
        deploy.check_expected_status("finished", deployment_id)

        # verify the update was actually installed on the device
        out = setup_ent_mtls.device.run("mender show-artifact").strip()
        assert out == "mtls-artifact"

    @MenderTesting.fast
    @pytest.mark.parametrize("algorithm", ["rsa"])
    @pytest.mark.parametrize("hsm_implementation", ["engine", "provider"])
    def test_mtls_enterprise_hsm(self, setup_ent_mtls, algorithm, hsm_implementation):
        # Check if the client has has SoftHSM (from yocto dunfell forward)
        output = setup_ent_mtls.device.run(
            "test -e /usr/lib/softhsm/libsofthsm2.so && echo true", hide=True
        )
        if output.rstrip() != "true":
            pytest.fail("Needs SoftHSM to run this test")

        setup_openssl_conf(hsm_implementation)

        try:
            self.common_test_mtls_enterprise(setup_ent_mtls, algorithm, use_hsm=True)

            output = setup_ent_mtls.device.run("journalctl --unit mender-authd | cat")
            assert "Successfully loaded private key from pkcs11" in output

            # prepare a test artifact
            with tempfile.NamedTemporaryFile() as tf:
                artifact = make_script_artifact(
                    "mtls-artifact", conftest.machine_name, tf.name
                )
                assert "loaded private key: '" in output

                # prepare a test artifact
                with tempfile.NamedTemporaryFile() as tf:
                    artifact = make_script_artifact(
                        "mtls-artifact", conftest.machine_name, tf.name
                    )
                    deploy.upload_image(artifact)

                for device in devauth.get_devices_status("pending"):
                    devauth.decommission(device["id"])

                i = self.wait_for_device_timeout_seconds
                while i > 0:
                    i = i - 1
                    time.sleep(1)
                    devices = list(
                        set(
                            [
                                device["id"]
                                for device in devauth.get_devices_status("accepted")
                            ]
                        )
                    )
                    if len(devices) > 0:
                        break

                # deploy the update to the device
                devices = list(
                    set(
                        [
                            device["id"]
                            for device in devauth.get_devices_status("accepted")
                        ]
                    )
                )
                assert len(devices) == 1
                deployment_id = deploy.trigger_deployment(
                    "mtls-test", artifact_name="mtls-artifact", devices=devices,
                )

                # now just wait for the update to succeed
                deploy.check_expected_statistics(deployment_id, "success", 1)
                deploy.check_expected_status("finished", deployment_id)

                # verify the update was actually installed on the device
                out = setup_ent_mtls.device.run("mender show-artifact").strip()
                assert out == "mtls-artifact"
        finally:
            self.hsm_cleanup(setup_ent_mtls.device)

    @MenderTesting.fast
    def test_mtls_enterprise_without_client_cert(self, setup_ent_mtls):
        # set up the mTLS test environment, without providing client certs
        self.common_test_mtls_enterprise(setup_ent_mtls, algorithm=None, use_hsm=False)

        # in here it also may happen, that the client is started earlier, and device registers
        # as pending. in that case get_devices_status which is called from get_devices will
        # loop until it runs out of iterations, due to the fact that we expect to have 0 devices.
        # to prevent this from happening, lets wait a bit, if the device shows as pending,
        # if it does, decommission it, and then restart the client, and wait to be sure the
        # device will not re-appear, which is the main idea of the test.
        device_not_present_timeout_seconds = 30
        for device in devauth.get_devices_status(
            "pending", max_wait=device_not_present_timeout_seconds * 0.5, no_assert=True
        ):
            devauth.decommission(device["id"])

        setup_ent_mtls.device.run("systemctl start mender-authd")

        # wait device_not_present_timeout_seconds
        time.sleep(device_not_present_timeout_seconds)

        # no device shows up, because mTLS doesn't forward requests to the backend
        devauth.get_devices(expected_devices=0)
