# Copyright 2020 Northern.tech AS
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
