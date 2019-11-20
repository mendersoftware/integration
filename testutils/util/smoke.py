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

def minio(ip):
    for check in ['live', 'ready']:
        r = requests.get("http://{}:9000/minio/health/{}".format(ip, check))
        if r.status_code != 200:
            m = "'{}' check for minio returned with http {}".format(check, r.status_code)
            logging.error(m)
            raise RuntimeError(m)
        else:
            logging.info("'{}' check for minio ok".format(check))
