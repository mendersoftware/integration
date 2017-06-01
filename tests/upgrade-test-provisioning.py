import os
import sys
import subprocess
import conftest #  needed even though not referenced
import common #  needed even though not referenced
from MenderAPI import auth, adm
sys.path.insert(0, "./tests")
from common_update import common_update_proceduce
os.environ["PATH"] += os.pathsep + os.path.dirname(os.path.realpath(__file__)) + "/downloaded-tools"

if sys.argv[1] == "start":
    # add keys for production environment
    if not os.path.exists("../keys-generated"):
        subprocess.call(["./keygen"], env={"CERT_API_CN": "localhost",
                                           "CERT_STORAGE_CN": "localhost"},
                                      cwd="../")

    # copy production environment yml file
    if not os.path.exists("../production-testing-env.yml"):
        subprocess.call(["cp", "extra/production-testing-env.yml", "."],
                        cwd="../")

    # start docker-compose
    subprocess.call(["docker-compose",
                     "-p", "test-prod",
                     "-f", "docker-compose.yml",
                     "-f", "docker-compose.storage.minio.yml",
                     "-f", "production-testing-env.yml",
                     "up", "-d"],
                    cwd="../")

if sys.argv[1] == "deploy":
    # create account for management api
    auth.get_auth_token()

    # wait for 10 devices to be available
    devices = adm.get_devices(10)
    assert len(devices) == 10

    # accept all devices
    for d in devices:
        adm.set_device_status(d["id"], "accepted")

    # perform upgrade
    devices_to_update = list(set([device["id"] for device in adm.get_devices_status("accepted", expected_devices=10)]))
    common_update_proceduce("core-image-full-cmdline-vexpress-qemu.ext4", device_type="test", devices=devices_to_update)
