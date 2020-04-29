#!/usr/bin/env python3

import os
import sys
import subprocess
import argparse

parser = argparse.ArgumentParser(description="Helper script to bring up production env")

parser.add_argument(
    "--start", dest="start", action="store_true", help="start production environment"
)

parser.add_argument(
    "--kill", dest="kill", action="store_true", help="destroy production environment"
)

parser.add_argument(
    "--docker-compose-instance",
    required=True,
    help="The docker-compose instance to use (project name)",
)

if len(sys.argv) == 1:
    parser.print_help()
    sys.exit(1)

args = parser.parse_args()

docker_compose_project = args.docker_compose_instance


def fill_production_template():

    # copy production environment yml file
    subprocess.check_output(
        ["cp", "production/config/prod.yml.template", "production-testing-env.yml"],
        cwd="../",
    )
    subprocess.check_output(
        "sed -i 's,/production/,/,g' ../production-testing-env.yml", shell=True
    )
    subprocess.check_output(
        "sed -i 's/ALLOWED_HOSTS: my-gateway-dns-name/ALLOWED_HOSTS: ~./' ../production-testing-env.yml",
        shell=True,
    )
    subprocess.check_output(
        "sed -i '0,/set-my-alias-here.com/s/set-my-alias-here.com/localhost/' ../production-testing-env.yml",
        shell=True,
    )
    subprocess.check_output(
        "sed -i 's|DEPLOYMENTS_AWS_URI:.*|DEPLOYMENTS_AWS_URI: https://localhost:9000|' ../production-testing-env.yml",
        shell=True,
    )
    subprocess.check_output(
        "sed -i 's/MINIO_ACCESS_KEY:.*/MINIO_ACCESS_KEY: Q3AM3UQ867SPQQA43P2F/' ../production-testing-env.yml",
        shell=True,
    )
    subprocess.check_output(
        "sed -i 's/MINIO_SECRET_KEY:.*/MINIO_SECRET_KEY: abcssadasdssado798dsfjhkksd/' ../production-testing-env.yml",
        shell=True,
    )
    subprocess.check_output(
        "sed -i 's/DEPLOYMENTS_AWS_AUTH_KEY:.*/DEPLOYMENTS_AWS_AUTH_KEY: Q3AM3UQ867SPQQA43P2F/' ../production-testing-env.yml",
        shell=True,
    )
    subprocess.check_output(
        "sed -i 's/DEPLOYMENTS_AWS_AUTH_SECRET:.*/DEPLOYMENTS_AWS_AUTH_SECRET: abcssadasdssado798dsfjhkksd/' ../production-testing-env.yml",
        shell=True,
    )


def setup_docker_volumes():
    docker_volumes = [
        "mender-artifacts",
        "mender-db",
    ]

    for volume in docker_volumes:
        ret = subprocess.call(["docker", "volume", "create", "--name=%s" % volume])
        assert ret == 0, "failed to create docker volumes"


if args.start:
    # create volumes required for production environment
    setup_docker_volumes()

    # add keys for production environment
    if not os.path.exists("../keys-generated"):
        ret = subprocess.call(
            ["./keygen"],
            env={"CERT_API_CN": "localhost", "CERT_STORAGE_CN": "localhost"},
            cwd="../",
        )
        assert ret == 0, "failed to generate keys"
    fill_production_template()

    # start docker-compose
    ret = subprocess.call(
        [
            "docker-compose",
            "-p",
            docker_compose_project,
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.storage.minio.yml",
            "-f",
            "./production-testing-env.yml",
            "up",
            "-d",
        ],
        cwd="../",
    )

    assert ret == 0, "failed to start docker-compose"

if args.kill:
    subprocess.call(
        [
            "docker-compose",
            "-p",
            docker_compose_project,
            "down",
            "-v",
            "--remove-orphans",
        ]
    )
