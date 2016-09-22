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
import logging

class Deployments(object):

    @staticmethod
    def post_image_meta(name, device_type, yocto_id, description=None, checksum=None):
        meta_upload_path = "https://%s/api/integrations/%s/deployments/images" % (
            env.mender_gateway, env.api_version)

        image_meta = {"name": name,
                      "description": description,
                      "checksum": checksum,
                      "device_type": device_type,
                      "yocto_id": yocto_id}

        r = requests.post(meta_upload_path,
                          data=json.dumps(image_meta),
                          headers={'Content-Type': 'application/json'},
                          verify=False)
        print meta_upload_path, json.dumps(image_meta)
        assert r.status_code == requests.status_codes.codes.created
        return r.headers["location"]

    @staticmethod
    def upload_image(upload_request_url, filename):
        upload_location = requests.get(
            "https://%s/%s/upload" % (env.mender_gateway, upload_request_url),
            verify=False)

        assert upload_location.status_code == requests.status_codes.codes.ok
        aws_uri = upload_location.json()["uri"]
        aws_uri = aws_uri.replace("\u0026", "&")
        r = requests.put(str(aws_uri), data=open(filename, 'rb'), headers={'content-type': 'application/octet-stream'})
        assert r.status_code == requests.status_codes.codes.ok

    @staticmethod
    def trigger_deployment(name, artifact_name, devices):
        trigger_deploy_path = "https://%s/api/integrations/%s/deployments/deployments" % (
            env.mender_gateway, env.api_version)

        trigger_data = {"name": name,
                        "artifact_name": artifact_name,
                        "devices": devices}

        headers = {'Content-Type': 'application/json'}

        r = requests.post(trigger_deploy_path, headers=headers,
                          data=json.dumps(trigger_data), verify=False)
        print trigger_deploy_path, json.dumps(trigger_data)
        assert r.status_code == requests.status_codes.codes.created

        deployment_id = str(r.headers['Location'].split("/")[-1])
        logging.info("Deployment id is: " + deployment_id)

        return deployment_id

    @staticmethod
    def get_logs(device, deployment_id, expected_status=200):
        get_logs_url = "https://%s/api/integrations/%s/deployments/deployments/%s/devices/%s/log" % (env.mender_gateway, env.api_version, deployment_id, device)
        r = requests.get(get_logs_url, verify=False)
        assert r.status_code == expected_status

        logging.info("Logs contain " + str(r.text))
        return r.text

    @staticmethod
    def get_statistics(deployment_id):
        r = requests.get("https://%s/api/integrations/%s/deployments/deployments/%s/statistics" % (env.mender_gateway, env.api_version, deployment_id), verify=False)
        assert r.status_code == requests.status_codes.codes.ok

        try:
            json.loads(r.text)
        except Exception, e:
            assert e is None

        logging.info("Statistics contain: " + str(r.text))
        return json.loads(r.text)

    @staticmethod
    def check_expected_status(deployment_id, expected_status, expected_count, max_wait=120, polling_frequency=0.2):
        timeout = time.time() + max_wait
        seen = set()

        while time.time() <= timeout:
            time.sleep(polling_frequency)

            data = Deployments.get_statistics(deployment_id)
            seen.add(str(data))

            if data[expected_status] != expected_count:
                continue
            else:
                return

        if time.time() > timeout:
            pytest.fail("Never found: %s:%s, only seen: %s" % (expected_status, expected_count, str(seen)))
