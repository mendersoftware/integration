#!/bin/bash

set -e

PYTEST_EXTRA_ARGS=""
if [ -n "$K8S" ]; then
    export KUBECONFIG="${HOME}/kubeconfig.${K8S}"
    aws eks update-kubeconfig --region $AWS_DEFAULT_REGION --name $AWS_EKS_CLUSTER_NAME --kubeconfig ${HOME}/kubeconfig.${K8S}
    kubectl config set-context --current --namespace=$K8S
    kubectl get pods -o wide
    if ! python3 -m pip show pytest-xdist >/dev/null; then
        echo "WARNING: install pytest-xdist for running tests in parallel"
    else
        PYTEST_EXTRA_ARGS="${XDIST_ARGS:--n ${TESTS_IN_PARALLEL:-auto}}"
    fi
fi

if [ -n "$SSH_PRIVATE_KEY" ]; then
    eval $(ssh-agent -s)
    echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add - > /dev/null
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    ssh-keyscan github.com >> ~/.ssh/known_hosts
fi

chmod 755 /usr/local/bin/mender-artifact

python3 -m pytest -v -s /tests/test_*.py $PYTEST_EXTRA_ARGS "$@"
