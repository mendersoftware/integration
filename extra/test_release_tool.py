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
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-client-qemu", "--version-type", "docker"],
        "master",
    )

    # Manually modifying the Git version:
    filename = os.path.join(INTEGRATION_DIR, "git-versions.yml")
    with open(filename, "w") as fd:
        fd.write(
            """services:
    deviceauth:
        git-version: 1.2.3-git
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
        ["--version-of", "inventory", "--in-integration-version", "master"],
        "master",
    )
    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "inventory",
            "--version-type",
            "docker",
            "--in-integration-version",
            "master",
        ],
        "mender-master",
    )
    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "inventory",
            "--version-type",
            "git",
            "--in-integration-version",
            "master",
        ],
        "master",
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
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-deployments", "--version-type", "docker"],
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


def test_version_of_all_components_types(capsys):
    # As git repos (only git version type)
    list_repos = run_main_assert_result(capsys, ["--list", "git"], None)
    for repo in list_repos.split("\n"):
        if repo == "integration":
            # Skip integration as it will return the current branch (dev branch or PR branch)
            continue
        git_version = run_main_assert_result(
            capsys, ["--version-of", repo, "--version-type", "git"],
        )
        assert git_version == "master", "failed for repo %s" % repo

    # As docker images (only docker version type)
    list_images = run_main_assert_result(capsys, ["--list", "docker"], None)
    for image in list_images.split("\n"):
        docker_version = run_main_assert_result(
            capsys, ["--version-of", image, "--version-type", "docker"],
        )
        if image.startswith("mender-client-"):
            assert docker_version == "master", "failed for image %s" % image
        else:
            assert docker_version == "mender-master", "failed for image %s" % image

    # As docker container names (only docker version type)
    list_containers = run_main_assert_result(capsys, ["--list", "container"], None)
    for container in list_containers.split("\n"):
        docker_version = run_main_assert_result(
            capsys, ["--version-of", container, "--version-type", "docker"], None,
        )
        if container == "mender-client":
            assert docker_version == "master", "failed for container %s" % container
        else:
            assert docker_version == "mender-master", (
                "failed for container %s" % container
            )

    # Try getting Git version for an ambiguous one: mender-api-gateway-docker/api-gateway/mender-api-gateway
    # as repo
    git_version = run_main_assert_result(
        capsys, ["--version-of", "mender-api-gateway-docker", "--version-type", "git"],
    )
    assert git_version == "master", "failed for repo mender-api-gateway-docker"
    # as image
    try:
        run_main_assert_result(
            capsys, ["--version-of", "api-gateway", "--version-type", "git"],
        )
    except SystemExit:
        err_message = capsys.readouterr().out.strip()
        assert (
            err_message
            == "Unsuported docker_image api-gateway for --version-type git. Use --version-type docker instead"
        )
    else:
        assert False, "expected to fail for image api-gateway; but succeeded"
    # and as container
    try:
        run_main_assert_result(
            capsys, ["--version-of", "mender-api-gateway", "--version-type", "git"],
        )
    except SystemExit:
        err_message = capsys.readouterr().out.strip()
        assert (
            err_message
            == "Unsuported docker_container mender-api-gateway for --version-type git. Use --version-type docker instead"
        )
    else:
        assert False, "expected to fail for container mender-api-gateway; but succeeded"
