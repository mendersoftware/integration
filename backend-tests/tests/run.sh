#!/bin/bash
sleep 30

python3 -m pytest -s /tests/test_*.py "$@"
