#!/bin/bash
set -x -e

DEFAULT_TESTS=tests/
MACHINE_NAME=qemux86-64
DOWNLOAD_REQUIREMENTS="true"

check_tests_arguments() {
    while [ -n "$1" ]; do
        case "$1" in
            --machine-name=*)
                MACHINE_NAME="${1#--machine-name=}"
                ;;
            --machine-name)
                shift
                MACHINE_NAME="$1"
                ;;
            --no-download)
                DOWNLOAD_REQUIREMENTS=""
                ;;
            tests/*)
                # Allow test files to be named on command line by removing ours.
                DEFAULT_TESTS=
                ;;
        esac
        shift
    done
}

check_tests_arguments "$@"

# Remove optional argument --no-download from the passthrough to py.test
pass_args=$(echo $@ | sed -e "s/--no-download//")

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

echo "Detected Mender branch: $MENDER_BRANCH"
echo "Detected Mender artifact branch: $MENDER_ARTIFACT_BRANCH"

function modify_services_for_testing() {
    # Remove all published ports for testing
    sed -e '/9000:9000/d' -e '/8080:8080/d' -e '/443:443/d' -e '/ports:/d' ../docker-compose.demo.yml > ../docker-compose.testing.yml
    # disable download speed limits
    sed -e 's/DOWNLOAD_SPEED/#DOWNLOAD_SPEED/' -i ../docker-compose.testing.yml
    # whitelist *all* IPs/DNS names in the gateway (will be accessed via dynamically assigned IP in tests)
    sed -e 's/ALLOWED_HOSTS: .*/ALLOWED_HOSTS: ~./' -i ../docker-compose.testing.yml
}

function inject_pre_generated_ssh_keys() {
    ssh-keygen -f /tmp/mender-id_rsa -t rsa -N ''
    printf "cd /home/root/\nmkdir .ssh\ncd .ssh\nwrite /tmp/mender-id_rsa.pub id_rsa.pub\nwrite /tmp/mender-id_rsa id_rsa\n" | debugfs -w core-image-full-cmdline-$MACHINE_NAME.ext4
    rm /tmp/mender-id_rsa.pub
    rm /tmp/mender-id_rsa
}

function get_requirements() {
    # Download what we need.
    mkdir -p downloaded-tools

    curl --fail "https://d1b0l86ne08fsf.cloudfront.net/mender-artifact/${MENDER_ARTIFACT_BRANCH}/linux/mender-artifact" \
         -o downloaded-tools/mender-artifact \
         -z downloaded-tools/mender-artifact

    if [ $? -ne 0 ]; then
        echo "failed to download mender-artifact"
        exit 1
    fi

    chmod +x downloaded-tools/mender-artifact

    if [ $? -ne 0 ]; then
        echo "failed to download ext4 image" 
        exit 1
    fi

   curl --fail "https://stress-client.s3-accelerate.amazonaws.com/release/mender-stress-test-client" \
        -o downloaded-tools/mender-stress-test-client \
        -z downloaded-tools/mender-stress-test-client

    if [ $? -ne 0 ]; then
        echo "failed to download mender-stress-test-client" 
        exit 1
    fi

    chmod +x downloaded-tools/mender-stress-test-client

    export PATH=$PWD/downloaded-tools:$PATH

    inject_pre_generated_ssh_keys
}

# Old ways of getting the image, now deprecated, but still needed for images
# built with thud or older.
get_ext4_image_deprecated() {
    if [[ -n "$BUILDDIR" ]]; then
        cp -f "$BUILDDIR/tmp/deploy/images/$MACHINE_NAME/core-image-full-cmdline-$MACHINE_NAME.ext4" .
    elif [[ -n "$DOWNLOAD_REQUIREMENTS" ]]; then
        curl --fail "https://mender.s3-accelerate.amazonaws.com/temp_${MENDER_BRANCH}/core-image-full-cmdline-$MACHINE_NAME.ext4" \
             -o core-image-full-cmdline-$MACHINE_NAME.ext4 \
             -z core-image-full-cmdline-$MACHINE_NAME.ext4
    fi
}

