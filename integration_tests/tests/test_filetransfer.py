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
#

import json
import io
import os
import os.path
import random
import requests
import shutil
import tempfile
import pytest
import time
import urllib.parse
import random

from flaky import flaky

from tempfile import NamedTemporaryFile

from integration_tests.common_setup import (
    standard_setup_one_client,
    enterprise_no_client_class,
    class_persistent_standard_setup_one_client_bootstrapped,
)

from integration_tests.MenderAPI import (
    auth,
    authentication,
    get_container_manager,
    reset_mender_api,
    logger,
    devauth,
)
from integration_tests.tests.common_connect import prepare_env_for_connect, wait_for_connect
from integration_tests.tests.common import md5sum
from integration_tests.tests.mendertesting import MenderTesting
from integration_testutils.infra.container_manager import factory
from integration_testutils.infra.device import MenderDevice


container_factory = factory.get_factory()
connect_service_name = "mender-connect"


def random_filename():
    return "".join(random.choices([chr(c) for c in range(97, 123)], k=8))


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


def set_limits(mender_device, limits, auth, devid):
    tmpdir = tempfile.mkdtemp()
    try:
        # retrieve the original configuration file
        output = mender_device.run("cat /etc/mender/mender-connect.conf")
        config = json.loads(output)
        # update mender-connect.conf setting the file transfer limits
        config["Limits"] = limits
        mender_connect_conf = os.path.join(tmpdir, "mender-connect.conf")
        with open(mender_connect_conf, "w") as fd:
            json.dump(config, fd)
        mender_device.run(
            "cp /etc/mender/mender-connect.conf /etc/mender/mender-connect.conf-backup-`ls /etc/mender/mender-connect.* | wc -l`"
        )
        mender_device.put(
            os.path.basename(mender_connect_conf),
            local_path=os.path.dirname(mender_connect_conf),
            remote_path="/etc/mender",
        )
    finally:
        shutil.rmtree(tmpdir)
    mender_device.run("systemctl restart %s" % connect_service_name)
    wait_for_connect(auth, devid)
    debugoutput = mender_device.run("cat /etc/mender/mender-connect.conf")
    logger.info("/etc/mender/mender-connect.conf:\n%s" % debugoutput)
    debugoutput = mender_device.run("ls -al /etc/mender")
    logger.info("ls -al /etc/mender/:\n%s" % debugoutput)


class BaseTestFileTransferDownload(MenderTesting):
    def test_download_ok(self, mender_device_setup, content_assertion=None):
        # download a file and check its content
        path = "/etc/mender/mender.conf"
        r = download_file(path, self.devid, self.auth_token)

        assert r.status_code == 200, r.json()
        if content_assertion:
            assert content_assertion in str(r.content)
        assert (
            r.headers.get("Content-Disposition")
            == 'attachment; filename="' + os.path.basename(path) + '"'
        )
        assert r.headers.get("Content-Type") == "application/octet-stream"
        assert r.headers.get("X-Men-File-Gid") == "0"
        assert r.headers.get("X-Men-File-Uid") == "0"
        assert r.headers.get("X-Men-File-Mode") == "600"
        assert r.headers.get("X-Men-File-Path") == "/etc/mender/mender.conf"
        assert r.headers.get("X-Men-File-Size") != ""

    def test_download_error_relative_path(self, mender_device_setup):

        # wrong request, path is relative
        r = download_file("relative/path", self.devid, self.auth_token)
        assert r.status_code == 400, r.json()
        assert r.json().get("error") == "bad request: path: must be absolute."

    def test_upload_error_no_such_file_or_directory(self, mender_device_setup):

        # wrong request, no such file or directory
        path = "/does/not/exist"
        r = download_file(path, self.devid, self.auth_token)
        assert r.status_code == 400, r.json()
        assert "/does/not/exist: no such file or directory" in r.json().get("error")

    def test_upload_and_download_ok(self, mender_device_setup):

        try:
            # create a 40MB random file
            f = NamedTemporaryFile(delete=False)
            for i in range(40 * 1024):
                f.write(os.urandom(1024))
            f.close()

            uid = random.randint(100, 200)
            gid = random.randint(100, 200)

            fname = random_filename()
            path = f"/tmp/{fname}"
            r = upload_file(
                path,
                open(f.name, "rb"),
                self.devid,
                self.auth_token,
                mode="600",
                uid=str(uid),
                gid=str(gid),
            )
            assert r.status_code == 201, r.json()

            # download the file
            r = download_file(path, self.devid, self.auth_token)
            assert r.status_code == 200, r.json()
            assert (
                r.headers.get("Content-Disposition")
                == f'attachment; filename="{fname}"'
            )
            assert r.headers.get("Content-Type") == "application/octet-stream"
            assert r.headers.get("X-Men-File-Mode") == "600"
            assert r.headers.get("X-Men-File-Uid") == str(uid)
            assert r.headers.get("X-Men-File-Gid") == str(gid)
            assert r.headers.get("X-Men-File-Path") == f"/tmp/{fname}"
            assert r.headers.get("X-Men-File-Size") == str(40 * 1024 * 1024)

            filename_download = f.name + ".download"
            with open(filename_download, "wb") as fw:
                fw.write(r.content)

            # verify the file is not corrupted
            assert md5sum(filename_download) == md5sum(f.name)
        finally:
            os.unlink(f.name)
            if os.path.isfile(f.name + ".download"):
                os.unlink(f.name + ".download")

    def test_upload_error_path_is_relative(
        self, mender_device_setup,
    ):

        # wrong request, path is relative
        r = upload_file(
            "relative/path/dummy.txt",
            io.StringIO("dummy"),
            self.devid,
            self.auth_token,
            mode="600",
            uid="0",
            gid="0",
        )
        assert r.status_code == 400, r.json()
        assert r.json().get("error") == "bad request: path: must be absolute."

    def test_upload_error_file_does_not_exist(self, mender_device_setup):

        r = upload_file(
            "/does/not/exist/dummy.txt",
            io.StringIO("dummy"),
            self.devid,
            self.auth_token,
            mode="600",
            uid="0",
            gid="0",
        )
        assert r.status_code == 400, r.json()
        assert "failed to create target file" in r.json().get("error")


