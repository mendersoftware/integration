#!/bin/bash

if [ -z "$K8S" ]; then
    sleep 30
else
    aws eks --region $AWS_DEFAULT_REGION update-kubeconfig --name hosted-mender-prod-03
    kubectl config set-context --current --namespace=$K8S
    kubectl get pods -o wide
fi

python3 -m pytest -s /tests/test_*.py "$@"
