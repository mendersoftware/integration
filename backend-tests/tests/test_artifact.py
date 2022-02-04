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

import os
import pytest
import re
import requests
import subprocess
import tempfile
import uuid

from testutils.api.client import ApiClient
from testutils.api import (
    deployments,
    useradm,
    deviceauth,
)
from testutils.common import (
    create_org,
    create_user,
    mongo,
    clean_mongo,
    get_mender_artifact,
    make_accepted_device,
)


class TestUploadArtifactBase:
    def get_auth_token(self, username, password):
        r = ApiClient(useradm.URL_MGMT).call(
            "POST", useradm.URL_LOGIN, auth=(username, password)
        )
        assert r.status_code == 200
        assert r.text is not None
        assert r.text != ""

        return r.text

    def setup_upload_artifact_selection(self, plan, artifacts=()):
        tenant, username, password = self.get_tenant_username_and_password(plan=plan)
        auth_token = self.get_auth_token(username, password)

        api_client = ApiClient(deployments.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(auth_token)

        # create and upload the mender artifact
        for artifact_kw in artifacts:
            artifact_kw.setdefault("artifact_name", "test")
            artifact_kw.setdefault("device_types", ["arm1"])
            with get_mender_artifact(**artifact_kw) as artifact:
                r = api_client.with_auth(auth_token).call(
                    "POST",
                    deployments.URL_DEPLOYMENTS_ARTIFACTS,
                    files=(
                        ("description", (None, "description")),
                        ("size", (None, str(os.path.getsize(artifact)))),
                        (
                            "artifact",
                            (
                                artifact,
                                open(artifact, "rb"),
                                "application/octet-stream",
                            ),
                        ),
                    ),
                )
            assert r.status_code == 201

        # create a new accepted device
        devauthd = ApiClient(deviceauth.URL_DEVICES)
        devauthm = ApiClient(deviceauth.URL_MGMT)
        dev = make_accepted_device(
            devauthd,
            devauthm,
            auth_token,
            tenant.tenant_token if tenant is not None else "",
        )
        assert dev is not None

        # create a deployment
        resp = api_client.with_auth(auth_token).call(
            "POST",
            deployments.URL_DEPLOYMENTS,
            body={
                "name": "deployment-1",
                "artifact_name": "test",
                "devices": [dev.id],
            },
        )
        assert resp.status_code == 201

        return dev

    def do_test_upload_artifact_selection_already_installed(self):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs-image.checksum:another-checksum",),
                    "provides": ("rootfs-image.checksum:provided",),
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm1",
                "artifact_name": "test",
                "rootfs-image.checksum": "checksum",
            },
        )
        assert r.status_code == 204

    def do_test_upload_artifact_selection_match_depends_multiple_artifacts(self):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs-image.checksum:checksum",),
                    "provides": ("rootfs-image.checksum:provided",),
                },
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs-image.checksum:another-checksum",),
                    "provides": ("rootfs-image.checksum:provided",),
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm1",
                "artifact_name": "old-artifact",
                "rootfs-image.checksum": "another-checksum",
            },
        )
        assert r.status_code == 200

    def do_test_upload_artifact_selection_match_depends_multiple_artifacts_smallest_size(
        self,
    ):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {"artifact_name": "test", "device_types": ["arm2"], "size": 1024},
                {
                    "artifact_name": "test",
                    "device_types": ["arm2"],
                    "depends": ("vcdiff:xdelta",),
                    "size": 256,
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm2",
                "artifact_name": "old-artifact",
                "vcdiff": "xdelta",
            },
        )
        assert r.status_code == 200
        #
        data = r.json()
        r = requests.get(data["artifact"]["source"]["uri"], verify=False)
        assert r.status_code == 200

        f = tempfile.NamedTemporaryFile(delete=False)
        try:
            f.write(r.content)
            f.close()
            #
            p = subprocess.Popen(
                ["mender-artifact", "read", f.name], stdout=subprocess.PIPE
            )
            stdout = p.stdout.read().decode("utf-8")
            m_size = re.search(r".*size: *([0-9]+).*", stdout, re.M | re.I)
            assert m_size is not None
            size = int(m_size.group(1))
            assert size == 256
        finally:
            os.unlink(f.name)