class BaseTestFileTransferLimits(MenderTesting):
    def test_upload_limits_err_file_outside_chroot(self, mender_device_setup):
        "File Transfer limits: file outside chroot; upload forbidden"

        set_limits(
            self.mender_device,
            {
                "Enabled": True,
                "FileTransfer": {"Chroot": "/var/lib/mender/filetransfer"},
            },
            self.auth,
            self.devid,
        )
        self.mender_device.run("mkdir -p /var/lib/mender/filetransfer")

        f = NamedTemporaryFile(delete=False)
        for i in range(40 * 1024):
            f.write(os.urandom(1024))
        f.close()

        fname = random_filename()
        r = upload_file(
            f"/usr/{fname}", open(f.name, "rb"), self.devid, self.auth_token,
        )

        assert r.status_code == 400, r.json()
        assert (
            r.json().get("error")
            == "access denied: the target file path is outside chroot"
        )

    def test_upload_limits_ok(self, mender_device_setup):
        "File Transfer limits: file inside chroot; upload allowed"

        set_limits(
            self.mender_device,
            {
                "Enabled": True,
                "FileTransfer": {
                    "Chroot": "/var/lib/mender/filetransfer",
                    "FollowSymLinks": True,  # in the image /var/lib/mender is a symlink
                },
            },
            self.auth,
            self.devid,
        )
        self.mender_device.run("mkdir -p /var/lib/mender/filetransfer")

        f = NamedTemporaryFile(delete=False)
        f.write(os.urandom(16))
        f.close()

        fname = random_filename()
        r = upload_file(
            f"/var/lib/mender/filetransfer/{fname}",
            open(f.name, "rb"),
            self.devid,
            self.auth_token,
        )

        assert r.status_code == 201

    def test_upload_limits_err_file_too_big(self, mender_device_setup):
        "File Transfer limits: file size over the limit; upload forbidden"
        set_limits(
            self.mender_device,
            {
                "Enabled": True,
                "FileTransfer": {"MaxFileSize": 15 * 1024, "FollowSymLinks": True},
            },
            self.auth,
            self.devid,
        )

        f = NamedTemporaryFile(delete=False)
        for i in range(128 * 1024):
            f.write(b"ok")
        f.close()

        fname = random_filename()
        r = upload_file(
            f"/tmp/{fname}", open(f.name, "rb"), self.devid, self.auth_token,
        )

        assert r.status_code == 400, r.json()
        assert (
            r.json().get("error")
            == "failed to write file chunk: transmitted bytes limit exhausted"
        )

    def test_upload_limits_err_max_bytes_per_minute_exceeded(self, mender_device_setup):
        "File Transfer limits: transfers during last minute over the limit; upload forbidden"
        set_limits(
            self.mender_device,
            {
                "Enabled": True,
                "FileTransfer": {
                    "FollowSymLinks": True,
                    "Counters": {"MaxBytesRxPerMinute": 16 * 1024},
                },
            },
            self.auth,
            self.devid,
        )

        f = NamedTemporaryFile(delete=False)
        for i in range(256 * 1024):
            f.write(b"ok")
        f.close()

        fname = random_filename()
        upload_file(
            f"/tmp/{fname}-0.bin", open(f.name, "rb"), self.devid, self.auth_token,
        )
        upload_file(
            f"/tmp/{fname}-1.bin", open(f.name, "rb"), self.devid, self.auth_token,
        )
        logger.info("-- testcase: File Transfer limits: sleeping to gather the avg")

        time.sleep(60)  # wait for mender-connect to calculate the 1m exp moving avg
        self.mender_device.run(
            "kill -USR1 `pidof mender-connect`"
        )  # USR1 makes mender-connect print status

        r = upload_file(
            f"/tmp/{fname}-2.bin", open(f.name, "rb"), self.devid, self.auth_token
        )

        assert r.status_code == 400, r.json()
        assert r.json().get("error") == "transmitted bytes limit exhausted"

        logger.info(
            "-- testcase: File Transfer limits: transfers during last minute: test_filetransfer_limits_upload sleeping 64s to be able to transfer again"
        )
        # let's rest some more and increase the limit and try again
        time.sleep(64)
        self.mender_device.run(
            "kill -USR1 `pidof mender-connect`"
        )  # USR1 makes mender-connect print status

        logger.info(
            "-- testcase: File Transfer limits: transfers during last minute below the limit; upload allowed"
        )
        f = NamedTemporaryFile(delete=False)
        for i in range(64):
            f.write(b"ok")
        f.close()
        # upload a file
        r = upload_file(
            f"/tmp/{fname}-a.bin", open(f.name, "rb"), self.devid, self.auth_token,
        )
        self.mender_device.run(
            "kill -USR1 `pidof mender-connect`"
        )  # USR1 makes mender-connect print status

        assert r.status_code == 201

    def test_upload_limits_err_preserve_modes(self, mender_device_setup):
        "File Transfer limits: preserve modes;"

        set_limits(
            self.mender_device,
            {
                "Enabled": True,
                "FileTransfer": {
                    "Chroot": "/var/lib/mender/filetransfer",
                    "FollowSymLinks": True,  # in the image /var/lib/mender is a symlink
                    "PreserveMode": True,
                },
            },
            self.auth,
            self.devid,
        )
        self.mender_device.run("mkdir -p /var/lib/mender/filetransfer")

        f = NamedTemporaryFile(delete=False)
        f.write(os.urandom(16))
        f.close()

        fname = random_filename()
        r = upload_file(
            f"/var/lib/mender/filetransfer/{fname}.bin",
            open(f.name, "rb"),
            self.devid,
            self.auth_token,
            mode="4711",
        )
        modes_ls = self.mender_device.run(
            f"ls -al /var/lib/mender/filetransfer/{fname}.bin"
        )
        logger.info(
            f"test_filetransfer_limits_upload ls -al /var/lib/mender/filetransfer/{fname}.bin:\n%s"
            % modes_ls
        )

        assert modes_ls.startswith("-rws--x--x")
        assert r.status_code == 201

    def test_upload_limits_preserve_owner_and_group(self, mender_device_setup):
        "File Transfer limits: preserve owner and group;"

        set_limits(
            self.mender_device,
            {
                "Enabled": True,
                "FileTransfer": {
                    "Chroot": "/var/lib/mender/filetransfer",
                    "FollowSymLinks": True,  # in the image /var/lib/mender is a symlink
                    "PreserveOwner": True,
                    "PreserveGroup": True,
                },
            },
            self.auth,
            self.devid,
        )
        self.mender_device.run("mkdir -p /var/lib/mender/filetransfer")

        f = NamedTemporaryFile(delete=False)
        f.write(os.urandom(16))
        f.close()
        gid = int(self.mender_device.run("cat /etc/group  | tail -1 | cut -f3 -d:"))
        uid = int(self.mender_device.run("cat /etc/passwd | tail -1 | cut -f3 -d:"))
        logger.info("test_filetransfer_limits_upload gid/uid %d/%d", gid, uid)
        fname = random_filename()
        r = upload_file(
            f"/var/lib/mender/filetransfer/{fname}.bin",
            open(f.name, "rb"),
            self.devid,
            self.auth_token,
            uid=str(uid),
            gid=str(gid),
        )

        owner_group = self.mender_device.run(
            f"ls -aln /var/lib/mender/filetransfer/{fname}.bin | cut -f 3,4 -d' '"
        )

        assert owner_group == str(uid) + " " + str(gid) + "\n"
        assert r.status_code == 201

    def assert_forbidden(self, rsp, message):
        try:
            assert rsp.status_code == 403
            assert rsp.json().get("error") == message
        except AssertionError as e:
            if rsp.status_code == 500:
                raise NotImplementedError(
                    "[MEN-4659] Deviceconnect should not respond with 5xx errors "
                    + "on user restriction errors"
                )
            else:
                raise e

    @pytest.mark.xfail(raises=NotImplementedError, reason="MEN-4659")
    def test_filetransfer_limits_download_err_outside_chroot(self, mender_device_setup):
        "File Transfer limits: file outside chroot; download forbidden"

        set_limits(
            self.mender_device,
            {
                "Enabled": True,
                "FileTransfer": {"Chroot": "/var/lib/mender/filetransfer"},
            },
            self.auth,
            self.devid,
        )

        path = "/etc/profile"
        r = download_file(path, self.devid, self.auth_token)

        self.assert_forbidden(
            r, "access denied: the target file path is outside chroot"
        )

    @pytest.mark.xfail(raises=NotImplementedError, reason="MEN-4659")
    def test_filetransfer_limits_download_err_max_file_size(self, mender_device_setup):
        "File Transfer limits: file over the max file size limit; download forbidden"
        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"MaxFileSize": 2}},
            self.auth,
            self.devid,
        )

        path = "/etc/profile"
        r = download_file(path, self.devid, self.auth_token)

        self.assert_forbidden(r, "access denied: the file size is over the limit")

    @pytest.mark.xfail(raises=NotImplementedError, reason="MEN-4659")
    def test_filetransfer_limits_download_err_not_allowed_to_follow_link(
        self, mender_device_setup,
    ):
        "File Transfer limits: not allowed to follow a link; download forbidden"
        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"FollowSymLinks": False}},
            self.auth,
            self.devid,
        )

        fname = random_filename()
        path = f"/tmp/{fname}-profile-link"
        self.mender_device.run("ln -s /etc/profile " + path)
        r = download_file(path, self.devid, self.auth_token)

        self.assert_forbidden(r, "access denied: forbidden to follow the link")

    @pytest.mark.xfail(raises=NotImplementedError, reason="MEN-4659")
    def test_filetransfer_limits_download_err_not_allowed_to_follow_link_on_path_part(
        self, mender_device_setup,
    ):
        "File Transfer limits: not allowed to follow a link on path part; download forbidden"

        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"FollowSymLinks": False}},
            self.auth,
            self.devid,
        )

        fname = random_filename()
        self.mender_device.run(f"cd /tmp && mkdir {fname} && cd {fname} && ln -s /etc")
        # now we have a link to the etc directory under /tmp/{fname}/etc
        path = f"/tmp/{fname}/etc/profile"
        r = download_file(path, self.devid, self.auth_token)

        self.assert_forbidden(r, "access denied: forbidden to follow the link")

    def test_filetransfer_limits_download_ok_allowed_to_follow_symlink(
        self, mender_device_setup,
    ):
        "File Transfer limits: not allowed to follow a link; download forbidden"
        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"FollowSymLinks": True}},
            self.auth,
            self.devid,
        )

        fname = random_filename() + ".symlink"
        path = f"/tmp/{fname}"
        self.mender_device.run("ln -s /etc/profile " + path)

        r = download_file(path, self.devid, self.auth_token)

        assert r.status_code == 200, r.json()
        assert "PATH" in str(r.content)

    @pytest.mark.xfail(raises=NotImplementedError, reason="MEN-4659")
    def test_filetransfer_limits_download_err_owner_mismatch(self, mender_device_setup):
        "File Transfer limits: file owner do not match; download forbidden"

        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"OwnerGet": ["someotheruser"]}},
            self.auth,
            self.devid,
        )

        path = "/etc/profile"
        r = download_file(path, self.devid, self.auth_token)

        self.assert_forbidden(r, "access denied: the file owner does not match")

    @pytest.mark.xfail(raises=NotImplementedError, reason="MEN-4659")
    def test_filetransfer_limits_download_err_group_mismatch(self, mender_device_setup):
        "File Transfer limits: file group do not match; download forbidden"

        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"GroupGet": ["someothergroup"]}},
            self.auth,
            self.devid,
        )

        path = "/etc/profile"
        r = download_file(path, self.devid, self.auth_token)

        self.assert_forbidden(r, "access denied: the file group does not match")

    def test_filetransfer_limits_download_err_not_a_regular_file(
        self, mender_device_setup
    ):
        "File Transfer limits: file not a regular file; download forbidden"
        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"RegularFilesOnly": True}},
            self.auth,
            self.devid,
        )

        fname = random_filename()
        path = f"/tmp/{fname}.fifo"
        self.mender_device.run("mkfifo " + path)
        r = download_file(path, self.devid, self.auth_token)

        assert r.status_code == 400, r.json()
        assert r.json().get("error").endswith("path is not a regular file")

    def test_filetransfer_limits_download_ok_file_owner_match(
        self, mender_device_setup
    ):
        "File Transfer limits: file owner match; download allowed"
        set_limits(
            self.mender_device,
            {"Enabled": True, "FileTransfer": {"OwnerGet": ["someotheruser", "root"]}},
            self.auth,
            self.devid,
        )

        path = "/etc/profile"
        r = download_file(path, self.devid, self.auth_token)

        assert r.status_code == 200, r.json()
        assert "PATH" in str(r.content)


