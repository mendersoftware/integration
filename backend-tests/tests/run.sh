#!/bin/bash
# Copyright 2022 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

set -e

if [ -n "$K8S" ]; then
    aws eks --region $AWS_DEFAULT_REGION update-kubeconfig --name $AWS_EKS_CLUSTER_NAME
    kubectl config set-context --current --namespace=$K8S
    kubectl get pods -o wide
fi

python3 -m pytest -v -s /tests/test_*.py "$@"
