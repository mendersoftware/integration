#!/bin/bash
# Copyright 2024 Northern.tech AS
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

set -x -e -o pipefail

DOWNLOAD_REQUIREMENTS="true"

export PYTHONDONTWRITEBYTECODE=1

usage() {
    echo "Usage: $ run.sh [-h|--help] [--no-download] [--get-requirements] [ -- [<pytest-args>] [tests/<testfile.py>] ]"
    echo
    echo "    -h                               Display help"
    echo "    --no-download                    Do not download the external dependencies"
    echo "    --get-requirements               Download the external binary requirements into ./downloaded-tools and exit"
    echo "    --                               Separates 'run.sh' arguments from pytest arguments"
    echo "    <pytest-args>                    Passes these arguments along to pytest"
    echo "    tests/<testfile.py>              Name the test-file to run"
    echo "    -k TestNameToRun                 Name of the test class, method, or module to run"

    echo
    echo "Recognized Environment Variables:"
    echo
    echo "XDIST_JOBS_IN_PARALLEL_INTEGRATION   The number of parallel jobs for pytest-xdist"
    exit 0
}

while [ -n "$1" ]; do
    case "$1" in
        -h|--help)
            set +x
            usage
            ;;
        --no-download)
            DOWNLOAD_REQUIREMENTS=""
            ;;
        -- )
            shift
            # Pass on the rest of the arguments un-touched to pytest
            break ;;
    esac
    shift
done

function get_requirements() {
    # Download what we need.
    mkdir -p downloaded-tools

    # Detect the branches from where to download the tools
    MENDER_BRANCH=$(../extra/release_tool.py --version-of mender)
    if [[ $? -ne 0 ]]; then
        echo "Failed to determine mender version using release_tool.py"
        exit 1
    fi

    echo "Detected Mender branch: $MENDER_BRANCH"

    # Download the tools
    EXTRACT_DIR=$(mktemp -d mender-artifact.XXXXXX)
    (
        test -z "$MENDER_ARTIFACT_VERSION" && source ../.env
        curl --fail \
            "https://downloads.mender.io/repos/debian/pool/main/m/mender-artifact/mender-artifact_${MENDER_ARTIFACT_VERSION}-1%2bubuntu%2bnoble_amd64.deb" \
            -o "$EXTRACT_DIR/mender-artifact.deb"
    )
    if [ $? -ne 0 ]; then
        echo "failed to download mender-artifact"
        exit 1
    fi

    dpkg -x "$EXTRACT_DIR/mender-artifact.deb" "$EXTRACT_DIR"
    mv $EXTRACT_DIR/usr/bin/mender-artifact downloaded-tools/mender-artifact
    rm -rf $EXTRACT_DIR

    curl --fail "https://raw.githubusercontent.com/mendersoftware/mender/${MENDER_BRANCH}/support/modules-artifact-gen/directory-artifact-gen" \
         -o downloaded-tools/directory-artifact-gen \
         -z downloaded-tools/directory-artifact-gen

    if [ $? -ne 0 ]; then
        echo "failed to download directory-artifact-gen"
        exit 1
    fi

    chmod +x downloaded-tools/directory-artifact-gen

    curl --fail "https://raw.githubusercontent.com/mendersoftware/mender/${MENDER_BRANCH}/support/modules-artifact-gen/single-file-artifact-gen" \
         -o downloaded-tools/single-file-artifact-gen \
         -z downloaded-tools/single-file-artifact-gen

    if [ $? -ne 0 ]; then
        echo "failed to download single-file-artifact-gen"
        exit 1
    fi

    chmod +x downloaded-tools/single-file-artifact-gen

    export PATH=$PWD/downloaded-tools:$PATH
}

if [[ $1 == "--get-requirements" ]]; then
    get_requirements
    exit 0
fi

if [[ -z "$BUILDDIR" ]] && [[ -n "$DOWNLOAD_REQUIREMENTS" ]]; then
    get_requirements
fi

# Contains either the arguments to xdists, or '--maxfail=1', if xdist not found.
EXTRA_TEST_ARGS=
HTML_REPORT="--html=report.html --self-contained-html"

if ! python3 -m pip show pytest-xdist >/dev/null; then
    EXTRA_TEST_ARGS="--maxfail=1"
    echo "WARNING: install pytest-xdist for running tests in parallel"
else
    # run all tests when running in parallel
    EXTRA_TEST_ARGS="${XDIST_ARGS:--n ${XDIST_JOBS_IN_PARALLEL_INTEGRATION:-auto}}"
fi

if ! python3 -m pip show pytest-html >/dev/null; then
    HTML_REPORT=""
    echo "WARNING: install pytest-html for html results report"
fi

if [ -n "$K8S" ]; then
    export KUBECONFIG="${HOME}/kubeconfig.${K8S}"
    aws eks update-kubeconfig --region $AWS_DEFAULT_REGION --name $AWS_EKS_CLUSTER_NAME --kubeconfig ${HOME}/kubeconfig.${K8S}
fi
if test ${CI_NODE_TOTAL:-1} -gt 1; then
  PYTEST_NODES=$(python ci-parallel-pytest-plugin.py | tr '\n' ' ')
  if test -z "$PYTEST_NODES"; then
    echo "No tests to run for current node"
    exit 0
  fi
  export PYTEST_ADDOPTS="$PYTEST_ADDOPTS $PYTEST_NODES"
fi
python3 -m pytest \
    $EXTRA_TEST_ARGS \
    --verbose \
    --junitxml=results.xml \
    $HTML_REPORT \
    "$@"
