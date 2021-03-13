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

import hashlib
import io
import os
import os.path
import requests
import pytest
import urllib.parse

from tempfile import NamedTemporaryFile

from ..common_setup import standard_setup_one_client
from ..MenderAPI import (
    authentication,
    devauth,
    get_container_manager,
)
from .common_connect import wait_for_connect
from .mendertesting import MenderTesting


def download_file(path, devid, authtoken):
    deviceconnect_url = (
        "https://%s/api/management/v1/deviceconnect"
        % get_container_manager().get_mender_gateway()
    )
    download_url = "%s/devices/%s/download" % (deviceconnect_url, devid)
    download_url_with_path = download_url + "?path=" + urllib.parse.quote(path)
    return requests.get(download_url_with_path, verify=False, headers=authtoken)


def upload_file(path, file, devid, authtoken, mode="600", uid="0", gid="0"):
    files = (
        ("path", (None, path)),
        ("mode", (None, mode)),
        ("uid", (None, uid)),
        ("gid", (None, gid)),
        ("file", (os.path.basename(path), file, "application/octet-stream"),),
    )
    deviceconnect_url = (
        "https://%s/api/management/v1/deviceconnect"
        % get_container_manager().get_mender_gateway()
    )
    upload_url = "%s/devices/%s/upload" % (deviceconnect_url, devid)
    return requests.put(upload_url, verify=False, headers=authtoken, files=files)


def md5sum(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


@pytest.mark.usefixtures("standard_setup_one_client")
class TestFileTransfer(MenderTesting):
    """Tests the file transfer functionality"""

    def test_filetransfer(self, standard_setup_one_client):
        """Tests the file transfer features
        """
        # accept the device
        devauth.accept_devices(1)

        # list of devices
        devices = list(
            set([device["id"] for device in devauth.get_devices_status("accepted")])
        )
        assert 1 == len(devices)

        # wait for the device to connect via websocket
        auth = authentication.Authentication()
        wait_for_connect(auth, devices[0])

        # device ID and auth token
        devid = devices[0]
        authtoken = auth.get_auth_token()

        # download a file and check its content
        path = "/etc/mender/mender.conf"
        r = download_file(path, devid, authtoken)
        assert r.status_code == 200, r.json()
        assert "ServerURL" in str(r.content)
        assert (
            r.headers.get("Content-Disposition") == 'attachment; filename="mender.conf"'
        )
        assert r.headers.get("Content-Type") == "application/octet-stream"
        assert r.headers.get("X-Men-File-Gid") == "0"
        assert r.headers.get("X-Men-File-Uid") == "0"
        assert r.headers.get("X-Men-File-Mode") == "600"
        assert r.headers.get("X-Men-File-Path") == "/etc/mender/mender.conf"
        assert r.headers.get("X-Men-File-Size") != ""

        # wrong request, path is relative
        path = "relative/path"
        r = download_file(path, devid, authtoken)
        assert r.status_code == 400, r.json()
        assert r.json().get("error") == "bad request: path: must be absolute."

        # wrong request, no such file or directory
        path = "/does/not/exist"
        r = download_file(path, devid, authtoken)
        assert r.status_code == 400, r.json()
        assert "/does/not/exist: no such file or directory" in r.json().get("error")

        try:
            # create a 40MB random file
            f = NamedTemporaryFile(delete=False)
            for i in range(40 * 1024):
                f.write(os.urandom(1024))
            f.close()

            # upload the file
            r = upload_file(
                "/tmp/random.bin",
                open(f.name, "rb"),
                devid,
                authtoken,
                mode="600",
                uid="0",
                gid="0",
            )
            assert r.status_code == 201, r.json()

            # download the file
            path = "/tmp/random.bin"
            r = download_file(path, devid, authtoken)
            assert r.status_code == 200, r.json()
            assert (
                r.headers.get("Content-Disposition")
                == 'attachment; filename="random.bin"'
            )
            assert r.headers.get("Content-Type") == "application/octet-stream"
            assert r.headers.get("X-Men-File-Gid") == "0"
            assert r.headers.get("X-Men-File-Uid") == "0"
            assert r.headers.get("X-Men-File-Mode") == "600"
            assert r.headers.get("X-Men-File-Path") == "/tmp/random.bin"
            assert r.headers.get("X-Men-File-Size") != ""

            filename_download = f.name + ".download"
            with open(filename_download, "wb") as fw:
                fw.write(r.content)

            # verify the file is not corrupted
            assert md5sum(filename_download) == md5sum(f.name)
        finally:
            os.unlink(f.name)
            if os.path.isfile(f.name + ".download"):
                os.unlink(f.name + ".download")

        # wrong request, path is relative
        r = upload_file(
            "relative/path/dummy.txt",
            io.StringIO("dummy"),
            devid,
            authtoken,
            mode="600",
            uid="0",
            gid="0",
        )
        assert r.status_code == 400, r.json()
        assert r.json().get("error") == "bad request: path: must be absolute."

        # wrong request, cannot write the file
        r = upload_file(
            "/does/not/exist/dummy.txt",
            io.StringIO("dummy"),
            devid,
            authtoken,
            mode="600",
            uid="0",
            gid="0",
        )
        assert r.status_code == 400, r.json()
        assert "failed to create target file" in r.json().get("error")
