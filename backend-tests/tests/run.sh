#!/bin/bash

set -e

if [ -n "$K8S" ]; then
    aws eks --region $AWS_DEFAULT_REGION update-kubeconfig --name $AWS_EKS_CLUSTER_NAME
    kubectl config set-context --current --namespace=$K8S
    kubectl get pods -o wide
fi

if [ -n "$SSH_PRIVATE_KEY" ]; then
    eval $(ssh-agent -s)
    echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add - > /dev/null
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    ssh-keyscan github.com >> ~/.ssh/known_hosts
fi

force_sugar=""
if python3 -m pip show pytest-sugar >/dev/null; then
    # Force pytest-sugar in CI/CD containers
    # ref https://github.com/Teemu/pytest-sugar/issues/219
    force_sugar="--force-sugar"
fi

python3 -m pytest -v -s /tests/test_*.py $force_sugar "$@"
