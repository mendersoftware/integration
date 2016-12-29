import os
import logging

api_version = os.getenv("MENDER_API_VERSION", "0.1")
gateway = os.getenv("GATEWAY_IP_PORT", "127.0.0.1:8080")

logger = logging.getLogger()

logger.setLevel(logging.DEBUG)
#logging.getLogger("paramiko").setLevel(logging.DEBUG)

logging.info("Setting api_version as: " + api_version)
logging.info("Setting gateway as: " + gateway)

import admission
import deployments
import artifacts

import requests

r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (gateway, api_version), verify=False)
assert r.status_code == 200

s = requests.Session()
s.headers.update({"Authorization": 'Bearer ' + str(r.text)})
s.verify = False

logging.info("Using Authorization headers: " + str(r.text))
adm = admission.Admission(s)
deploy = deployments.Deployments(s)
image = artifacts.Artifacts()
