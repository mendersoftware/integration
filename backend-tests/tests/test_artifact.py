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

import os
import random
import re
import requests
import string
import subprocess
import tempfile
import pytest

from contextlib import contextmanager

from testutils.api.client import ApiClient
from testutils.api import (
    deployments,
    useradm,
    deviceauth as deviceauth_v1,
)
from testutils.common import create_org, mongo, clean_mongo, get_mender_artifact

from .test_deployments import make_accepted_device


class TestUploadArtifactEnterprise:
    def get_auth_token(self, username, password):
        r = ApiClient(useradm.URL_MGMT).call(
            "POST", useradm.URL_LOGIN, auth=(username, password)
        )
        assert r.status_code == 200
        assert r.text is not None
        assert r.text != ""

        return r.text

    def get_tenant_username_and_password(self, plan):
        tenant, username, password = (
            "test.mender.io",
            "some.user@example.com",
            "secretsecret",
        )
        tenant = create_org(tenant, username, password, plan)
        return tenant, username, password

    @pytest.mark.parametrize("plan", ["os", "professional", "enterprise"])
    def test_upload_artifact_depends_provides_valid(self, mongo, clean_mongo, plan):
        tenant, username, password = self.get_tenant_username_and_password(plan=plan)
        auth_token = self.get_auth_token(username, password)

        api_client = ApiClient(deployments.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(auth_token)

        # create and upload the mender artifact
        with get_mender_artifact(
            artifact_name="test",
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
        }

    def test_upload_artifact_depends_conflicting(self, mongo, clean_mongo):
        tenant, username, password = self.get_tenant_username_and_password(plan="os")
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
            print(artifact_kw)
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
        devauthd = ApiClient(deviceauth_v1.URL_DEVICES)
        dev = make_accepted_device(auth_token, devauthd, tenant.tenant_token)
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

    def test_upload_artifact_selection_no_match(self, mongo, clean_mongo):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs_image_checksum:checksum",),
                    "provides": ("rootfs_image_checksum:provided",),
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
                    "depends": ("rootfs_image_checksum:checksum",),
                    "provides": ("rootfs_image_checksum:provided",),
                },
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs_image_checksum:another-checksum",),
                    "provides": ("rootfs_image_checksum:provided",),
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
                "rootfs_image_checksum": "wrong-checksum",
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
                    "depends": ("rootfs_image_checksum:checksum",),
                    "provides": ("rootfs_image_checksum:provided",),
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
                "rootfs_image_checksum": "checksum",
            },
        )
        assert r.status_code == 200

    def test_upload_artifact_selection_already_installed(self, mongo, clean_mongo):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs_image_checksum:another-checksum",),
                    "provides": ("rootfs_image_checksum:provided",),
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
                "rootfs_image_checksum": "checksum",
            },
        )
        assert r.status_code == 204

    def test_upload_artifact_selection_match_depends_multiple_artifacts(
        self, mongo, clean_mongo
    ):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs_image_checksum:checksum",),
                    "provides": ("rootfs_image_checksum:provided",),
                },
                {
                    "artifact_name": "test",
                    "device_types": ["arm1"],
                    "depends": ("rootfs_image_checksum:another-checksum",),
                    "provides": ("rootfs_image_checksum:provided",),
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
                "rootfs_image_checksum": "another-checksum",
            },
        )
        assert r.status_code == 200

    def test_upload_artifact_selection_match_depends_multiple_artifacts_smallest_size(
        self, mongo, clean_mongo
    ):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {"artifact_name": "test", "device_types": ["arm2"], "size": 1024,},
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

    def test_upload_artifact_selection_match_depends_multiple_artifacts_smallest_size_wrong_depends(
        self, mongo, clean_mongo
    ):
        dev = self.setup_upload_artifact_selection(
            plan="enterprise",
            artifacts=(
                {"artifact_name": "test", "device_types": ["arm2"], "size": 1024,},
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
                "rootfs_image_checksum": "another-checksum",
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

    @pytest.mark.parametrize("plan", ["os", "professional"])
    def test_provides_depends_ignored_in_lower_plans(self, mongo, clean_mongo, plan):
        dev = self.setup_upload_artifact_selection(
            plan=plan,
            artifacts=(
                {"artifact_name": "test", "device_types": ["arm1"], "size": 256,},
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
