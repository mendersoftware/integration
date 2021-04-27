#!/bin/bash

set -e

if [ -n "$K8S" ]; then
    aws eks --region $AWS_DEFAULT_REGION update-kubeconfig --name $AWS_EKS_CLUSTER_NAME
    kubectl config set-context --current --namespace=$K8S
    kubectl get pods -o wide
fi

python3 -m pytest -v -s /tests/test_*.py "$@"
