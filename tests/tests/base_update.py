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

from deployments import Deployments
from admission import Admission
from common import *
from helpers import Helpers
from artifacts import Artifacts
import random


def base_update_proceduce(install_image, name, regnerate_image_id=True, device_type="vexpress-qemu", checksum="abc123", broken_image=False):

    if broken_image:
        artifact_id = "broken_image_" + str(random.randint(0, 999999))
    elif regnerate_image_id:
        artifact_id = Helpers.artifact_id_randomize(install_image)
        logging.debug("Randomized image id: " + artifact_id)
    else:
        artifact_id = Helpers.yocto_id_from_ext4(install_image)

    if name is None:
        name = "imageid-" + str(random.randint(1, 9999999999))

    # create atrifact
    artifact_file = "artifact.mender"
    created = Artifacts.make_artifact(install_image, device_type, artifact_id, artifact_file)
    if (created):
        Deployments.upload_image(name, "artifact.mender")
        devices_accepted_id = [device["id"] for device in Admission.get_devices_status("accepted")]
        deployment_id = Deployments.trigger_deployment(name="New valid update",
                                                       artifact_name=name,
                                                       devices=devices_accepted_id)

        # remove the artifact file
        os.remove(artifact_file)
        return deployment_id, artifact_id

    logging.error("error creating artifact")
