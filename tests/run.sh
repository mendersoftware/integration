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

function modify_services_for_testing() {
    # Remove all published ports for testing
    sed -e '/9000:9000/d' -e '/443:443/d' -e '/ports:/d' ../docker-compose.demo.yml > ../docker-compose.testing.yml
    # disable download speed limits
    sed -e 's/DOWNLOAD_SPEED/#DOWNLOAD_SPEED/' -i ../docker-compose.testing.yml
    # whitelist *all* IPs/DNS names in the gateway (will be accessed via dynamically assigned IP in tests)
    sed -e 's/ALLOWED_HOSTS: .*/ALLOWED_HOSTS: ~./' -i ../docker-compose.testing.yml
    # disable dynomite logs, NOTE indentation is important in this one
    cat <<EOF  >> ../docker-compose.testing.yml
    mender-dynomite:
        logging:
            driver: "none"
EOF
}

function inject_pre_generated_ssh_keys() {
    ssh-keygen -f /tmp/mender-id_rsa -t rsa -N ''
    echo "cd /home/root/\nmkdir .ssh\ncd .ssh\nwrite /tmp/mender-id_rsa.pub id_rsa.pub\nwrite /tmp/mender-id_rsa id_rsa" | debugfs -w core-image-full-cmdline-vexpress-qemu.ext4
    rm /tmp/mender-id_rsa.pub
    rm /tmp/mender-id_rsa
}

function get_requirements() {
    # Download what we need.
    mkdir -p downloaded-tools

    curl "https://d1b0l86ne08fsf.cloudfront.net/mender-artifact/${MENDER_ARTIFACT_BRANCH}/mender-artifact" \
         -o downloaded-tools/mender-artifact \
         -z downloaded-tools/mender-artifact

    chmod +x downloaded-tools/mender-artifact


    curl "https://s3.amazonaws.com/mender/temp_${MENDER_BRANCH}/core-image-full-cmdline-vexpress-qemu.ext4" \
         -o core-image-full-cmdline-vexpress-qemu.ext4 \
         -z core-image-full-cmdline-vexpress-qemu.ext4

   curl "https://s3-eu-west-1.amazonaws.com/stress-client/release/mender-stress-test-client" \
        -o downloaded-tools/mender-stress-test-client \
        -z downloaded-tools/mender-stress-test-client

    chmod +x downloaded-tools/mender-stress-test-client

    export PATH=$PWD/downloaded-tools:$PATH

    modify_services_for_testing
    inject_pre_generated_ssh_keys
}

if [[ $1 == "--get-requirements" ]]; then
    get_requirements
    exit 0
fi

if [[ ! -f large_image.dat ]]; then
    dd if=/dev/zero of=large_image.dat bs=300M count=0 seek=1
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

    # mender-stress-test-client is here
    export PATH=$PATH:~/go/bin/

    modify_services_for_testing
else
    get_requirements
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
    py.test $XDIST_ARGS $MAX_FAIL_ARG -s --verbose --junitxml=results.xml $HTML_REPORT --runfast --runslow $UPGRADE_TEST_ARG $SPECIFIC_INTEGRATION_TEST_ARG tests/
    exit $?
fi

py.test $XDIST_ARGS $MAX_FAIL_ARG -s --verbose --junitxml=results.xml $HTML_REPORT "$@" tests/
