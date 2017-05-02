#!/bin/bash
set -x -e
RUN_S3=""

function get_requirements() {
    # Download what we need.
    mkdir -p downloaded-tools
    curl "https://d25phv8h0wbwru.cloudfront.net/${TEST_BRANCH}/tip/mender-artifact" \
         -o downloaded-tools/mender-artifact \
         -z downloaded-tools/mender-artifact

    chmod +x downloaded-tools/mender-artifact
    export PATH=$PWD/downloaded-tools:$PATH


    curl "https://s3.amazonaws.com/mender/temp_${TEST_BRANCH}/core-image-full-cmdline-vexpress-qemu.ext4" \
         -o core-image-full-cmdline-vexpress-qemu.ext4 \
         -z core-image-full-cmdline-vexpress-qemu.ext4
}


# we need to make sure we use the correct ext4 image for testing
if [[ -z "$BUILDDIR" ]] && [[ -z "$TEST_BRANCH" ]]; then
    echo "TEST_BRANCH environment variable needs to be set"
    exit 1
fi

if [[ $1 == "--get-requirements" ]]; then
    get_requirements
    exit 0
fi

if [[ ! -f large_image.dat ]]; then
    dd if=/dev/zero of=large_image.dat bs=200M count=0 seek=1
fi

if [[ -n "$BUILDDIR" ]]; then
    # Get the necessary path directly from the build.

    # On branches without recipe specific sysroots, the next step will fail
    # because the prepare_recipe_sysroot task doesn't exist. Use that failure
    # to fall back to the old generic sysroot path.
    if ( cd $BUILDDIR && bitbake -c prepare_recipe_sysroot mender-test-dependencies ); then
        eval `cd $BUILDDIR && bitbake -e mender-test-dependencies | grep '^export PATH='`:$PATH
    else
        eval `cd $BUILDDIR && bitbake -e core-image-minimal | grep '^export PATH='`:$PATH
    fi

    cp -f $BUILDDIR/tmp/deploy/images/vexpress-qemu/core-image-full-cmdline-vexpress-qemu.ext4 .
else
    get_requirements
fi


# Remove all published ports for testing
sed -e '/9000:9000/d' -e '/443:443/d' -e '/ports:/d' ../docker-compose.demo.yml > ../docker-compose.testing.yml


cp -f core-image-full-cmdline-vexpress-qemu.ext4 core-image-full-cmdline-vexpress-qemu-broken-network.ext4
debugfs -w -R "rm /lib/systemd/systemd-networkd" core-image-full-cmdline-vexpress-qemu-broken-network.ext4

dd if=/dev/urandom of=broken_update.ext4 bs=10M count=5

if [[ -z $AWS_ACCESS_KEY_ID ]] || [[ -z $AWS_SECRET_ACCESS_KEY ]] ; then
    echo "AWS credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) are not set, not running S3 tests"
else
    if [[ ! -d ../keys-generated ]]; then
        ( cd .. && CERT_API_CN=docker.mender.io CERT_STORAGE_CN=s3.docker.mender.io ./keygen )
    fi
fi

XDIST_ARGS="-n auto"
MAX_FAIL_ARG="--maxfail=1"
HTML_REPORT="--html=report.html --self-contained-html"

if ! pip list |grep -e pytest-xdist >/dev/null 2>&1; then
    XDIST_ARGS=""
    echo "WARNING: install pytest-xdist for running tests in parallel"
else
    # run all tests when running in parallel
    MAX_FAIL_ARG=""

    # allow you to run something else besides -n auto
    if [[ -n $XDIST_PARALLEL_ARG ]]; then
        XDIST_ARGS="-n $XDIST_PARALLEL_ARG"
    fi
fi

if ! pip list|grep -e pytest-html >/dev/null 2>&1; then
    HTML_REPORT=""
    echo "WARNING: install pytest-html for html results report"
fi

if [ $# -eq 0 ]; then
    py.test $XDIST_ARGS $MAX_FAIL_ARG -s --verbose --junitxml=results.xml $HTML_REPORT --runfast --runslow tests/
    exit $?
fi

py.test $XDIST_ARGS $MAX_FAIL_ARG -s --verbose --junitxml=results.xml $HTML_REPORT "$@" tests/
