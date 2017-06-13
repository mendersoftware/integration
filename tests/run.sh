#!/bin/bash
set -x -e
RUN_S3=""
MENDER_BRANCH=$(../extra/release_tool.py --version-of mender)

if [[ $? -ne 0 ]]; then
    echo "Failed to determine mender version using release_tool.py"
    exit 1
fi

MENDER_ARTIFACT_BRANCH=$(../extra/release_tool.py --version-of artifact)

if [[ $? -ne 0 ]]; then
    echo "Failed to determine mender-artifact version using release_tool.py"
    exit 1
fi

echo "Detected Mender branch: $MENDER_BRANCH"
echo "Detected Mender artifact branch: $MENDER_ARTIFACT_BRANCH"


function get_requirements() {
    # Download what we need.
    mkdir -p downloaded-tools
    curl "https://d25phv8h0wbwru.cloudfront.net/${MENDER_ARTIFACT_BRANCH}/tip/mender-artifact" \
         -o downloaded-tools/mender-artifact \
         -z downloaded-tools/mender-artifact

    chmod +x downloaded-tools/mender-artifact
    export PATH=$PWD/downloaded-tools:$PATH

    curl "https://s3.amazonaws.com/mender/temp_${MENDER_BRANCH}/core-image-full-cmdline-vexpress-qemu.ext4" \
         -o core-image-full-cmdline-vexpress-qemu.ext4 \
         -z core-image-full-cmdline-vexpress-qemu.ext4
}

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
