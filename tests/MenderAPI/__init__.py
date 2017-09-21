import os
import logging

api_version = os.getenv("MENDER_API_VERSION", "v1")

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# don't complain about non-verified ssl connections
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from common import *
from common_docker import *

import time
import json
import pytest
import os
import authentication
import admission
import deployments
import artifacts
import inventory
import device_authentication

logger = logging.getLogger('root')

auth = authentication.Authentication()
adm = admission.Admission(auth)
deploy = deployments.Deployments(auth, adm)
image = artifacts.Artifacts()
inv = inventory.Inventory(auth)
deviceauth = device_authentication.DeviceAuthentication(auth)
# -- When adding something here, also add a reset method and add it below --


def reset_mender_api():
    auth.reset()
    adm.reset()
    deploy.reset()
    image.reset()
    inv.reset()
    deviceauth.reset()


reset_mender_api()
