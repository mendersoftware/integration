#!/bin/bash

[ $$ -eq 1 ] && sleep 30

py.test-3 -s /tests/test_*.py "$@"
