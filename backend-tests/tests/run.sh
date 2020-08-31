#!/bin/bash

if [ -z "$K8S" ]; then
    sleep 30
fi

python3 -m pytest -s /tests/test_*.py "$@"