if [[ $1 == "--get-requirements" ]]; then
    get_requirements
    exit 0
fi

dd if=/dev/zero of=large_image.dat bs=300M count=0 seek=1

# mender-stress-test-client is here
export PATH=$PATH:~/go/bin/

if [[ -z "$BUILDDIR" ]] && [[ -n "$DOWNLOAD_REQUIREMENTS" ]]; then
    get_requirements
fi

mkdir -p output
ret=0
docker run --rm --privileged --entrypoint /extract_fs -v $PWD/output:/output \
       mendersoftware/mender-client-qemu:$(../extra/release_tool.py -g mender-client-qemu) || ret=$?
if [ $ret -eq 0 ]; then
    # There is `extract_fs` support. Get the R/O image too.
    docker run --rm --privileged --entrypoint /extract_fs -v $PWD/output:/output \
           mendersoftware/mender-client-qemu-rofs:$(../extra/release_tool.py -g mender-client-qemu-rofs)
    mv output/* .
else
    # Old style ext4 fetching.
    get_ext4_image_deprecated
fi
rmdir output

modify_services_for_testing

cp -f core-image-full-cmdline-$MACHINE_NAME.ext4 core-image-full-cmdline-$MACHINE_NAME-broken-network.ext4
debugfs -w -R "rm /lib/systemd/systemd-networkd" core-image-full-cmdline-$MACHINE_NAME-broken-network.ext4

dd if=/dev/urandom of=broken_update.ext4 bs=10M count=5

if [[ -z $AWS_ACCESS_KEY_ID ]] || [[ -z $AWS_SECRET_ACCESS_KEY ]] ; then
    echo "AWS credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) are not set, not running S3 tests"
else
    if [[ ! -d ../keys-generated ]]; then
        ( cd .. && CERT_API_CN=docker.mender.io CERT_STORAGE_CN=s3.docker.mender.io ./keygen )
    fi

    if [[ $@ == **--runs3** ]]; then
        py.test --maxfail=1 -s --tb=short --verbose --junitxml=results.xml --runs3 tests/amazon_s3/test_s3.py::TestBasicIntegrationWithS3::test_update_image_with_aws_s3
    else
        echo "AWS creds are present, but --runs3 flag not passed."
    fi
fi

XDIST_ARGS="${XDIST_ARGS:--n ${XDIST_PARALLEL_ARG:-auto}}"
MAX_FAIL_ARG="--maxfail=1"
HTML_REPORT="--html=report.html --self-contained-html"
UPGRADE_TEST_ARG=""
SPECIFIC_INTEGRATION_TEST_ARG=""

if ! pip2 list |grep -e pytest-xdist >/dev/null 2>&1; then
    XDIST_ARGS=""
    echo "WARNING: install pytest-xdist for running tests in parallel"
else
    # run all tests when running in parallel
    MAX_FAIL_ARG=""
fi

if ! pip2 list|grep -e pytest-html >/dev/null 2>&1; then
    HTML_REPORT=""
    echo "WARNING: install pytest-html for html results report"
fi

if [[ -n $UPGRADE_FROM ]]; then
    UPGRADE_TEST_ARG="--upgrade-from $UPGRADE_FROM"
fi

if [[ -n $SPECIFIC_INTEGRATION_TEST ]]; then
    SPECIFIC_INTEGRATION_TEST_ARG="-k $SPECIFIC_INTEGRATION_TEST"
fi

if [ $# -eq 0 ]; then
    py.test $XDIST_ARGS $MAX_FAIL_ARG -s --verbose --junitxml=results.xml $HTML_REPORT --runfast --runslow $UPGRADE_TEST_ARG $SPECIFIC_INTEGRATION_TEST_ARG $DEFAULT_TESTS
    exit $?
fi

python -m pytest $XDIST_ARGS $MAX_FAIL_ARG -s --verbose --junitxml=results.xml $HTML_REPORT $pass_args $DEFAULT_TESTS
