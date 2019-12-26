#!/usr/bin/python
# Copyright 2019 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
"""
Smoke tests for various components in our setup.

Answer the question: is my particular component, that I'll soon rely on, really up and running (ports exposed, etc)."

Compose these in e.g. test fixtures for the complete smoke test of your setup.
"""

import requests
import logging
import time

def minio(ip):
    for check in ['live', 'ready']:
        r = requests.get("http://{}:9000/minio/health/{}".format(ip, check))
        if r.status_code != 200:
            m = "'{}' check for minio returned with http {}".format(check, r.status_code)
            logging.error(m)
            raise RuntimeError(m)
        else:
            logging.info("'{}' check for minio ok".format(check))

def deployments(ip):
    for check in range(256):
        try:
                r = requests.get("http://{}:8080/api/management/v1/deployments/deployments".format(ip))
                if r.status_code != 200:
                     m = "'{}'/{} check for deployments returned with http {}".format(ip, check, r.status_code)
                     logging.error(m)
                     time.sleep(8)
                     continue
                else:
                     logging.info("'{}'/{} check for deployments ok".format(ip, check))
                     break
        except Exception:
                m = "'{}'/{} check for deployments returned with Exception".format(ip, check)
                logging.error(m)
                time.sleep(8)
                continue
