#!/bin/bash
set -x -e

# Tip: use "docker run -v $BUILDDIR:/mnt/build" to get build artifacts from
# local hard drive.

run_slow_tests () {
    py.test --maxfail=1 -s --tb=short --runslow --verbose --junitxml=results.xml
}

run_fast_tests() {
    py.test --maxfail=1 -s --tb=short --runfast --verbose --junitxml=results.xml
}

if [[ ! -f large_image.dat ]]; then
    dd if=/dev/zero of=large_image.dat bs=200M count=0 seek=1
fi

if [[ ! -f mender-artifact ]]; then
    if [ -n "$BUILDDIR" ] && [ -f $BUILDDIR/tmp/sysroots/x86_64-linux/usr/bin/mender-artifact ]; then
        cp $BUILDDIR/tmp/sysroots/x86_64-linux/usr/bin/mender-artifact .
    else
        curl "https://d25phv8h0wbwru.cloudfront.net/master/tip/mender-artifact" -o mender-artifact
    fi
    chmod +x mender-artifact
fi

if [[ ! -f core-image-full-cmdline-vexpress-qemu.ext4 ]] ; then
    if [ -n "$BUILDDIR" ] && [ -f $BUILDDIR/tmp/deploy/images/vexpress-qemu/core-image-full-cmdline-vexpress-qemu.ext4 ]; then
        echo "!! WARNING: core-image-file-cmdline-vexpress-qemu.ext4 was not found in the current working directory, grabbing from BUILDDIR !!"
        cp $BUILDDIR/tmp/deploy/images/vexpress-qemu/core-image-full-cmdline-vexpress-qemu.ext4 .
    else
        echo "!! WARNING: core-image-file-cmdline-vexpress-qemu.ext4 was not found in the current working directory, will download the latest !!"
        curl -o core-image-full-cmdline-vexpress-qemu.ext4 "https://s3.amazonaws.com/mender/temp/core-image-full-cmdline-vexpress-qemu.ext4"
    fi
fi

if [[ ! -f core-image-full-cmdline-vexpress-qemu-broken-network.ext4 ]]; then
    cp core-image-full-cmdline-vexpress-qemu.ext4 core-image-full-cmdline-vexpress-qemu-broken-network.ext4
    e2rm core-image-full-cmdline-vexpress-qemu-broken-network.ext4:/lib/systemd/systemd-networkd
fi

if [[ ! -f broken_update.ext4 ]]; then
    dd if=/dev/urandom of=broken_update.ext4 bs=10M count=5
fi

if [[ $1 = "slow" ]]; then
    run_slow_tests
    exit
fi

if [[ $1 = "fast" ]]; then
    run_fast_tests
    exit
fi

run_slow_tests
run_fast_tests
