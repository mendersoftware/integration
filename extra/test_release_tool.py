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
import pathlib
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest
import yaml
from release_tool import Component, docker_compose_files_list, main
from release_tool import git_to_buildparam

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RELEASE_TOOL = os.path.join(THIS_DIR, "release_tool.py")
INTEGRATION_DIR = os.path.normpath(os.path.join(THIS_DIR, ".."))

# Samples of the different "types" of repos for listing tests
SAMPLE_REPOS_BASE = ["deviceconnect", "gui", "tenantadm"]
SAMPLE_REPOS_BACKEND_OS = ["deployments", "inventory", "useradm", "deviceauth"]
SAMPLE_REPOS_BACKEND_ENT = [f"{repo}-enterprise" for repo in SAMPLE_REPOS_BACKEND_OS]
SAMPLE_REPOS_NON_BACKEND = [
    "mender-cli",
    "mender-artifact",
    "mender-convert",
    "mender",
    "mender-connect",
]
SAMPLE_REPOS_DEPRECATED = ["deviceadm", "mender-api-gateway-docker", "mender-conductor"]


@pytest.fixture(scope="session")
def is_staging():
    """Fixture to figure out if we are running the tests in staging branch

    Inspect git-versions.yml and ensure that the core OS repositories that have
    enterprise forks (i.e. deployments, inventory, and useradm) do not exist; as
    they shall exist only in git-versions-enterprise.yml.
    """

    non_staging_components = [
        "mender-deployments",
        "mender-inventory",
        "mender-useradm",
    ]
    with open(os.path.join(INTEGRATION_DIR, "git-versions.yml")) as fd:
        content = yaml.safe_load(fd)
        return not any(c in non_staging_components for c in content["services"])


def run_main_assert_result(capsys, args, expect=None):
    testargs = [RELEASE_TOOL] + args
    with patch.object(sys, "argv", testargs):
        main()

    # Reset to avoid cache for further calls
    Component.COMPONENT_MAPS = None

    captured = capsys.readouterr().out.strip()
    if expect is not None:
        assert captured == expect
    return captured


