#!/usr/bin/python
# Copyright 2017 Northern.tech AS
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

from MenderAPI import *

class Deployments(object):
    # track the last statistic for a deployment id
    last_statistic = {}
    auth = None
    adm = None

    def __init__(self, auth, adm):
        self.reset()
        self.auth = auth
        self.adm = adm

    def reset(self):
        # Reset all temporary values.
        self.last_statistic = Deployments.last_statistic

    def get_deployments_base_path(self):
        return "https://%s/api/management/%s/deployments/" % (get_mender_gateway(), api_version)

    def upload_image(self, filename, description="abc"):
        image_path_url = self.get_deployments_base_path() + "artifacts"

        r = requests.post(image_path_url,
                          verify=False,
                          headers=self.auth.get_auth_token(),
                          files=(
                              ("description", (None, description)),
                              ("size", (None, str(os.path.getsize(filename)))),
                              ("artifact", (filename, open(filename), "application/octet-stream"))
                          ))

        logger.info("Received image upload status code: " + str(r.status_code) + " with payload: " + str(r.text))
        assert r.status_code == requests.status_codes.codes.created
        return r.headers["location"]

    def trigger_deployment(self, name, artifact_name, devices):
        deployments_path_url = self.get_deployments_base_path() + "deployments"

        trigger_data = {"name": name,
                        "artifact_name": artifact_name,
                        "devices": devices}

        headers = {'Content-Type': 'application/json'}
        headers.update(self.auth.get_auth_token())

        r = requests.post(deployments_path_url, headers=headers,
                          data=json.dumps(trigger_data), verify=False)

        logger.debug("triggering deployment with: " + json.dumps(trigger_data))
        logging.info("deployment returned: " + r.text)
        assert r.status_code == requests.status_codes.codes.created

        deployment_id = str(r.headers['Location'].split("/")[-1])
        logger.info("deployment [%s] triggered for device [%s]" % (deployment_id, devices))

        return deployment_id

    def get_logs(self, device, deployment_id, expected_status=200):
        deployments_logs_url = self.get_deployments_base_path() + "deployments/%s/devices/%s/log" % (deployment_id, device)
        r = requests.get(deployments_logs_url, headers=self.auth.get_auth_token(), verify=False)
        assert r.status_code == expected_status

        logger.info("Logs contain " + str(r.text))
        return r.text

    def get_status(self, status=None):
        deployments_status_url = self.get_deployments_base_path() + "deployments"

        if status:
            deployments_status_url += "?status=%s" % (status)

        r = requests.get(deployments_status_url, headers=self.auth.get_auth_token(), verify=False)

        assert r.status_code == requests.status_codes.codes.ok
        return json.loads(r.text)

    def get_statistics(self, deployment_id):
        deployments_statistics_url = self.get_deployments_base_path() + "deployments/%s/statistics" % (deployment_id)
        r = requests.get(deployments_statistics_url, headers=self.auth.get_auth_token(), verify=False)
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

    def check_expected_status(self, expected_status, deployment_id, max_wait=60*60, polling_frequency=.2):
        timeout = time.time() + max_wait

        while time.time() <= timeout:
            data = self.get_status(status=expected_status)

            for deployment in data:
                if deployment["id"] == deployment_id:
                    logger.info("got expected deployment status (%s) for: %s" % (expected_status, deployment_id))
                    return
            else:
                time.sleep(polling_frequency)
                continue

        if time.time() > timeout:
            pytest.fail("Never found status: %s for %s after %d seconds" % (expected_status, deployment_id, max_wait))


    def check_expected_statistics(self, deployment_id, expected_status, expected_count, max_wait=60*60, polling_frequency=.2):
        timeout = time.time() + max_wait
        seen = set()

        while time.time() <= timeout:
            time.sleep(polling_frequency)

            data = self.get_statistics(deployment_id)
            seen.add(str(data))

            if int(data["failure"]) > 0 and expected_status != "failure":
                all_failed_logs = ""
                for device in self.adm.get_devices():
                    try:
                        all_failed_logs += self.get_logs(device["device_id"], deployment_id) + "\n" * 5
                    except Exception, e:
                        logger.warn("failed to get logs.")

                pytest.fail("deployment unexpectedly failed, here are the deployment logs: \n\n %s" % (all_failed_logs))

            if data[expected_status] == expected_count:
                return
            continue

        if time.time() > timeout:
            pytest.fail("Never found: %s:%s, only seen: %s after %d seconds" % (expected_status, expected_count, str(seen), max_wait))

    def get_deployment_overview(self, deployment_id):
        deployments_overview_url = self.get_deployments_base_path() + "deployments/%s/devices" % (deployment_id)
        r = requests.get(deployments_overview_url, headers=self.auth.get_auth_token(), verify=False)
        assert r.status_code == requests.status_codes.codes.ok
        return r.json()

    def get_deployment(self, deployment_id):
        deployments_url = self.get_deployments_base_path() + "deployments/%s" % (deployment_id)
        r = requests.get(deployments_url, headers=self.auth.get_auth_token(), verify=False)
        assert r.status_code == requests.status_codes.codes.ok
        return r.json()

    def get_artifact_details(self, artifact_id):
        artifact_url = self.get_deployments_base_path() + "artifacts/%s" % (artifact_id)
        r = requests.get(artifact_url, headers=self.auth.get_auth_token(), verify=False)
        assert r.status_code == requests.status_codes.codes.ok
        return r.json()

    def get_artifacts(self):
        artifact_url = self.get_deployments_base_path() + "artifacts"
        r = requests.get(artifact_url, headers=self.auth.get_auth_token(), verify=False)
        assert r.status_code == requests.status_codes.codes.ok
        return r.json()

    def abort(self, deployment_id):
        deployment_abort_url = self.get_deployments_base_path() + "deployments/%s/status" % (deployment_id)
        r = requests.put(deployment_abort_url, verify=False, headers=self.auth.get_auth_token(), json={"status": "aborted"})
        assert r.status_code == requests.status_codes.codes.no_content

    def abort_finished_deployment(self, deployment_id):
        deployment_abort_url = self.get_deployments_base_path() + "deployments/%s/status" % (deployment_id)
        r = requests.put(deployment_abort_url, verify=False, headers=self.auth.get_auth_token(), json={"status": "aborted"})
        assert r.status_code == requests.status_codes.codes.unprocessable_entity