def rerun_on_timeouts(err, *args):
    if not issubclass(err[0], AssertionError):
        return False
    return "408" in str(err[1])


@flaky(rerun_filter=rerun_on_timeouts)
class TestFileTransferDownloadOS(BaseTestFileTransferDownload):
    """Tests the file transfer functionality"""

    @pytest.fixture(scope="class")
    def mender_device_setup(
        self, request, class_persistent_standard_setup_one_client_bootstrapped
    ):

        env = class_persistent_standard_setup_one_client_bootstrapped

        request.cls.auth = env.auth
        request.cls.mender_device = env.device
        request.cls.auth_token = env.auth.get_auth_token()

        devices = devauth.get_devices_status("accepted")
        assert 1 == len(devices)
        request.cls.devid = devices[0]["id"]

        wait_for_connect(env.auth, request.cls.devid)

    def test_download_ok(self, mender_device_setup, content_assertion=None):
        super().test_download_ok(mender_device_setup, content_assertion="ServerURL")


@flaky(rerun_filter=rerun_on_timeouts)
class TestFileTransferDownloadEnterprise(BaseTestFileTransferDownload):
    """Tests the file transfer functionality for enterprise setup"""

    @pytest.fixture(scope="class")
    def mender_device_setup(self, request, enterprise_no_client_class):
        devid, auth_token, auth, mender_device = prepare_env_for_connect(
            enterprise_no_client_class
        )
        request.cls.devid = devid
        request.cls.auth_token = auth_token
        request.cls.auth = auth
        request.cls.mender_device = mender_device


