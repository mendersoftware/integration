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
import inventory

import requests
from requests.auth import HTTPBasicAuth

def get_auth_token():
    email = "admin@admin.net"
    password = "averyverystrongpasswordthatyouwillneverguess!haha!"

    def get_header(t):
        return {"Authorization": "Bearer " + str(t)}

    r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (gateway, api_version), verify=False)
    auth_header = get_header(r.text)

    if r.status_code == 200:
        auth_header = get_header(r.text)
        r = requests.post("https://%s/api/management/%s/useradm/users/initial" % (gateway, api_version), headers=auth_header, verify=False, json={"email": email, "password": password})
        assert r.status_code == 201

    r = requests.post("https://%s/api/management/%s/useradm/auth/login" % (gateway, api_version), verify=False, auth=HTTPBasicAuth(email, password))
    assert r.status_code == 200

    auth_header = get_header(r.text)
    logging.info("Using Authorization headers: " + str(r.text))
    return auth_header

auth_header = get_auth_token()

adm = admission.Admission(auth_header)
deploy = deployments.Deployments(auth_header)
image = artifacts.Artifacts()
inv = inventory.Inventory(auth_header)
