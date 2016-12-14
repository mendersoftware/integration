#!/usr/bin/python
# Copyright 2016 Mender Software AS
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


import requests
import json
from fabric.api import *
import time
import pytest
from MenderAPI import gateway, api_version, logger


class Deployments(object):
    # track the last statistic for a deployment id
    last_statistic = {}

    def __init__(self):
        self.deployments_base_path = "https://%s/api/integrations/%s/deployments/" % (gateway, api_version)

    def upload_image(self, name, filename, description=""):
        image_path_url = self.deployments_base_path + "artifacts"

        r = requests.post(image_path_url, verify=False, files=(("name", (None, name)),
                          ("description", (None, description)),
                          ("artifact", (filename, open(filename),
                           "multipart/form-data"))))

        logger.info("Received image upload status code: " + str(r.status_code) + " with payload: " + str(r.text))
        assert r.status_code == requests.status_codes.codes.created
        return r.headers["location"]

    def trigger_deployment(self, name, artifact_name, devices):
        deployments_path_url = self.deployments_base_path + "deployments"

        trigger_data = {"name": name,
                        "artifact_name": artifact_name,
                        "devices": devices}

        headers = {'Content-Type': 'application/json'}

        r = requests.post(deployments_path_url, headers=headers,
                          data=json.dumps(trigger_data), verify=False)

        logger.debug("triggering deployment with: " + json.dumps(trigger_data))
        assert r.status_code == requests.status_codes.codes.created

        deployment_id = str(r.headers['Location'].split("/")[-1])
        logger.info("Deployment id is: " + deployment_id)

        return deployment_id

    def get_logs(self, device, deployment_id, expected_status=200):
        deployments_logs_url = self.deployments_base_path + "deployments/%s/devices/%s/log" % (deployment_id, device)
        r = requests.get(deployments_logs_url, verify=False)
        assert r.status_code == expected_status

        logger.info("Logs contain " + str(r.text))
        return r.text

    def get_statistics(self, deployment_id):
        deployments_statistics_url = self.deployments_base_path + "deployments/%s/statistics" % (deployment_id)
        r = requests.get(deployments_statistics_url, verify=False)
        assert r.status_code == requests.status_codes.codes.ok

        try:
            json.loads(r.text)
        except Exception, e:
            assert e is None

        if not self.last_statistic.setdefault(deployment_id, []) or \
            self.last_statistic[deployment_id][-1] != str(r.text):
                self.last_statistic[deployment_id].append(str(r.text))
                logger.info("Statistics contains new entry: " + str(r.text))

        return json.loads(r.text)

    def check_expected_status(self, deployment_id, expected_status, expected_count, max_wait=120, polling_frequency=0.2):
        timeout = time.time() + max_wait
        seen = set()

        while time.time() <= timeout:
            time.sleep(polling_frequency)

            data = self.get_statistics(deployment_id)
            seen.add(str(data))

            if data[expected_status] != expected_count:
                continue
            else:
                return

        if time.time() > timeout:
            pytest.fail("Never found: %s:%s, only seen: %s" % (expected_status, expected_count, str(seen)))
