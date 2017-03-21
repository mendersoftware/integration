#!/bin/bash
set -x -e
RUN_S3=""


# we need to make sure we use the correct ext4 image for testing
if [[ -z "$BUILDDIR" ]] && [[ -z "$TEST_BRANCH" ]]; then
    echo "TEST_BRANCH environment variable needs to be set"
    exit 1
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
fi


cp -f core-image-full-cmdline-vexpress-qemu.ext4 core-image-full-cmdline-vexpress-qemu-broken-network.ext4
debugfs -w -R "rm /lib/systemd/systemd-networkd" core-image-full-cmdline-vexpress-qemu-broken-network.ext4

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

if [ $# -eq 0 ]; then
    py.test --maxfail=1 -s --tb=short --verbose --junitxml=results.xml --runfast --runslow
    exit $?
fi

py.test --maxfail=1 -s --tb=short --verbose --junitxml=results.xml "$@"