def test_version_of(capsys):
    with open(os.path.join(INTEGRATION_DIR, "docker-compose.yml")) as fd:
        content = fd.read()
        assert "mendersoftware/gui:" in content
        if re.search("mendersoftware/gui:.*master", content) is None:
            # Skip this test for non-master branches.
            pytest.skip("This test requires master tags in the docker-compose files.")

    # On a clean checkout, both will be master
    run_main_assert_result(capsys, ["--version-of", "gui"], "master")
    run_main_assert_result(
        capsys, ["--version-of", "gui", "--version-type", "docker"], "mender-master",
    )
    run_main_assert_result(
        capsys, ["--version-of", "gui", "--version-type", "git"], "master"
    )

    # Querying mender with version-type docker should error, since it maps to
    # multiple containers and we don't know which one to choose.
    run_main_assert_result(capsys, ["--version-of", "mender"], "master")
    with pytest.raises(Exception):
        run_main_assert_result(
            capsys, ["--version-of", "mender", "--version-type", "docker"], "master"
        )
    run_main_assert_result(
        capsys, ["--version-of", "mender", "--version-type", "git"], "master"
    )

    # For an independent component, it should also error because it doesn't have
    # a Docker image.
    run_main_assert_result(capsys, ["--version-of", "mender-binary-delta"], "master")
    with pytest.raises(Exception):
        run_main_assert_result(
            capsys,
            ["--version-of", "mender-binary-delta", "--version-type", "docker"],
            "master",
        )
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-binary-delta", "--version-type", "git"],
        "master",
    )

    # For a backend component, it should work for either
    run_main_assert_result(capsys, ["--version-of", "inventory"], "master")
    run_main_assert_result(
        capsys,
        ["--version-of", "inventory", "--version-type", "docker"],
        "mender-master",
    )
    run_main_assert_result(
        capsys, ["--version-of", "inventory", "--version-type", "git"], "master"
    )

    # This cannot be mapped to a single git repo, so it should fail.
    with pytest.raises(Exception):
        run_main_assert_result(capsys, ["--version-of", "mender-client-qemu"], "master")
    run_main_assert_result(
        capsys,
        ["--version-of", "mender-client-qemu", "--version-type", "docker"],
        "mender-master",
    )
    with pytest.raises(Exception):
        run_main_assert_result(
            capsys,
            ["--version-of", "mender-client-qemu", "--version-type", "git"],
            "master",
        )

    try:
        shutil.copyfile(
            os.path.join(INTEGRATION_DIR, "git-versions.yml"),
            os.path.join(INTEGRATION_DIR, "git-versions.yml.bkp"),
        )
        shutil.copyfile(
            os.path.join(INTEGRATION_DIR, "docker-compose.yml"),
            os.path.join(INTEGRATION_DIR, "docker-compose.yml.bkp"),
        )

        # Manually modifying the Git version:
        filename = os.path.join(INTEGRATION_DIR, "git-versions.yml")
        with open(filename, "w") as fd:
            fd.write(
                """services:
    mender-gui:
        image: mendersoftware/gui:1.2.3-git
"""
            )
        run_main_assert_result(capsys, ["--version-of", "gui"], "1.2.3-git")
        run_main_assert_result(
            capsys,
            ["--version-of", "gui", "--version-type", "docker"],
            "mender-master",
        )
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "git"], "1.2.3-git"
        )

        # Manually modifying the Docker version:
        filename = os.path.join(INTEGRATION_DIR, "docker-compose.yml")
        with open(filename, "w") as fd:
            fd.write(
                """services:
    mender-gui:
        image: mendersoftware/gui:4.5.6-docker
"""
            )
        run_main_assert_result(capsys, ["--version-of", "gui"], "1.2.3-git")
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "docker"], "4.5.6-docker",
        )
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "git"], "1.2.3-git"
        )

    finally:
        os.rename(
            os.path.join(INTEGRATION_DIR, "git-versions.yml.bkp"),
            os.path.join(INTEGRATION_DIR, "git-versions.yml"),
        )
        os.rename(
            os.path.join(INTEGRATION_DIR, "docker-compose.yml.bkp"),
            os.path.join(INTEGRATION_DIR, "docker-compose.yml"),
        )

    # At the time of writing, workflows git repository has two docker images,
    # where one has the same name as the repository (ambiguous). Make sure it
    # still works to query this when specifically giving "docker" as the version
    # type.
    run_main_assert_result(
        capsys,
        ["--version-of", "workflows", "--version-type", "docker"],
        "mender-master",
    )
    run_main_assert_result(
        capsys, ["--version-of", "workflows", "--version-type", "git"], "master",
    )

    run_main_assert_result(
        capsys,
        ["--version-of", "mender-client-docker-addons", "--version-type", "docker"],
        "mender-master",
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

    run_main_assert_result(
        capsys,
        ["--version-of", "mender-connect", "--in-integration-version", "3.1.0",],
        "1.2.0",
    )

    run_main_assert_result(
        capsys,
        ["--version-of", "mender", "--in-integration-version", "3.1.0",],
        "3.1.0",
    )

    run_main_assert_result(
        capsys,
        ["--version-of", "monitor-client", "--in-integration-version", "3.1.0",],
        "1.0.0",
    )

    # Ranges
    run_main_assert_result(
        capsys,
        ["--version-of", "inventory", "--in-integration-version", "3.0.1..3.1.0",],
        "3.0.0..4.0.0",
    )

    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "mender-connect",
            "--in-integration-version",
            "3.1.0..master",
        ],
        "1.2.0..master",
    )

    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "mender-configure-module",
            "--in-integration-version",
            "3.1.0..master",
        ],
        "master",
    )

    run_main_assert_result(
        capsys,
        ["--version-of", "mender", "--in-integration-version", "3.1.0..master",],
        "3.1.0..master",
    )

    run_main_assert_result(
        capsys,
        [
            "--version-of",
            "monitor-client",
            "--in-integration-version",
            "3.1.0..master",
        ],
        "1.0.0..master",
    )


