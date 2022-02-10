# Copyright 2022 Northern.tech AS
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
    """Edit all yml files setting them to 'master'/'mender-master' versions

    So that the tests can be run from any branch or with any
    local changes in the yml files. The files are restored after
    the test run.
    """

    docker_files = docker_compose_files_list(INTEGRATION_DIR, "docker")
    for filename in docker_files:
        shutil.copyfile(filename, filename + ".bkp")
    for filename in docker_compose_files_list(INTEGRATION_DIR, "git"):
        if filename not in docker_files:
            shutil.copyfile(filename, filename + ".bkp")

    for filename in docker_files:
        with open(filename) as fd:
            full_content = "".join(fd.readlines())
        with open(filename, "w") as fd:
            fd.write(
                re.sub(
                    r"image:\s+(mendersoftware|.*mender\.io)/((?!mender\-client\-.+|mender-artifact|mender-cli).+):.*",
                    r"image: \g<1>/\g<2>:mender-master",
                    full_content,
                )
            )
        with open(filename) as fd:
            full_content = "".join(fd.readlines())
        with open(filename, "w") as fd:
            fd.write(
                re.sub(
                    r"image:\s+(mendersoftware|.*mender\.io)/(mender\-client\-.+|mender-artifact|mender-cli):.*",
                    r"image: \g<1>/\g<2>:master",
                    full_content,
                )
            )

    for filename in docker_compose_files_list(INTEGRATION_DIR, "git"):
        if filename not in docker_files:
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

    def restore():
        docker_files = docker_compose_files_list(INTEGRATION_DIR, "docker")
        for filename in docker_files:
            os.rename(filename + ".bkp", filename)
        for filename in docker_compose_files_list(INTEGRATION_DIR, "git"):
            if filename not in docker_files:
                os.rename(filename + ".bkp", filename)

    request.addfinalizer(restore)


def run_main_assert_result(capsys, args, expect=None):
    testargs = [RELEASE_TOOL] + args
    with patch.object(sys, "argv", testargs):
        main()

    captured = capsys.readouterr().out.strip()
    if expect is not None:
        assert captured == expect
    return captured


