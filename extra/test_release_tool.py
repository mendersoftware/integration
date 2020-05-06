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
import sys
import shutil
import re
from unittest.mock import patch

import pytest

from release_tool import main
from release_tool import docker_compose_files_list

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RELEASE_TOOL = os.path.join(THIS_DIR, "release_tool.py")
INTEGRATION_DIR = os.path.normpath(os.path.join(THIS_DIR, ".."))


@pytest.fixture(scope="function", autouse=True)
def master_yml_files(request):
    """Edit all yml files setting them to 'master' versions

    So that the tests can be run from any branch or with any
    local changes in the yml files. The files are restored after
    the test run.
    """

    for filename in docker_compose_files_list(INTEGRATION_DIR):
        shutil.copyfile(filename, filename + ".bkp")

        with open(filename) as fd:
            full_content = "".join(fd.readlines())
        with open(filename, "w") as fd:
            fd.write(
                re.sub(
                    r"image:\s+(mendersoftware|.*mender\.io)/(.+):.*",
                    r"image: \g<1>/\g<2>:master",
                    full_content,
                )
            )
        with open(filename) as fd:
            full_content = "".join(fd.readlines())
        with open(filename, "w") as fd:
            fd.write(
                re.sub(
                    r"git-version:\s+.*",
                    r"git-version: master",
                    full_content,
                    flags=re.MULTILINE,
                )
            )

    def restore():
        for filename in docker_compose_files_list(INTEGRATION_DIR):
            os.rename(filename + ".bkp", filename)

    request.addfinalizer(restore)


def run_main_assert_result(capsys, args, expect=""):
    testargs = [RELEASE_TOOL] + args
    with patch.object(sys, "argv", testargs):
        main()

    captured = capsys.readouterr().out.strip()
    assert captured == expect


def test_version_of(capsys):
    # On a clean checkout, both will be master
    run_main_assert_result(capsys, ["--version-of", "inventory"], "master")
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "docker"], "master"
    )
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "git"], "master"
    )

    # For an independent component, it should still accept docker/git type of the query
    run_main_assert_result(capsys, ["--version-of", "mender"], "master")
    run_main_assert_result(
        capsys, ["--version-of", "mender", "--version-type", "docker"], "master"
    )
    run_main_assert_result(
        capsys, ["--version-of", "mender", "--version-type", "git"], "master"
    )
    run_main_assert_result(capsys, ["--version-of", "mender-client-qemu"], "master")
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-client-qemu", "--version-type", "docker"],
        "master",
    )
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-client-qemu", "--version-type", "git"],
        "master",
    )

    # Manually modifying the Git version:
    filename = os.path.join(INTEGRATION_DIR, "git-versions.yml")
    with open(filename, "w") as fd:
        fd.write(
            """services:
    inventory:
        git-version: 1.2.3-git
"""
        )
    run_main_assert_result(capsys, ["--version-of", "inventory"], "1.2.3-git")
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "docker"], "master"
    )
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "git"], "1.2.3-git"
    )

    # Manually modifying the Docker version:
    filename = os.path.join(INTEGRATION_DIR, "docker-compose.yml")
    with open(filename, "w") as fd:
        fd.write(
            """services:
    mender-inventory:
        image: mendersoftware/inventory:4.5.6-docker
"""
        )
    run_main_assert_result(capsys, ["--version-of", "inventory"], "1.2.3-git")
    run_main_assert_result(
        capsys,
        ["--version-of", "inventory", "--version-type", "docker"],
        "4.5.6-docker",
    )
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "git"], "1.2.3-git"
    )


def test_set_version_of(capsys):

    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "docker"], "master"
    )
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "git"], "master"
    )

    # Using --set-version-of modifies both versions, regardless of using the repo name
    run_main_assert_result(
        capsys, ["--set-version-of", "inventory", "--version", "1.2.3-test"]
    )
    run_main_assert_result(capsys, ["--version-of", "inventory"], "1.2.3-test")
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "docker"], "1.2.3-test"
    )
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "git"], "1.2.3-test"
    )

    # or the container name. However, setting from the container name sets all repos (os + ent)
    run_main_assert_result(
        capsys, ["--set-version-of", "mender-deployments", "--version", "4.5.6-test"]
    )
    run_main_assert_result(capsys, ["--version-of", "mender-deployments"], "4.5.6-test")
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-deployments", "--version-type", "docker"],
        "4.5.6-test",
    )
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-deployments", "--version-type", "git"],
        "4.5.6-test",
    )
    run_main_assert_result(capsys, ["--version-of", "deployments"], "4.5.6-test")
    run_main_assert_result(
        capsys,
        ["--version-of", "deployments", "--version-type", "docker"],
        "4.5.6-test",
    )
    run_main_assert_result(
        capsys, ["--version-of", "deployments", "--version-type", "git"], "4.5.6-test"
    )
    run_main_assert_result(
        capsys, ["--version-of", "deployments-enterprise"], "4.5.6-test"
    )
    run_main_assert_result(
        capsys,
        ["--version-of", "deployments-enterprise", "--version-type", "docker"],
        "4.5.6-test",
    )
    run_main_assert_result(
        capsys,
        ["--version-of", "deployments-enterprise", "--version-type", "git"],
        "4.5.6-test",
    )

    # For old releases, --version-type shall be ignored
    run_main_assert_result(
        capsys,
        ["--version-of", "inventory", "--in-integration-version", "2.3.0"],
        "1.7.0",
    )
    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "inventory",
            "--version-type",
            "git",
            "--in-integration-version",
            "2.3.0",
        ],
        "1.7.0",
    )
    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "inventory",
            "--version-type",
            "docker",
            "--in-integration-version",
            "2.3.0",
        ],
        "1.7.0",
    )
