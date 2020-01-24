import os
import logging

api_version = os.getenv("MENDER_API_VERSION", "v1")
logger = logging.getLogger()

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# don't complain about non-verified ssl connections
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Define get funtion before the below imports to avoid circular dependency
container_manager = None
def get_container_manager():
    return container_manager

from .authentication import Authentication
from .deployments import Deployments
from .artifacts import Artifacts
from .inventory import Inventory
from .auth_v2 import DeviceAuthV2

auth = Authentication()
auth_v2 = DeviceAuthV2(auth)
deploy = Deployments(auth, auth_v2)
image = Artifacts()
inv = Inventory(auth)
# -- When adding something here, also add a reset method and add it below --


def reset_mender_api(manager=None):
    auth.reset()
    auth_v2.reset()
    deploy.reset()
    image.reset()
    inv.reset()
    global container_manager
    container_manager = manager


reset_mender_api()
