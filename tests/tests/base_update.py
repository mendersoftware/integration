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

import pytest
import time
from deployments import Deployments
from admission import Admission
from common import *
from helpers import Helpers
import random


def base_update_proceduce(install_image, name, regnerate_image_id=True, device_type="TestDevice", checksum="abc123", broken_image=False):

    if broken_image:
        yocto_id = "broken_image_" + str(random.randint(0, 999999))
    elif regnerate_image_id:
        yocto_id = Helpers.yocto_id_randomize(install_image)
    else:
        yocto_id = Helpers.yocto_id_from_ext4(install_image)

    if name is None:
        name = "imageid-" + str(random.randint(1, 9999999999))

    upload_request_url = Deployments.post_image_meta(name=name,
                                                     checksum=checksum,
                                                     device_type=device_type,
                                                     yocto_id=yocto_id)

    Deployments.upload_image(upload_request_url, install_image)
    devices_accepted_id = [device["id"] for device in Admission.get_devices_status("accepted")]

    deployment_id = Deployments.trigger_deployment(name="New valid update",
                                                   artifact_name=name,
                                                   devices=devices_accepted_id)
    return deployment_id, yocto_id