def test_set_version_of(capsys, is_staging):
    try:
        shutil.copyfile(
            os.path.join(INTEGRATION_DIR, "git-versions.yml"),
            os.path.join(INTEGRATION_DIR, "git-versions.yml.bkp"),
        )
        shutil.copyfile(
            os.path.join(INTEGRATION_DIR, "git-versions-enterprise.yml"),
            os.path.join(INTEGRATION_DIR, "git-versions-enterprise.yml.bkp"),
        )
        shutil.copyfile(
            os.path.join(INTEGRATION_DIR, "docker-compose.yml"),
            os.path.join(INTEGRATION_DIR, "docker-compose.yml.bkp"),
        )
        shutil.copyfile(
            os.path.join(INTEGRATION_DIR, "docker-compose.enterprise.yml"),
            os.path.join(INTEGRATION_DIR, "docker-compose.enterprise.yml.bkp"),
        )
        shutil.copyfile(
            os.path.join(
                INTEGRATION_DIR,
                "extra/failover-testing/docker-compose.failover-server.yml",
            ),
            os.path.join(
                INTEGRATION_DIR,
                "extra/failover-testing/docker-compose.failover-server.yml.bkp",
            ),
        )

        # Using --set-version-of modifies both versions, regardless of using the repo name
        run_main_assert_result(
            capsys, ["--set-version-of", "gui", "--version", "1.2.3-test"]
        )
        run_main_assert_result(capsys, ["--version-of", "gui"], "1.2.3-test")
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "docker"], "1.2.3-test"
        )
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "git"], "1.2.3-test"
        )

        # or the container name. However, setting from the container name sets all repos (os + ent)
        run_main_assert_result(
            capsys,
            ["--set-version-of", "mender-deployments", "--version", "4.5.6-test"],
        )
        # NOTE: skip check for OS flavor for branches without it (namely staging)
        if not is_staging:
            run_main_assert_result(
                capsys,
                ["--version-of", "deployments", "--version-type", "docker"],
                "4.5.6-test",
            )
        run_main_assert_result(
            capsys,
            ["--version-of", "deployments-enterprise", "--version-type", "docker"],
            "4.5.6-test",
        )
        # NOTE: skip check for OS flavor for branches without it (namely staging)
        if not is_staging:
            run_main_assert_result(
                capsys,
                ["--version-of", "deployments", "--version-type", "git"],
                "4.5.6-test",
            )
        run_main_assert_result(
            capsys,
            ["--version-of", "deployments-enterprise", "--version-type", "git"],
            "4.5.6-test",
        )
        # NOTE: skip check for OS flavor for branches without it (namely staging)
        if not is_staging:
            run_main_assert_result(
                capsys, ["--version-of", "deployments"], "4.5.6-test"
            )
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

        # Using --set-version-of with --version-type modifies only one version
        run_main_assert_result(
            capsys,
            [
                "--set-version-of",
                "gui",
                "--version-type",
                "git",
                "--version",
                "4.5.6-test",
            ],
        )
        run_main_assert_result(capsys, ["--version-of", "gui"], "4.5.6-test")
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "docker"], "1.2.3-test"
        )
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "git"], "4.5.6-test"
        )

        run_main_assert_result(
            capsys,
            [
                "--set-version-of",
                "gui",
                "--version-type",
                "docker",
                "--version",
                "7.8.9-test",
            ],
        )
        run_main_assert_result(capsys, ["--version-of", "gui"], "4.5.6-test")
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "docker"], "7.8.9-test"
        )
        run_main_assert_result(
            capsys, ["--version-of", "gui", "--version-type", "git"], "4.5.6-test"
        )

    finally:
        os.rename(
            os.path.join(INTEGRATION_DIR, "git-versions.yml.bkp"),
            os.path.join(INTEGRATION_DIR, "git-versions.yml"),
        )
        os.rename(
            os.path.join(INTEGRATION_DIR, "git-versions-enterprise.yml.bkp"),
            os.path.join(INTEGRATION_DIR, "git-versions-enterprise.yml"),
        )
        os.rename(
            os.path.join(INTEGRATION_DIR, "docker-compose.yml.bkp"),
            os.path.join(INTEGRATION_DIR, "docker-compose.yml"),
        )
        os.rename(
            os.path.join(INTEGRATION_DIR, "docker-compose.enterprise.yml.bkp"),
            os.path.join(INTEGRATION_DIR, "docker-compose.enterprise.yml"),
        )
        os.rename(
            os.path.join(
                INTEGRATION_DIR,
                "extra/failover-testing/docker-compose.failover-server.yml.bkp",
            ),
            os.path.join(
                INTEGRATION_DIR,
                "extra/failover-testing/docker-compose.failover-server.yml",
            ),
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


@patch("release_tool.integration_dir")
def test_get_components_of_type(integration_dir_func, is_staging):
    integration_dir_func.return_value = pathlib.Path(__file__).parent.parent.absolute()

    # standard query (only_release=None)
    repos_comp = Component.get_components_of_type("git")
    repos_name = [r.name for r in repos_comp]
    assert all([r in repos_name for r in SAMPLE_REPOS_BASE])
    assert all([r in repos_name for r in SAMPLE_REPOS_BACKEND_ENT])
    assert all([r in repos_name for r in SAMPLE_REPOS_NON_BACKEND])
    assert not any([r in repos_name for r in SAMPLE_REPOS_DEPRECATED])
    if is_staging:
        assert not any([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])
    else:
        assert all([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])

    # only_release=False
    repos_comp = Component.get_components_of_type("git", only_release=False)
    repos_name = [r.name for r in repos_comp]
    assert all([r in repos_name for r in SAMPLE_REPOS_BASE])
    assert all([r in repos_name for r in SAMPLE_REPOS_BACKEND_ENT])
    assert all([r in repos_name for r in SAMPLE_REPOS_NON_BACKEND])
    assert all([r in repos_name for r in SAMPLE_REPOS_DEPRECATED])
    assert all([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])

    # only_non_release=True
    repos_comp = Component.get_components_of_type("git", only_non_release=True)
    repos_name = [r.name for r in repos_comp]
    assert not any([r in repos_name for r in SAMPLE_REPOS_BASE])
    assert not any([r in repos_name for r in SAMPLE_REPOS_BACKEND_ENT])
    assert not any([r in repos_name for r in SAMPLE_REPOS_NON_BACKEND])
    assert all([r in repos_name for r in SAMPLE_REPOS_DEPRECATED])
    if is_staging:
        assert all([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])
    else:
        assert not any([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])

    # only_independent_component=True
    repos_comp = Component.get_components_of_type(
        "git", only_independent_component=True
    )
    repos_name = [r.name for r in repos_comp]
    assert not any([r in repos_name for r in SAMPLE_REPOS_BASE])
    assert not any([r in repos_name for r in SAMPLE_REPOS_BACKEND_ENT])
    assert all([r in repos_name for r in SAMPLE_REPOS_NON_BACKEND])
    assert not any([r in repos_name for r in SAMPLE_REPOS_DEPRECATED])
    assert not any([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])

    # only_non_independent_component=True
    repos_comp = Component.get_components_of_type(
        "git", only_non_independent_component=True
    )
    repos_name = [r.name for r in repos_comp]
    assert all([r in repos_name for r in SAMPLE_REPOS_BASE])
    assert all([r in repos_name for r in SAMPLE_REPOS_BACKEND_ENT])
    assert not any([r in repos_name for r in SAMPLE_REPOS_NON_BACKEND])
    assert not any([r in repos_name for r in SAMPLE_REPOS_DEPRECATED])
    if is_staging:
        assert not any([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])
    else:
        assert all([r in repos_name for r in SAMPLE_REPOS_BACKEND_OS])


def test_list_repos(capsys, is_staging):

    # release_tool.py --list
    captured = run_main_assert_result(capsys, ["--list"], None)
    repos_list = captured.split("\n")
    assert all([r in repos_list for r in SAMPLE_REPOS_BASE])
    assert all([r in repos_list for r in SAMPLE_REPOS_BACKEND_ENT])
    assert all([r in repos_list for r in SAMPLE_REPOS_NON_BACKEND])
    assert not any([r in repos_list for r in SAMPLE_REPOS_DEPRECATED])
    if is_staging:
        assert not any([r in repos_list for r in SAMPLE_REPOS_BACKEND_OS])
    else:
        assert all([r in repos_list for r in SAMPLE_REPOS_BACKEND_OS])

    # release_tool.py --list --only-backend
    captured = run_main_assert_result(capsys, ["--list", "--only-backend"], None)
    repos_list = captured.split("\n")
    assert all([r in repos_list for r in SAMPLE_REPOS_BASE])
    assert all([r in repos_list for r in SAMPLE_REPOS_BACKEND_ENT])
    assert not any([r in repos_list for r in SAMPLE_REPOS_NON_BACKEND])
    assert not any([r in repos_list for r in SAMPLE_REPOS_DEPRECATED])
    if is_staging:
        assert not any([r in repos_list for r in SAMPLE_REPOS_BACKEND_OS])
    else:
        assert all([r in repos_list for r in SAMPLE_REPOS_BACKEND_OS])

    # release_tool.py --list --all
    captured = run_main_assert_result(capsys, ["--list", "--all"], None)
    repos_list = captured.split("\n")
    assert all([r in repos_list for r in SAMPLE_REPOS_BASE])
    assert all([r in repos_list for r in SAMPLE_REPOS_BACKEND_ENT])
    assert all([r in repos_list for r in SAMPLE_REPOS_NON_BACKEND])
    assert all([r in repos_list for r in SAMPLE_REPOS_DEPRECATED])
    assert all([r in repos_list for r in SAMPLE_REPOS_BACKEND_OS])
    assert "mender-binary-delta" in repos_list
    assert "mender-convert" in repos_list
    assert "mender-configure-module" in repos_list


def test_list_repos_old_releases(capsys):

    # release_tool.py --list --in-integration-version 3.0.0
    captured = run_main_assert_result(capsys, ["--list", "-i", "3.0.0"], None)
    repos_list = captured.split("\n")
    assert "monitor-client" not in repos_list
    assert "deviceauth-enterprise" not in repos_list
    assert "iot-manager" not in repos_list
    assert "mender" in repos_list
    assert "deviceauth" in repos_list


def test_git_to_buildparam():
    GIT_TO_BUILDPARAM_MAP = {
        "mender-api-gateway-docker": "MENDER_API_GATEWAY_DOCKER_REV",
        "iot-manager": "IOT_MANAGER_REV",
        "mender-auth-azure-iot": "MENDER_AUTH_AZURE_IOT_REV",
        "deployments": "DEPLOYMENTS_REV",
        "deployments-enterprise": "DEPLOYMENTS_ENTERPRISE_REV",
        "deviceauth": "DEVICEAUTH_REV",
        "deviceauth-enterprise": "DEVICEAUTH_ENTERPRISE_REV",
        "gui": "GUI_REV",
        "inventory": "INVENTORY_REV",
        "inventory-enterprise": "INVENTORY_ENTERPRISE_REV",
        "tenantadm": "TENANTADM_REV",
        "useradm": "USERADM_REV",
        "useradm-enterprise": "USERADM_ENTERPRISE_REV",
        "workflows": "WORKFLOWS_REV",
        "workflows-enterprise": "WORKFLOWS_ENTERPRISE_REV",
        "create-artifact-worker": "CREATE_ARTIFACT_WORKER_REV",
        "mender": "MENDER_REV",
        "mender-artifact": "MENDER_ARTIFACT_REV",
        "mender-cli": "MENDER_CLI_REV",
        "meta-mender": "META_MENDER_REV",
        "integration": "INTEGRATION_REV",
        "mender-qa": "MENDER_QA_REV",
        "auditlogs": "AUDITLOGS_REV",
        "mtls-ambassador": "MTLS_AMBASSADOR_REV",
        "deviceconnect": "DEVICECONNECT_REV",
        "mender-connect": "MENDER_CONNECT_REV",
        "deviceconfig": "DEVICECONFIG_REV",
        "devicemonitor": "DEVICEMONITOR_REV",
        "monitor-client": "MONITOR_CLIENT_REV",
        "reporting": "REPORTING_REV",
    }

    for k, v in GIT_TO_BUILDPARAM_MAP.items():
        assert git_to_buildparam(k) == v


@pytest.mark.skip(reason="don't run in staging")
def test_generate_release_notes(request, capsys):
    try:
        subprocess.check_call("rm -f release_notes*.txt", shell=True)

        os.environ["TEST_RELEASE_TOOL_LIST_OPEN_SOURCE_ONLY"] = "1"

        run_main_assert_result(
            capsys, ["--generate-release-notes", "-i", "3.0.0..3.1.0"], None
        )

        files = []
        for entry in os.listdir():
            if re.match(r"^release_notes.*\.txt$", entry) is not None:
                files.append(entry)
        files = sorted(files)

        expected_files = [
            "release_notes_mender-artifact.txt",
            "release_notes_mender-cli.txt",
            "release_notes_mender-connect.txt",
            "release_notes_mender.txt",
            "release_notes_server.txt",
        ]
        assert expected_files == files

        for f in expected_files:
            with open(
                os.path.join(request.fspath.dirname, "test", f)
            ) as expected_fd, open(f) as actual_fd:
                expected = expected_fd.read()
                actual = actual_fd.read()
                assert expected == actual

    finally:
        subprocess.check_call("rm -f release_notes*.txt", shell=True)
        del os.environ["TEST_RELEASE_TOOL_LIST_OPEN_SOURCE_ONLY"]


@pytest.mark.skip(reason="don't run in staging")
def test_generate_release_notes_from_master(request, capsys):
    try:
        subprocess.check_call("rm -f release_notes*.txt", shell=True)

        os.environ["TEST_RELEASE_TOOL_LIST_OPEN_SOURCE_ONLY"] = "1"

        output = run_main_assert_result(
            capsys, ["--generate-release-notes", "-i", "master"], None
        )

        # Since master and therefore the latest version is a moving target, it's
        # difficult to test content, but make sure the tool has selected a
        # version to diff from, and not just the entire master branch.
        assert re.search(r"[0-9]\.\.master", output) is not None

    finally:
        subprocess.check_call("rm -f release_notes*.txt", shell=True)
        del os.environ["TEST_RELEASE_TOOL_LIST_OPEN_SOURCE_ONLY"]
