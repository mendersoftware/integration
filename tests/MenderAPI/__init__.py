import os
import logging

api_version = os.getenv("MENDER_API_VERSION", "0.1")
gateway = os.getenv("MENDER_API_GATEWAY", "127.0.0.1:8080")

logger = logging.getLogger()

logger.setLevel(logging.DEBUG)
#logging.getLogger("paramiko").setLevel(logging.DEBUG)

logging.info("Setting api_version as: " + api_version)
logging.info("Setting gateway as: " + gateway)

import admission
import deployments
import artifacts

adm = admission.Admission()
deploy = deployments.Deployments()
image = artifacts.Artifacts()
