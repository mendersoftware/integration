#!/bin/bash

set -e

if [ -z "$K8S" ]; then
    sleep 30
else
    aws eks --region $AWS_DEFAULT_REGION update-kubeconfig --name $AWS_EKS_CLUSTER_NAME
    kubectl config set-context --current --namespace=$K8S
    kubectl get pods -o wide
fi

python3 -m pytest -v -s /tests/test_*.py "$@"
