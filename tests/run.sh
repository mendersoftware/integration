#!/bin/bash
set -x -e

function get_requirements() {
    # Download what we need.
    mkdir -p downloaded-tools

    artifact_version=$(../extra/release_tool.py --version-of mender-artifact)
    curl "https://d25phv8h0wbwru.cloudfront.net/${artifact_version}/tip/mender-artifact" -o downloaded-tools/mender-artifact

    chmod +x downloaded-tools/mender-artifact
    export PATH=$PWD/downloaded-tools:$PATH

    curl -o core-image-full-cmdline-vexpress-qemu.ext4 "https://s3.amazonaws.com/mender/temp_${TEST_BRANCH}/core-image-full-cmdline-vexpress-qemu.ext4"
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

cp -f core-image-full-cmdline-vexpress-qemu.ext4 core-image-full-cmdline-vexpress-qemu-broken-network.ext4
debugfs -w -R "rm /lib/systemd/systemd-networkd" core-image-full-cmdline-vexpress-qemu-broken-network.ext4

dd if=/dev/urandom of=broken_update.ext4 bs=10M count=5

if [ $# -eq 0 ]; then
    py.test --maxfail=1 -s --tb=short --verbose --junitxml=results.xml --runfast --runslow
    exit $?
fi

py.test --maxfail=1 -s --tb=short --verbose --junitxml=results.xml "$@"
