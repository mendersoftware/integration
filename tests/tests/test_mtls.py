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

import json
import os.path
import pytest
import shutil
import tempfile
import time

from testutils.common import create_org
from testutils.infra.container_manager import factory
from testutils.infra.device import MenderDevice

from .. import conftest
from ..MenderAPI import reset_mender_api, auth, deploy, devauth, logger
from .common_artifact import get_script_artifact
from .mendertesting import MenderTesting

container_factory = factory.get_factory()


@pytest.fixture(scope="function")
def setup_ent_mtls(request):
    env = container_factory.getMTLSSetup()
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


class TestClientMTLSEnterprise:
    def hsm_setup(self, pin, ssl_engine_id, device):
        algorithm = "rsa"
        key = f"/var/lib/mender/client.1.{algorithm}.key"
        script = f"""\
#!/bin/bash
echo "module: /usr/lib/softhsm/libsofthsm2.so" > /usr/share/p11-kit/modules/softhsm2.module
mkdir -p /softhsm/tokens
echo "directories.tokendir = /softhsm/tokens" > /softhsm/softhsm2.conf
export SOFTHSM2_CONF=/softhsm/softhsm2.conf;
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

    def hsm_get_key_uri(self, pin, ssl_engine_id, device):
        key_uri = device.run(
            "export SOFTHSM2_CONF=/softhsm/softhsm2.conf; p11tool --login --provider=/usr/lib/softhsm/libsofthsm2.so --set-pin="
            + pin
            + " --list-all-privkeys | grep URL | sed -e 's/.*URL: //'"
        ).rstrip("\n")
        key_uri = key_uri + ";pin-value=" + pin
        device.run("cp /etc/ssl/openssl.cnf /etc/ssl/openssl.cnf.backup")
        device.run(
            'echo -ne "[openssl_init]\nengines=engine_section\n\n[engine_section]\npkcs11 = pkcs11_section\n\n[pkcs11_section]\nengine_id = '
            + ssl_engine_id
            + '\nMODULE_PATH = /usr/lib/softhsm/libsofthsm2.so\ninit = 0\n" >> /etc/ssl/openssl.cnf'
        )
        device.run(
            'sed -i.backup -e "/\\[Service\\]/ a Environment=SOFTHSM2_CONF=/softhsm/softhsm2.conf" /lib/systemd/system/mender-client.service'
        )
        return key_uri

    def hsm_cleanup(self, device):
        device.run(
            "mv /lib/systemd/system/mender-client.service.backup /lib/systemd/system/mender-client.service"
        )
        device.run("rm -Rf /softhsm")
        device.run("mv /etc/ssl/openssl.cnf.backup /etc/ssl/openssl.cnf")

    def common_test_mtls_enterprise(
        self, setup_ent_mtls, algorithm=None, use_hsm=False
    ):
        tenant = setup_ent_mtls.tenant

        # stop the api gateway
        setup_ent_mtls.stop_api_gateway()

        # start a new mender client
        setup_ent_mtls.new_mtls_client("mender-client", tenant.tenant_token)

        # stop the Mender client
        setup_ent_mtls.device = device = MenderDevice(
            setup_ent_mtls.get_mender_clients()[0]
        )
        device.ssh_is_opened()

        # upload the certificates
        basedir = os.path.join(os.path.dirname(__file__), "..", "..",)
        certs = os.path.join(basedir, "extra", "mtls", "certs",)

        device.put(
            "tenant.ca.crt",
            local_path=os.path.join(certs, "tenant-ca"),
            remote_path="/etc/ssl/certs",
        )
        device.run("update-ca-certificates")

        device.put(
            "server.crt",
            local_path=os.path.join(certs, "server"),
            remote_path="/etc/mender",
        )
        device.put(
            "cert.crt",
            local_path=os.path.join(basedir, "certs", "storage-proxy"),
            remote_path="/etc/mender",
        )
        device.run(
            "cat /etc/mender/server.crt /etc/mender/cert.crt > /tmp/server.crt && mv /tmp/server.crt /etc/mender/server.crt && rm /etc/mender/cert.crt"
        )
        if algorithm is not None:
            device.put(
                f"client.1.{algorithm}.crt",
                local_path=os.path.join(certs, "client"),
                remote_path="/var/lib/mender",
            )
            device.put(
                f"client.1.{algorithm}.key",
                local_path=os.path.join(certs, "client"),
                remote_path="/var/lib/mender",
            )

        device.run("systemctl stop mender-client")
        tmpdir = tempfile.mkdtemp()

        ssl_engine_id = "pkcs11"
        pin = "0001"
        if algorithm is not None and use_hsm is True:
            self.hsm_setup(pin, ssl_engine_id, device)
            key_uri = self.hsm_get_key_uri(pin, ssl_engine_id, device)

        try:
            # retrieve the original configuration file
            output = device.run("cat /etc/mender/mender.conf")
            config = json.loads(output)
            # replace mender.conf with an mTLS enabled one
            config["ServerURL"] = "https://mtls-ambassador:8080"
            config["ServerCertificate"] = "/etc/mender/server.crt"
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
            device.put(
                os.path.basename(mender_conf),
                local_path=os.path.dirname(mender_conf),
                remote_path="/etc/mender",
            )
        finally:
            shutil.rmtree(tmpdir)

        device.run("systemctl daemon-reload")
        # start the api gateway
        setup_ent_mtls.start_api_gateway()

        logger.info("starting the client.")
        # start the Mender client
        device.run("systemctl start mender-client")
        return device

    @MenderTesting.fast
    @pytest.mark.parametrize("algorithm", ["rsa", "ec256", "ed25519"])
    def test_mtls_enterprise(self, setup_ent_mtls, algorithm):
        # set up the mTLS test environment and return the device
        device = self.common_test_mtls_enterprise(setup_ent_mtls, algorithm)

        # prepare a test artifact
        with tempfile.NamedTemporaryFile() as tf:
            artifact = make_script_artifact(
                "mtls-artifact", conftest.machine_name, tf.name
            )
            deploy.upload_image(artifact)

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
        out = device.run(
            "export SOFTHSM2_CONF=/softhsm/softhsm2.conf; mender -show-artifact"
        ).strip()
        assert out == "mtls-artifact"

    @MenderTesting.fast
    @pytest.mark.parametrize("algorithm", ["rsa"])
    def test_mtls_enterprise_hsm(self, setup_ent_mtls, algorithm):
        try:
            # set up the mTLS test environment and return the device
            device = self.common_test_mtls_enterprise(setup_ent_mtls, algorithm, True)

            output = device.run(
                "journalctl -u %s | cat" % device.get_client_service_name()
            )
            assert "ded private key: '" in output

            # prepare a test artifact
            with tempfile.NamedTemporaryFile() as tf:
                artifact = make_script_artifact(
                    "mtls-artifact", conftest.machine_name, tf.name
                )
                deploy.upload_image(artifact)

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
            out = device.run(
                "export SOFTHSM2_CONF=/softhsm/softhsm2.conf; mender -show-artifact"
            ).strip()
            assert out == "mtls-artifact"
        finally:
            self.hsm_cleanup(device)

    @MenderTesting.fast
    def test_mtls_enterprise_without_client_cert(self, setup_ent_mtls):
        # set up the mTLS test environment, without providing client certs
        self.common_test_mtls_enterprise(setup_ent_mtls, algorithm=None)

        # wait 30 seconds
        time.sleep(30)

        # no device shows up, because mTLS doesn't forward requests to the backend
        devauth.get_devices(expected_devices=0)
