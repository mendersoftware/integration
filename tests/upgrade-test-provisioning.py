#!/usr/bin/env python2.7
import argparse
import os
import sys
import subprocess
import conftest  # needed even though not referenced
import common  # needed even though not referenced
from MenderAPI import auth, adm
sys.path.insert(0, "./tests")
from common_update import common_update_proceduce

# make sure artifact tool is available
os.environ["PATH"] += os.pathsep + os.path.dirname(os.path.realpath(__file__)) + "/downloaded-tools"

parser = argparse.ArgumentParser(description='Helper script to bring up production env and provision for upgrade testing')
parser.add_argument('--start', dest='start', action='store_true',
                    help='start production environment')

parser.add_argument('--deploy', dest='deploy', action='store_true',
                    help='start testing upgrade test procedure (used for upgrade testing)')

conftest.docker_compose_instance = "testprod"

if len(sys.argv) == 1:
    parser.print_help()
    sys.exit(1)

args = parser.parse_args()


if args.start:
    # add keys for production environment
    if not os.path.exists("../keys-generated"):
        ret = subprocess.call(["./keygen"], env={"CERT_API_CN": "localhost",
                                                 "CERT_STORAGE_CN": "localhost"},
                              cwd="../")
        assert ret == 0, "failed to generate keys"

    # copy production environment yml file
    if not os.path.exists("../production-testing-env.yml"):
        ret = subprocess.call(["cp", "extra/production-testing-env.yml", "."],
                              cwd="../")
        assert ret == 0, "failed to copy extra/production-testing-env.yml"

    # start docker-compose
    ret = subprocess.call(["docker-compose",
                           "-p", "test-prod",
                           "-f", "docker-compose.yml",
                           "-f", "docker-compose.storage.minio.yml",
                           "-f", "production-testing-env.yml",
                           "up", "-d"],
                          cwd="../")

    assert ret == 0, "failed to start docker-compose"

if args.deploy:
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
