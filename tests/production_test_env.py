#!/usr/bin/env python2.7

import os
import sys
import subprocess
import argparse
import conftest
import common
from MenderAPI import auth, adm
sys.path.insert(0, "./tests")
from common_update import common_update_procedure

parser = argparse.ArgumentParser(description='Helper script to bring up production env and provision for upgrade testing')

parser.add_argument('--start', dest='start', action='store_true',
                    help='start production environment')

parser.add_argument('--kill', dest='kill', action='store_true',
                    help='destroy production environment')

parser.add_argument('--test-deployment', dest='deploy', action='store_true',
                    help='start testing upgrade test procedure (used for upgrade testing)')

conftest.docker_compose_instance = "testprod"

if len(sys.argv) == 1:
    parser.print_help()
    sys.exit(1)

args = parser.parse_args()

def setup_docker_volumes():
    docker_volumes = ["mender-artifacts",
                      "mender-deployments-db",
                      "mender-deviceadm-db",
                      "mender-deviceauth-db",
                      "mender-dynomite-db",
                      "mender-elasticsearch-db",
                      "mender-inventory-db",
                      "mender-useradm-db"]

    for volume in docker_volumes:
        ret = subprocess.call(["docker", "volume", "create", "--name=%s" % volume])
        assert ret == 0, "failed to create docker volumes"

if args.start:
    # create volumes required for production environment
    setup_docker_volumes()

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
                           "-p", "testprod",
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

    # make sure artifact tool in current workdir is being used
    os.environ["PATH"] = os.path.dirname(os.path.realpath(__file__)) + "/downloaded-tools" + os.pathsep + os.environ["PATH"]

    # perform upgrade
    devices_to_update = list(set([device["device_id"] for device in adm.get_devices_status("accepted", expected_devices=10)]))
    deployment_id, artifact_id = common_update_procedure("core-image-full-cmdline-vexpress-qemu.ext4", device_type="test", devices=devices_to_update)

    print("deployment_id=%s" % deployment_id)
    print("artifact_id=%s" % artifact_id)
    print("devices=%d" % len(devices))

if args.kill:
    subprocess.call(["docker-compose", "-p", "testprod", "down", "-v"])
