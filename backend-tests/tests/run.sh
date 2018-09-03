#!/bin/bash
sleep 30

py.test-3 -s /tests/test_*.py "$@"
