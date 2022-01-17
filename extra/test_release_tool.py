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
SAMPLE_REPOS_BASE = ["deviceconnect", "gui", "tenantadm", "mender", "mender-connect"]
SAMPLE_REPOS_BACKEND_OS = ["deployments", "inventory", "useradm", "deviceauth"]
SAMPLE_REPOS_BACKEND_ENT = [f"{repo}-enterprise" for repo in SAMPLE_REPOS_BACKEND_OS]
SAMPLE_REPOS_NON_BACKEND = ["mender-cli", "mender-artifact", "mender-convert"]
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

    # Reset to avoid cache for further calls
    Component.COMPONENT_MAPS = None

    captured = capsys.readouterr().out.strip()
    if expect is not None:
        assert captured == expect
    return captured


def test_version_of(capsys):
    # On a clean checkout, both will be master
    run_main_assert_result(capsys, ["--version-of", "gui"], "master")
    run_main_assert_result(
        capsys, ["--version-of", "gui", "--version-type", "docker"], "mender-master",
    )
    run_main_assert_result(
        capsys, ["--version-of", "gui", "--version-type", "git"], "master"
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
    mender-gui:
        image: mendersoftware/gui:1.2.3-git
"""
        )
    run_main_assert_result(capsys, ["--version-of", "gui"], "1.2.3-git")
    run_main_assert_result(
        capsys, ["--version-of", "gui", "--version-type", "docker"], "mender-master",
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


def test_set_version_of(capsys, is_staging):
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
    if not is_staging:
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
    if is_staging:
        assert not any([r in repos_list for r in SAMPLE_REPOS_BACKEND_OS])
    else:
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
