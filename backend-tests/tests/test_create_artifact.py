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

import os
import tempfile
import time
import uuid

from json import dumps

from testutils.api.client import ApiClient
from testutils.api import deployments, useradm
from testutils.common import create_org, create_user, mongo, clean_mongo


class TestCreateArtifactBase:
    def run_create_artifact_test(self, username, password):
        r = ApiClient(useradm.URL_MGMT).call(
            "POST", useradm.URL_LOGIN, auth=(username, password)
        )
        assert r.status_code == 200
        assert r.text is not None
        assert r.text != ""

        auth_token = r.text

        api_client = ApiClient(deployments.URL_MGMT)
        api_client.headers = {}  # avoid default Content-Type: application/json
        api_client.with_auth(auth_token)

        f = tempfile.NamedTemporaryFile(delete=False)
        try:
            f.write(b"#!/bin/bash\ntrue\n")
            f.close()

            filename = f.name

            r = api_client.call(
                "POST",
                deployments.URL_DEPLOYMENTS_ARTIFACTS_GENERATE,
                files={
                    "name": (None, "artifact"),
                    "description": (None, "description"),
                    "device_types_compatible": (None, "beaglebone"),
                    "type": (None, "single_file"),
                    "args": (
                        None,
                        dumps({"filename": "run.sh", "dest_dir": "/tests"}),
                    ),
                    "file": (
                        filename,
                        open(filename, "rb"),
                        "application/octet-stream",
                        {},
                    ),
                },
                qs_params=None,
            )
        finally:
            os.unlink(f.name)

        assert r.status_code == 201

        artifact_id = r.headers.get("Location", "").rsplit("/", 1)[-1]
        assert artifact_id != ""

        artifact_url = deployments.URL_DEPLOYMENTS_ARTIFACTS_GET.replace(
            "{id}", artifact_id
        )

        artifact = None
        for i in range(15):
            time.sleep(1)
            r = api_client.call("GET", artifact_url,)
            if r.status_code == 200:
                artifact = r.json()
                break

        assert artifact is not None
        assert artifact["description"] == "description"
        assert artifact["name"] == "artifact"
        assert artifact["info"] == {"format": "mender", "version": 3}
        assert artifact["signed"] is False
        assert len(artifact["updates"]) == 1
        assert artifact["size"] > 0
        assert artifact["id"] is not None
        assert artifact["modified"] is not None


class TestCreateArtifactEnterprise(TestCreateArtifactBase):
    def test_create_artifact(self, mongo, clean_mongo):
        uuidv4 = str(uuid.uuid4())
        tenant, username, password = (
            "test.mender.io-" + uuidv4,
            "some.user+" + uuidv4 + "@example.com",
            "secretsecret",
        )
        create_org(tenant, username, password)
        self.run_create_artifact_test(username, password)


class TestCreateArtifactOpenSource(TestCreateArtifactBase):
    def test_create_artifact(self, mongo, clean_mongo):
        uuidv4 = str(uuid.uuid4())
        username, password = ("some.user+" + uuidv4 + "@example.com", "secretsecret")
        create_user(username, password)
        self.run_create_artifact_test(username, password)