def test_version_of(capsys):
    # On a clean checkout, both will be master
    run_main_assert_result(capsys, ["--version-of", "deviceauth"], "master")
    run_main_assert_result(
        capsys,
        ["--version-of", "deviceauth", "--version-type", "docker"],
        "mender-master",
    )
    run_main_assert_result(
        capsys, ["--version-of", "deviceauth", "--version-type", "git"], "master"
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
    mender-deviceauth:
        image: mendersoftware/deviceauth:1.2.3-git
"""
        )
    run_main_assert_result(capsys, ["--version-of", "deviceauth"], "1.2.3-git")
    run_main_assert_result(
        capsys,
        ["--version-of", "deviceauth", "--version-type", "docker"],
        "mender-master",
    )
    run_main_assert_result(
        capsys, ["--version-of", "deviceauth", "--version-type", "git"], "1.2.3-git"
    )

    # Manually modifying the Docker version:
    filename = os.path.join(INTEGRATION_DIR, "docker-compose.yml")
    with open(filename, "w") as fd:
        fd.write(
            """services:
    mender-deviceauth:
        image: mendersoftware/deviceauth:4.5.6-docker
"""
        )
    run_main_assert_result(capsys, ["--version-of", "deviceauth"], "1.2.3-git")
    run_main_assert_result(
        capsys,
        ["--version-of", "deviceauth", "--version-type", "docker"],
        "4.5.6-docker",
    )
    run_main_assert_result(
        capsys, ["--version-of", "deviceauth", "--version-type", "git"], "1.2.3-git"
    )


def test_version_of_with_in_integration_version(capsys):
    # In remote master, shall be master
    run_main_assert_result(
        capsys,
        ["--version-of", "inventory", "--in-integration-version", "3.1.x"],
        "4.0.x",
    )
    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "inventory",
            "--version-type",
            "docker",
            "--in-integration-version",
            "3.1.x",
        ],
        "mender-3.1.x",
    )
    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "inventory",
            "--version-type",
            "git",
            "--in-integration-version",
            "3.1.x",
        ],
        "4.0.x",
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


def test_set_version_of(capsys):
    # Using --set-version-of modifies both versions, regardless of using the repo name
    run_main_assert_result(
        capsys, ["--set-version-of", "deviceauth", "--version", "1.2.3-test"]
    )
    run_main_assert_result(capsys, ["--version-of", "deviceauth"], "1.2.3-test")
    run_main_assert_result(
        capsys, ["--version-of", "deviceauth", "--version-type", "docker"], "1.2.3-test"
    )
    run_main_assert_result(
        capsys, ["--version-of", "deviceauth", "--version-type", "git"], "1.2.3-test"
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
    # NOTE: skip check for OS flavor for branches without it (namely staging)
    list_repos = run_main_assert_result(capsys, ["--list", "git"], None)
    if "deployments" in list_repos.split("\n"):
        run_main_assert_result(capsys, ["--version-of", "deployments"], "4.5.6-test")
        run_main_assert_result(
            capsys,
            ["--version-of", "deployments", "--version-type", "docker"],
            "4.5.6-test",
        )
        run_main_assert_result(
            capsys,
            ["--version-of", "deployments", "--version-type", "git"],
            "4.5.6-test",
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


def test_integration_versions_including(capsys):
    pytest.skip(
        "--integration-versions-including doesn't work on 3.1.x and older branches after N-to-N component mapping (0bb62557e30) was introduced"
    )

    captured = run_main_assert_result(
        capsys,
        ["--integration-versions-including", "inventory", "--version", "master"],
        None,
    )
    # The output shall be <remote>/master
    assert captured.endswith("/master")

    captured = run_main_assert_result(
        capsys,
        ["--integration-versions-including", "inventory", "--version", "1.6.x"],
        None,
    )
    # Three versions: <remote>/2.2.x, <remote>/2.1.x, <remote>/2.0.x
    versions = captured.split("\n")
    assert len(versions) == 3
    assert versions[0].endswith("/2.2.x")
    assert versions[1].endswith("/2.1.x")
    assert versions[2].endswith("/2.0.x")


def test_docker_compose_files_list():
    list_git = docker_compose_files_list(INTEGRATION_DIR, version="git")
    list_git_filenames = [os.path.basename(file) for file in list_git]
    assert "docker-compose.client.demo.yml" in list_git_filenames
    assert "docker-compose.no-ssl.yml" in list_git_filenames
    assert "docker-compose.testing.enterprise.yml" in list_git_filenames
    assert "other-components.yml" in list_git_filenames
    assert "docker-compose.storage.minio.yml" in list_git_filenames
    assert "docker-compose.client.rofs.yml" in list_git_filenames
    assert "docker-compose.client-dev.yml" in list_git_filenames
    assert "docker-compose.mt.client.yml" in list_git_filenames
    assert "docker-compose.demo.yml" in list_git_filenames
    assert "docker-compose.client.yml" in list_git_filenames
    assert "docker-compose.docker-client.yml" in list_git_filenames

    assert "git-versions.yml" in list_git_filenames
    assert "git-versions-enterprise.yml" in list_git_filenames
    assert "docker-compose.yml" not in list_git_filenames
    assert "docker-compose.enterprise.yml" not in list_git_filenames

    list_docker = docker_compose_files_list(INTEGRATION_DIR, version="docker")
    list_docker_filenames = [os.path.basename(file) for file in list_docker]
    assert "docker-compose.client.demo.yml" in list_docker_filenames
    assert "docker-compose.no-ssl.yml" in list_docker_filenames
    assert "docker-compose.testing.enterprise.yml" in list_docker_filenames
    assert "other-components.yml" in list_docker_filenames
    assert "docker-compose.storage.minio.yml" in list_docker_filenames
    assert "docker-compose.client.rofs.yml" in list_docker_filenames
    assert "docker-compose.client-dev.yml" in list_docker_filenames
    assert "docker-compose.mt.client.yml" in list_docker_filenames
    assert "docker-compose.demo.yml" in list_docker_filenames
    assert "docker-compose.client.yml" in list_docker_filenames
    assert "docker-compose.docker-client.yml" in list_docker_filenames

    assert "git-versions.yml" not in list_docker_filenames
    assert "git-versions-enterprise.yml" not in list_docker_filenames
    assert "docker-compose.yml" in list_docker_filenames
    assert "docker-compose.enterprise.yml" in list_docker_filenames