class TestUploadArtifactEnterprise(TestUploadArtifactBase):
    def get_tenant_username_and_password(self, plan):
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, plan)
        return tenant, username, password

    def test_upload_artifact_depends_conflicting(self, mongo, clean_mongo):
        _, username, password = self.get_tenant_username_and_password(plan="os")
        auth_token = self.get_auth_token(username, password)

        api_client = ApiClient(deployments.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(auth_token)

        # create and upload the mender artifact
        with get_mender_artifact(
            artifact_name="test",
            device_types=["arm1", "arm2"],
            depends=("key1:value1", "key2:value2"),
            provides=("key3:value3", "key4:value4", "key5:value5"),
        ) as artifact:
            r = api_client.with_auth(auth_token).call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS,
                files=(
                    ("description", (None, "description")),
                    ("size", (None, str(os.path.getsize(artifact)))),
                    (
                        "artifact",
                        (artifact, open(artifact, "rb"), "application/octet-stream"),
                    ),
                ),
            )
        assert r.status_code == 201

        # create and upload a conflicting mender artifact
        # conflict because (arm2 / key:value1 / key:value2) are duplicated
        with get_mender_artifact(
            artifact_name="test",
            device_types=["arm2", "arm3"],
            depends=("key1:value1", "key2:value2"),
            provides=("key3:value3", "key4:value4", "key5:value5"),
        ) as artifact:
            r = api_client.with_auth(auth_token).call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS,
                files=(
                    ("description", (None, "description")),
                    ("size", (None, str(os.path.getsize(artifact)))),
                    (
                        "artifact",
                        (artifact, open(artifact, "rb"), "application/octet-stream"),
                    ),
                ),
            )
        assert r.status_code == 409

        # create and upload a non-conflicting mender artifact
        with get_mender_artifact(
            artifact_name="test",
            device_types=["arm4"],
            depends=("key1:value1", "key2:value2"),
            provides=("key3:value3", "key4:value4", "key5:value5"),
        ) as artifact:
            r = api_client.with_auth(auth_token).call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS,
                files=(
                    ("description", (None, "description")),
                    ("size", (None, str(os.path.getsize(artifact)))),
                    (
                        "artifact",
                        (artifact, open(artifact, "rb"), "application/octet-stream"),
                    ),
                ),
            )
        assert r.status_code == 201

    def test_upload_artifact_selection_no_match(self, mongo, clean_mongo):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs-image.checksum:checksum",),
                    "provides": ("rootfs-image.checksum:provided",),
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={"device_type": "arm1", "artifact_name": "old-artifact"},
        )
        assert r.status_code == 204

    def test_upload_artifact_selection_no_match_wrong_depends(self, mongo, clean_mongo):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs-image.checksum:checksum",),
                    "provides": ("rootfs-image.checksum:provided",),
                },
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs-image.checksum:another-checksum",),
                    "provides": ("rootfs-image.checksum:provided",),
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm1",
                "artifact_name": "old-artifact",
                "rootfs-image.checksum": "wrong-checksum",
            },
        )
        assert r.status_code == 204

    def test_upload_artifact_selection_match_depends(self, mongo, clean_mongo):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs-image.checksum:checksum",),
                    "provides": ("rootfs-image.checksum:provided",),
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm1",
                "artifact_name": "old-artifact",
                "rootfs-image.checksum": "checksum",
            },
        )
        assert r.status_code == 200

    def test_upload_artifact_selection_already_installed(self, mongo, clean_mongo):
        self.do_test_upload_artifact_selection_already_installed()

    def test_upload_artifact_selection_match_depends_multiple_artifacts(
        self, mongo, clean_mongo
    ):
        self.do_test_upload_artifact_selection_match_depends_multiple_artifacts()

    def test_upload_artifact_selection_match_depends_multiple_artifacts_smallest_size(
        self, mongo, clean_mongo
    ):
        self.do_test_upload_artifact_selection_match_depends_multiple_artifacts_smallest_size()

    def test_upload_artifact_selection_match_depends_multiple_artifacts_smallest_size_wrong_depends(
        self, mongo, clean_mongo
    ):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {"artifact_name": "test", "device_types": ["arm2"], "size": 1024},
                {
                    "artifact_name": "test",
                    "device_types": ["arm2"],
                    "depends": ("vcdiff:xdelta",),
                    "size": 256,
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm2",
                "artifact_name": "old-artifact",
                "rootfs-image.checksum": "another-checksum",
            },
        )
        assert r.status_code == 200
        #
        data = r.json()
        r = requests.get(data["artifact"]["source"]["uri"], verify=False)
        assert r.status_code == 200

        f = tempfile.NamedTemporaryFile(delete=False)
        try:
            f.write(r.content)
            f.close()
            #
            p = subprocess.Popen(
                ["mender-artifact", "read", f.name], stdout=subprocess.PIPE
            )
            stdout = p.stdout.read().decode("utf-8")
            m_size = re.search(r".*size: *([0-9]+).*", stdout, re.M | re.I)
            assert m_size is not None
            size = int(m_size.group(1))
            assert size == 1024
        finally:
            os.unlink(f.name)

    @pytest.mark.parametrize("plan", ["os", "professional", "enterprise"])
    def test_upload_artifact_depends_provides_valid(self, mongo, clean_mongo, plan):
        _, username, password = self.get_tenant_username_and_password(plan=plan)
        auth_token = self.get_auth_token(username, password)

        api_client = ApiClient(deployments.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(auth_token)

        # create and upload the mender artifact
        with get_mender_artifact(
            artifact_name="test",
            update_module="dummy",
            device_types=["arm1"],
            depends=("key1:value1", "key2:value2"),
            provides=("key3:value3", "key4:value4", "key5:value5"),
        ) as artifact:
            r = api_client.with_auth(auth_token).call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS,
                files=(
                    ("description", (None, "description")),
                    ("size", (None, str(os.path.getsize(artifact)))),
                    (
                        "artifact",
                        (artifact, open(artifact, "rb"), "application/octet-stream"),
                    ),
                ),
            )
        assert r.status_code == 201

        # extract the artifact id from the Location header
        artifact_id = r.headers.get("Location", "").rsplit("/", 1)[-1]
        assert artifact_id != ""

        # get the artifact details from the API
        artifact_url = deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace(
            "{id}", artifact_id
        )
        r = api_client.call("GET", artifact_url)
        assert r.status_code == 200
        artifact = r.json()

        # artifact data assertions
        assert artifact is not None
        assert artifact["description"] == "description"
        assert artifact["name"] == "test"
        assert artifact["info"] == {"format": "mender", "version": 3}
        assert artifact["signed"] is False
        assert len(artifact["updates"]) == 1
        assert artifact["size"] > 0
        assert artifact["id"] is not None
        assert artifact["modified"] is not None
        assert artifact["artifact_depends"] == {
            "device_type": ["arm1"],
            "key1": "value1",
            "key2": "value2",
        }
        assert artifact["artifact_provides"] == {
            "artifact_name": "test",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5",
            "rootfs-image.dummy.version": "test",
        }

    def test_artifacts_exclusive_to_user(self, mongo, clean_mongo):
        tenants = []
        #
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password)
        tenants.append(tenant)
        #
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password)
        tenants.append(tenant)

        api_client = ApiClient(deployments.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json

        for tenant in tenants:
            user = tenant.users[0]
            auth_token = self.get_auth_token(user.name, user.pwd)

            # create and upload the mender artifact
            tenant.test_artifact_name = user.name.translate(
                {ord(c): None for c in ".@+"}
            )
            with get_mender_artifact(
                artifact_name=tenant.test_artifact_name,
                device_types=["arm1"],
                depends=("key1:value1", "key2:value2"),
                provides=("key3:value3", "key4:value4", "key5:value5"),
            ) as artifact:
                r = api_client.with_auth(auth_token).call(
                    "POST",
                    deployments.URL_DEPLOYMENTS_ARTIFACTS,
                    files=(
                        ("description", (None, "description")),
                        ("size", (None, str(os.path.getsize(artifact)))),
                        (
                            "artifact",
                            (
                                artifact,
                                open(artifact, "rb"),
                                "application/octet-stream",
                            ),
                        ),
                    ),
                )
                assert r.status_code == 201

        for tenant in tenants:
            user = tenant.users[0]
            auth_token = self.get_auth_token(user.name, user.pwd)
            api_client.with_auth(auth_token)
            r = api_client.call(
                "GET",
                deployments.URL_DEPLOYMENTS_ARTIFACTS
                + "?name="
                + tenant.test_artifact_name,
            )
            assert r.status_code == 200
            artifacts = r.json()
            assert len(artifacts) == 1
            assert artifacts[0]["name"] == tenant.test_artifact_name

    @pytest.mark.parametrize("plan", ["os", "professional"])
    def test_provides_depends_ignored_in_lower_plans(self, mongo, clean_mongo, plan):
        dev = self.setup_upload_artifact_selection(
            plan=plan,
            artifacts=(
                {"artifact_name": "test", "device_types": ["arm1"], "size": 256},
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("foo:fooval", "bar:barval",),
                    "size": 1024,
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm1",
                "artifact_name": "old-artifact",
                "foo": "fooval",
                "bar": "barval",
            },
        )
        assert r.status_code == 200
        data = r.json()
        r = requests.get(data["artifact"]["source"]["uri"], verify=False)
        assert r.status_code == 200

        f = tempfile.NamedTemporaryFile(delete=False)
        try:
            f.write(r.content)
            f.close()
            #
            p = subprocess.Popen(
                ["mender-artifact", "read", f.name], stdout=subprocess.PIPE
            )
            stdout = p.stdout.read().decode("utf-8")
            m_size = re.search(r".*size: *([0-9]+).*", stdout, re.M | re.I)
            assert m_size is not None
            size = int(m_size.group(1))

            # if provides/depends wasn't ignored - the matching, larger
            # artifact should have been selected
            # that's not the case, and we selected 'smallest of all'
            assert size == 256
        finally:
            os.unlink(f.name)


class TestUploadArtifactOpenSource(TestUploadArtifactBase):
    def get_tenant_username_and_password(self, plan):
        _ = plan
        uuidv4 = str(uuid.uuid4())
        username, password = (
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        create_user(username, password)
        return None, username, password

    def test_upload_artifact_selection_already_installed(self, mongo, clean_mongo):
        self.do_test_upload_artifact_selection_already_installed()

    def test_upload_artifact_depends_provides_valid(self, mongo, clean_mongo):
        _, username, password = self.get_tenant_username_and_password(plan="os")
        auth_token = self.get_auth_token(username, password)

        api_client = ApiClient(deployments.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(auth_token)

        # create and upload the mender artifact
        with get_mender_artifact(
            artifact_name="test",
            update_module="dummy",
            device_types=["arm1"],
            depends=("key1:value1", "key2:value2"),
            provides=("key3:value3", "key4:value4", "key5:value5"),
        ) as artifact:
            r = api_client.with_auth(auth_token).call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS,
                files=(
                    ("description", (None, "description")),
                    ("size", (None, str(os.path.getsize(artifact)))),
                    (
                        "artifact",
                        (artifact, open(artifact, "rb"), "application/octet-stream"),
                    ),
                ),
            )
        assert r.status_code == 201

        # extract the artifact id from the Location header
        artifact_id = r.headers.get("Location", "").rsplit("/", 1)[-1]
        assert artifact_id != ""

        # get the artifact details from the API
        artifact_url = deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace(
            "{id}", artifact_id
        )
        r = api_client.call("GET", artifact_url)
        assert r.status_code == 200
        artifact = r.json()

        # artifact data assertions
        assert artifact is not None
        assert artifact["description"] == "description"
        assert artifact["name"] == "test"
        assert artifact["info"] == {"format": "mender", "version": 3}
        assert artifact["signed"] is False
        assert len(artifact["updates"]) == 1
        assert artifact["size"] > 0
        assert artifact["id"] is not None
        assert artifact["modified"] is not None
        assert artifact["artifact_depends"] == {
            "device_type": ["arm1"],
            "key1": "value1",
            "key2": "value2",
        }
        assert artifact["artifact_provides"] == {
            "artifact_name": "test",
            "key3": "value3",
            "key4": "value4",
            "key5": "value5",
            "rootfs-image.dummy.version": "test",
        }

    def test_provides_depends_ignored_in_open_source(self, mongo, clean_mongo):
        dev = self.setup_upload_artifact_selection(
            plan="os",
            artifacts=(
                {"artifact_name": "test", "device_types": ["arm1"], "size": 256},
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("foo:fooval", "bar:barval",),
                    "size": 1024,
                },
            ),
        )
        deploymentsd = ApiClient(deployments.URL_DEVICES)
        r = deploymentsd.with_auth(dev.token).call(
            "POST",
            deployments.URL_NEXT,
            body={
                "device_type": "arm1",
                "artifact_name": "old-artifact",
                "foo": "fooval",
                "bar": "barval",
            },
        )
        assert r.status_code == 200
        data = r.json()
        r = requests.get(data["artifact"]["source"]["uri"], verify=False)
        assert r.status_code == 200

        f = tempfile.NamedTemporaryFile(delete=False)
        try:
            f.write(r.content)
            f.close()
            #
            p = subprocess.Popen(
                ["mender-artifact", "read", f.name], stdout=subprocess.PIPE
            )
            stdout = p.stdout.read().decode("utf-8")
            m_size = re.search(r".*size: *([0-9]+).*", stdout, re.M | re.I)
            assert m_size is not None
            size = int(m_size.group(1))

            # if provides/depends wasn't ignored - the matching, larger
            # artifact should have been selected
            # that's not the case, and we selected 'smallest of all'
            assert size == 256
        finally:
            os.unlink(f.name)
