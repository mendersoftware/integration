import os
import logging

api_version = os.getenv("MENDER_API_VERSION", "v1")

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# don't complain about non-verified ssl connections
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from requests_helpers import requests_retry

from common import *
from common_docker import *

import time
import json
import pytest
import os
import authentication
import deployments
import artifacts
import inventory
import auth_v2 as auth_v2_mod

logger = logging.getLogger('root')

auth = authentication.Authentication()
auth_v2 = auth_v2_mod.DeviceAuthV2(auth)
deploy = deployments.Deployments(auth, auth_v2)
image = artifacts.Artifacts()
inv = inventory.Inventory(auth)
# -- When adding something here, also add a reset method and add it below --


def reset_mender_api():
    auth.reset()
    auth_v2.reset()
    deploy.reset()
    image.reset()
    inv.reset()


reset_mender_api()
