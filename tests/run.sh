#!/bin/bash
set -x -e


if [[ $INSIDE_DOCKER -eq 1 ]]; then
    # will assume if running inside docker, you are testing with the docker-compose setup
    DOCKER_GATEWAY=$(/sbin/ip route|awk '/default/ { print $3 }')
    CLIENT_IP_PORT="mender-client:8822"
    GATEWAY_IP_PORT=$DOCKER_GATEWAY":8080"

    # remove cached file and setup fakes3 hack
    find . -iname '*.pyc' -delete || true
    echo "${DOCKER_GATEWAY}" "mender-artifact-storage.s3.docker.mender.io" | tee -a /etc/hosts >/dev/null
else
    while [ ! $(docker ps | grep mender-client-qemu | wc -l) -eq 1 ]; do echo "Mender docker container not running.." && sleep 5; done
    CLIENT_IP_PORT=$(docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $(docker ps | grep "mender-client-qemu" | awk '{ print $1 }')):8822
    GATEWAY_IP_PORT=${GATEWAY_IP_PORT:-"127.0.0.1:8080"}
fi

if [[ ! -f large_image.dat ]]; then
    dd if=/dev/zero of=large_image.dat bs=200M count=0 seek=1
fi

if [[ ! -f mender-artifact ]]; then
    curl "https://d25phv8h0wbwru.cloudfront.net/master/tip/mender-artifact" -o mender-artifact
    chmod +x mender-artifact
fi

if [[ ! -f core-image-full-cmdline-vexpress-qemu.ext4 ]] || [[ "$INSIDE_DOCKER" -eq 1 ]] ; then
    echo "!! WARNING: core-image-file-cmdline-vexpress-qemu.ext4 was found in the current working directory, will download the latest !!"
    curl -o core-image-full-cmdline-vexpress-qemu.ext4 "https://s3.amazonaws.com/mender/temp/core-image-full-cmdline-vexpress-qemu.ext4"
fi

if [[ ! -f core-image-full-cmdline-vexpress-qemu-broken-network.ext4 ]]; then
    cp core-image-full-cmdline-vexpress-qemu.ext4 core-image-full-cmdline-vexpress-qemu-broken-network.ext4
    e2rm core-image-full-cmdline-vexpress-qemu-broken-network.ext4:/lib/systemd/systemd-networkd
fi

if [[ ! -f broken_update.ext4 ]]; then
    dd if=/dev/urandom of=broken_update.ext4 bs=10M count=5
fi



py.test --maxfail=1 -s --tb=short --runfast --gateway "${GATEWAY_IP_PORT}" --clients "${CLIENT_IP_PORT}" --verbose --junitxml=results.xml tests/{test_bootstrapping.py,test_basic_integration.py,test_image_update_failures.py,test_fault_tolerance.py}
py.test --maxfail=1 -s --tb=short --runslow --gateway "${GATEWAY_IP_PORT}" --clients "${CLIENT_IP_PORT}" --verbose --junitxml=results.xml tests/{test_basic_integration.py,test_image_update_failures.py,test_fault_tolerance.py}
