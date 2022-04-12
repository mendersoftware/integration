#!/bin/bash
set -x -e

MACHINE_NAME=qemux86-64
DOWNLOAD_REQUIREMENTS="true"

export PYTHONDONTWRITEBYTECODE=1

usage() {
    echo "Usage: $ run.sh [-h|--help] [--machine-name[=]<machine-name>] [--no-download] [--get-requirements] [ -- [<pytest-args>] [tests/<testfile.py>] ]"
    echo
    echo "    -h                               Display help"
    echo "    --machine-name[=] <machine-name> Specify the machine to test"
    echo "    --no-download                    Do not download the external dependencies"
    echo "    --get-requirements               Download the external binary requirements into ./downloaded-tools and exit"
    echo "    --                               Seperates 'run.sh' arguments from pytest arguments"
    echo "    <pytest-args>                    Passes these arguments along to pytest"
    echo "    tests/<testfile.py>              Name the test-file to run"
    echo "    -k TestNameToRun                 Name of the test class, method, or module to run"

    echo
    echo "Recognized Environment Variables:"
    echo
    echo "TESTS_IN_PARALLEL                    The number of parallel jobs for pytest-xdist"
    echo "SPECIFIC_INTEGRATION_TEST            The ability to pass <testname-regexp> to pytest -k"
    exit 0
}

while [ -n "$1" ]; do
    case "$1" in
        -h|--help)
            set +x
            usage
            ;;
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

function modify_services_for_testing() {
    # Remove all published ports for testing
    sed -e '/9000:9000/d' -e '/8080:8080/d' -e '/443:443/d' -e '/80:80/d' -e '/ports:/d' ../docker-compose.demo.yml > ../docker-compose.testing.yml
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

    inject_pre_generated_ssh_keys
}

if [[ $1 == "--get-requirements" ]]; then
    get_requirements
    exit 0
fi

dd if=/dev/zero of=large_image.dat bs=300M count=0 seek=1

if [[ -z "$BUILDDIR" ]] && [[ -n "$DOWNLOAD_REQUIREMENTS" ]]; then
    get_requirements
fi

# Extract file system images from Docker images
# the argument for the /extract_fs is the prefix of the image name
# as per QA-387 now we are explicitly extracting a clean image
# that is: an image which is crafted to be the one we update to.
IMG_PREFIX="clean-"
mkdir -p output
docker run --rm --privileged --entrypoint /extract_fs -v "${PWD}"/output:/output \
       mendersoftware/mender-client-qemu:$(../extra/release_tool.py --version-of mender-client-qemu --version-type docker) "${IMG_PREFIX}"
docker run --rm --privileged --entrypoint /extract_fs -v "${PWD}"/output:/output \
        mendersoftware/mender-client-qemu-rofs:$(../extra/release_tool.py --version-of mender-client-qemu-rofs --version-type docker) "${IMG_PREFIX}"
docker run --rm --privileged --entrypoint /extract_fs -v "${PWD}"/output:/output \
        registry.mender.io/mendersoftware/mender-gateway-qemu-commercial:$(../extra/release_tool.py --version-of mender-gateway --version-type docker) "${IMG_PREFIX}"
mv output/* .
rmdir output

# check if the expected artifact_name is present
expected_artifact_info="artifact_name=mender-image-clean"
for i in ${IMG_PREFIX}*; do
 mv -v "$i" "${i/${IMG_PREFIX}/}"
 mender-artifact write rootfs-image -t beaglebone -n release-1 --software-version rootfs-v1 -f "${i/${IMG_PREFIX}/}" -o "/tmp/${i/${IMG_PREFIX}/}.mender"
 actual_artifact_info=`mender-artifact cat "/tmp/${i/${IMG_PREFIX}/}.mender:/etc/mender/artifact_info"`
 [[ "${expected_artifact_info}" == "${actual_artifact_info}" ]] || { echo "mismatched artifact_info. expected: $expected_artifact_info got: ${actual_artifact_info}"; exit 1; };
done

# check if artifact_info from inside the image we run is different than the one we update to
# the condition/naming is misleading since we expect the $expected_artifact_info to not be equal to 
# $artifact_info in the below images
for image_tag in mendersoftware/mender-client-qemu:$(../extra/release_tool.py --version-of mender-client-qemu --version-type docker) mendersoftware/mender-client-qemu-rofs:$(../extra/release_tool.py --version-of mender-client-qemu-rofs --version-type docker) registry.mender.io/mendersoftware/mender-gateway-qemu-commercial:$(../extra/release_tool.py --version-of mender-gateway --version-type docker); do
 id=`docker run --rm -d "${image_tag}"`
 docker exec -it "${image_tag}" apk update;
 docker exec -it "${image_tag}" apk add openssh-client;
 artifact_info=`docker exec -it "${image_tag}" ssh -o StrictHostKeyChecking=no -p8822 127.0.0.1 cat /etc/mender/artifact_info`
# we expect the artifact info to be different than the one we expected from the clean image
 [[ "${expected_artifact_info}" == "${artifact_info}" ]] && { echo "artifact_info is the same in the clean image and the image we run. got: ${artifact_info}"; exit 1; };
 docker stop "$id"
done

modify_services_for_testing

cp -f core-image-full-cmdline-$MACHINE_NAME.ext4 core-image-full-cmdline-$MACHINE_NAME-broken-network.ext4
debugfs -w -R "rm /lib/systemd/systemd-networkd" core-image-full-cmdline-$MACHINE_NAME-broken-network.ext4

dd if=/dev/urandom of=broken_update.ext4 bs=10M count=5

# Contains either the arguments to xdists, or '--maxfail=1', if xdist not found.
EXTRA_TEST_ARGS=
HTML_REPORT="--html=report.html --self-contained-html"

if ! python3 -m pip show pytest-xdist >/dev/null; then
    EXTRA_TEST_ARGS="--maxfail=1"
    echo "WARNING: install pytest-xdist for running tests in parallel"
else
    # run all tests when running in parallel
    EXTRA_TEST_ARGS="${XDIST_ARGS:--n ${TESTS_IN_PARALLEL:-auto}}"
fi

if ! python3 -m pip show pytest-html >/dev/null; then
    HTML_REPORT=""
    echo "WARNING: install pytest-html for html results report"
fi

if [[ -n $SPECIFIC_INTEGRATION_TEST ]]; then
    SPECIFIC_INTEGRATION_TEST_FLAG="-k"
fi

export TENANTADM_STRIPE_API_KEY=$STRIPE_API_KEY

if [ -n "$K8S" ]; then
    export KUBECONFIG="${HOME}/kubeconfig.${K8S}"
    aws eks --region $AWS_DEFAULT_REGION update-kubeconfig --name $AWS_EKS_CLUSTER_NAME --kubeconfig ${HOME}/kubeconfig.${K8S}
    kubectl config set-context --current --namespace=$K8S
    kubectl get pods -o wide
fi

python3 -m pytest \
    $EXTRA_TEST_ARGS \
    --verbose \
    --junitxml=results.xml \
    $HTML_REPORT \
    "$@" \
    $SPECIFIC_INTEGRATION_TEST_FLAG ${SPECIFIC_INTEGRATION_TEST:+"$SPECIFIC_INTEGRATION_TEST"}