@flaky(rerun_filter=rerun_on_timeouts)
class TestFileTransferLimitsOS(BaseTestFileTransferLimits):
    """Tests the file transfer functionality"""

    @pytest.fixture(scope="class")
    def mender_device_setup(
        self, request, class_persistent_standard_setup_one_client_bootstrapped
    ):

        env = class_persistent_standard_setup_one_client_bootstrapped

        request.cls.auth = env.auth
        request.cls.mender_device = env.device
        request.cls.auth_token = env.auth.get_auth_token()

        devices = devauth.get_devices_status("accepted")
        assert 1 == len(devices)
        request.cls.devid = devices[0]["id"]

        wait_for_connect(env.auth, request.cls.devid)


@flaky(rerun_filter=rerun_on_timeouts)
class TestFileTransferLimitsEnterprise(BaseTestFileTransferLimits):
    """Tests the file transfer functionality for enterprise setup"""

    @pytest.fixture(scope="class")
    def mender_device_setup(self, request, enterprise_no_client_class):
        devid, auth_token, auth, mender_device = prepare_env_for_connect(
            enterprise_no_client_class
        )
        request.cls.devid = devid
        request.cls.auth_token = auth_token
        request.cls.auth = auth
        request.cls.mender_device = mender_device


class BaseFileTransferLegacyClient(MenderTesting):
    def test_filetransfer_not_implemented(self, setup_mender_connect_1_0):
        """Tests the file transfer is not implemented with mender-connect 1.0"""

        env = setup_mender_connect_1_0

        rsp = upload_file("/foo/bar", io.StringIO("foobar"), env.devid, env.auth_token)
        assert rsp.status_code == 502
        rsp = download_file("/foo/bar", env.devid, env.auth_token)
        assert rsp.status_code == 502
