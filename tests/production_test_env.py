#!/usr/bin/env python2.7

import os
import sys
import subprocess
import argparse
import shutil

sys.path.insert(0, "../")
from tests import conftest
from tests import common
from tests.MenderAPI import auth, auth_v2
from tests.tests import common_update

parser = argparse.ArgumentParser(description='Helper script to bring up production env and provision for upgrade testing')

parser.add_argument('--start', dest='start', action='store_true',
                    help='start production environment')

parser.add_argument('--kill', dest='kill', action='store_true',
                    help='destroy production environment')

parser.add_argument('--test-deployment', dest='deploy', action='store_true',
                    help='start testing upgrade test procedure (used for upgrade testing)')

parser.add_argument('--docker-compose-instance', required=True,
                    help='The docker-compose instance to use (project name)')

if len(sys.argv) == 1:
    parser.print_help()
    sys.exit(1)

args = parser.parse_args()

conftest.docker_compose_instance = args.docker_compose_instance

def fill_production_template():

    # copy production environment yml file
    subprocess.check_output(["cp", "production/config/prod.yml.template", "production-testing-env.yml"], cwd="../")
    subprocess.check_output("sed -i 's,/production/,/,g' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i 's/ALLOWED_HOSTS: my-gateway-dns-name/ALLOWED_HOSTS: ~./' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i '0,/set-my-alias-here.com/s/set-my-alias-here.com/localhost/' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i 's|DEPLOYMENTS_AWS_URI:.*|DEPLOYMENTS_AWS_URI: https://s3.docker.mender.io:9000|' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i 's/MINIO_ACCESS_KEY:.*/MINIO_ACCESS_KEY: Q3AM3UQ867SPQQA43P2F/' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i 's/MINIO_SECRET_KEY:.*/MINIO_SECRET_KEY: abcssadasdssado798dsfjhkksd/' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i 's,/export,/exportoff,g' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i 's/DEPLOYMENTS_AWS_AUTH_KEY:.*/DEPLOYMENTS_AWS_AUTH_KEY: Q3AM3UQ867SPQQA43P2F/' ../production-testing-env.yml", shell=True)
    subprocess.check_output("sed -i 's/DEPLOYMENTS_AWS_AUTH_SECRET:.*/DEPLOYMENTS_AWS_AUTH_SECRET: abcssadasdssado798dsfjhkksd/' ../production-testing-env.yml", shell=True)


def setup_docker_volumes():
    docker_volumes = ["mender-artifacts",
                      "mender-redis-db",
                      "mender-elasticsearch-db",
                      "mender-db"]

    for volume in docker_volumes:
        ret = subprocess.call(["docker", "volume", "create", "--name=%s" % volume])
        assert ret == 0, "failed to create docker volumes"

if args.start:
    # create volumes required for production environment
    setup_docker_volumes()

    # add keys for production environment
    if not os.path.exists("../keys-generated"):
        ret = subprocess.call(["./keygen"], env={"CERT_API_CN": "s3.docker.mender.io",
                                                 "CERT_STORAGE_CN": "s3.docker.mender.io"},
                              cwd="../")
        assert ret == 0, "failed to generate keys"
    fill_production_template()

    # start docker-compose
    timeoutenv=os.environ.copy()
    timeoutenv["COMPOSE_HTTP_TIMEOUT"]="1024"
    timeoutenv["DOCKER_CLIENT_TIMEOUT"]="1024"
    ret = subprocess.call(["docker-compose",
                           "-p", conftest.docker_compose_instance,
                           "-f", "docker-compose.yml",
                           "-f", "docker-compose.storage.minio.yml",
                           "-f", "./production-testing-env.yml",
                           "up", "-d"],
                          cwd="../",
                          env=timeoutenv)
    out = subprocess.check_output("/builds/Northern.tech/Mender/integration/wait-for-all %s" % conftest.docker_compose_instance, shell=True)

    assert ret == 0, "failed to start docker-compose"

if args.deploy:
    # create account for management api
    auth.get_auth_token()

    # wait for 10 devices to be available
    devices = auth_v2.get_devices(10)
    assert len(devices) == 10

    # accept all devices
    for d in devices:
        auth_v2.set_device_auth_set_status(d["id"], d["auth_sets"][0]["id"], "accepted")

    # make sure artifact tool in current workdir is being used
    os.environ["PATH"] = os.path.dirname(os.path.realpath(__file__)) + "/downloaded-tools" + os.pathsep + os.environ["PATH"]

    # perform upgrade
    devices_to_update = list(set([device["id"] for device in auth_v2.get_devices_status("accepted", expected_devices=10)]))
    deployment_id, artifact_id = common_update.common_update_procedure("core-image-full-cmdline-%s.ext4" % machine_name, device_type="test", devices=devices_to_update)

    print("deployment_id=%s" % deployment_id)
    print("artifact_id=%s" % artifact_id)
    print("devices=%d" % len(devices))

if args.kill:
    subprocess.call(["docker-compose", "-p", conftest.docker_compose_instance, "down", "-v", "--remove-orphans"])
