#!/bin/bash
set -x -e

if [[ ! -f large_image.dat ]]; then
  dd if=/dev/zero of=large_image.dat bs=1G count=0 seek=1
fi

if [[ ! -f core-image-full-cmdline-vexpress-qemu.ext4 ]]; then
    # check if this is a jenkins job by checking if variable is set
    if [ -z "$JENKINS_URL" ]; then
      wget -N "https://s3-eu-west-1.amazonaws.com/yocto-integration-builds/latest/core-image-full-cmdline-vexpress-qemu.ext4"
    else
      cp $EXT4_IMAGE_PATH .
    fi
fi

if [[ ! -f core-image-full-cmdline-vexpress-qemu-broken-network.ext4 ]]; then
    cp core-image-full-cmdline-vexpress-qemu.ext4 core-image-full-cmdline-vexpress-qemu-broken-network.ext4
    e2rm core-image-full-cmdline-vexpress-qemu-broken-network.ext4:/lib/systemd/systemd-networkd
fi

if [[ ! -f broken_image.dat ]]; then
    dd if=/dev/zero of=broken_image.dat bs=10M count=0 seek=1
fi

py.test-2.7 -s --tb=short --runslow --clients "127.0.0.1:8822" --verbose --junitxml=results.xml tests/test_fault_tolerance.py
