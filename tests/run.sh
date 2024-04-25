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

set -x -e

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
    echo "TESTS_IN_PARALLEL_INTEGRATION        The number of parallel jobs for pytest-xdist"
    echo "SPECIFIC_INTEGRATION_TEST            The ability to pass <testname-regexp> to pytest -k"
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

MENDER_BRANCH=$(../extra/release_tool.py --version-of mender)
if [[ $? -ne 0 ]]; then
    echo "Failed to determine mender version using release_tool.py"
    exit 1
fi

MENDER_ARTIFACT_BRANCH=$(../extra/release_tool.py --version-of mender-artifact)
if [[ $? -ne 0 ]]; then
    echo "Failed to determine mender-artifact version using release_tool.py"
    exit 1
fi

MENDER_CLI_BRANCH=$(../extra/release_tool.py --version-of mender-cli)
if [[ $? -ne 0 ]]; then
    echo "Failed to determine mender-cli version using release_tool.py"
    exit 1
fi

echo "Detected Mender branch: $MENDER_BRANCH"
echo "Detected mender-artifact branch: $MENDER_ARTIFACT_BRANCH"
echo "Detected mender-cli branch: $MENDER_CLI_BRANCH"

function get_requirements() {
    # Download what we need.
    mkdir -p downloaded-tools

    curl --fail "https://downloads.mender.io/mender-artifact/${MENDER_ARTIFACT_BRANCH}/linux/mender-artifact" \
         -o downloaded-tools/mender-artifact \
         -z downloaded-tools/mender-artifact

    if [ $? -ne 0 ]; then
        echo "failed to download mender-artifact"
        exit 1
    fi

    chmod +x downloaded-tools/mender-artifact

    curl --fail "https://downloads.mender.io/mender-cli/${MENDER_CLI_BRANCH}/linux/mender-cli" \
         -o downloaded-tools/mender-cli \
         -z downloaded-tools/mender-cli

    if [ $? -ne 0 ]; then
        echo "failed to download mender-cli"
        exit 1
    fi

    chmod +x downloaded-tools/mender-cli

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
    EXTRA_TEST_ARGS="${XDIST_ARGS:--n ${TESTS_IN_PARALLEL_INTEGRATION:-auto}}"
fi

if ! python3 -m pip show pytest-html >/dev/null; then
    HTML_REPORT=""
    echo "WARNING: install pytest-html for html results report"
fi

if [[ -n $SPECIFIC_INTEGRATION_TEST ]]; then
    SPECIFIC_INTEGRATION_TEST_FLAG="-k"
fi

if [ -n "$K8S" ]; then
    export KUBECONFIG="${HOME}/kubeconfig.${K8S}"
    aws eks update-kubeconfig --region $AWS_DEFAULT_REGION --name $AWS_EKS_CLUSTER_NAME --kubeconfig ${HOME}/kubeconfig.${K8S}
fi

python3 -m pytest \
    $EXTRA_TEST_ARGS \
    --verbose \
    --junitxml=results.xml \
    $HTML_REPORT \
    "$@" \
    $SPECIFIC_INTEGRATION_TEST_FLAG ${SPECIFIC_INTEGRATION_TEST:+"$SPECIFIC_INTEGRATION_TEST"}
