#!/usr/bin/env python3
# Copyright 2021 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

# This script is a modified snapshot of the script with the same name in
# meta-mender/meta-mender-qemu/scripts/docker. It is used for hijacking the
# entrypoint of older Mender client releases making sure that the
# mender-connect configuration file is updated in accordance with mender.conf
# when provisioning a new certificate. Moreover, both the active and inactive
# partition is overwritten.

import argparse
import json
import os
import stat
import sys
import subprocess
from pathlib import PurePath


def get(remote_path, local_path, rootfs):
    subprocess.check_call(
        ["debugfs", "-R", "dump -p %s %s" % (remote_path, local_path), rootfs],
        stderr=subprocess.STDOUT,
    )


def put(local_path, remote_path, rootfs, remote_path_mkdir_p=False):
    proc = subprocess.Popen(
        ["debugfs", "-w", rootfs], stdin=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    if remote_path_mkdir_p:
        # Create parent directories sequentially, to simulate a "mkdir -p" on the final dir
        parent_dirs = list(PurePath(remote_path).parents)[::-1][1:]
        for parent in parent_dirs:
            proc.stdin.write(("mkdir %s\n" % parent).encode())
    proc.stdin.write(("cd %s\n" % os.path.dirname(remote_path)).encode())
    proc.stdin.write(("rm %s\n" % os.path.basename(remote_path)).encode())
    proc.stdin.write(
        ("write %s %s\n" % (local_path, os.path.basename(remote_path))).encode()
    )
    proc.stdin.close()
    ret = proc.wait()
    assert ret == 0


def extract_ext4(img, rootfs):
    return _manipulate_ext4(img=img, rootfs=rootfs, write=False)


def insert_ext4(img, rootfs):
    return _manipulate_ext4(img=img, rootfs=rootfs, write=True)


def _manipulate_ext4(img, rootfs, write):
    # calls partx with --show --bytes --noheadings, sample output:
    #
    # $ partx -sbg core-image-full-cmdline-vexpress-qemu.sdimg
    # NR  START    END SECTORS      SIZE NAME UUID  <-- NOTE: this is not shown
    # 1  49152  81919   32768  16777216      a38e337d-01
    # 2  81920 294911  212992 109051904      a38e337d-02
    # 3 294912 507903  212992 109051904      a38e337d-03
    # 4 507904 770047  262144 134217728      a38e337d-04
    output = subprocess.check_output(["partx", "-sbg", img])
    done = False
    for line in output.decode().split("\n"):
        columns = line.split()
        # This blindly assumes that rootfs is on partition 2 and 3.
        if write:
            if columns[0] in ["2", "3"]:
                subprocess.check_call(
                    [
                        "dd",
                        "if=%s" % rootfs,
                        "of=%s" % img,
                        "seek=%s" % columns[1],
                        "count=%d" % (int(columns[3])),
                        "conv=notrunc",
                    ],
                    stderr=subprocess.STDOUT,
                )
                if done:
                    break
                else:
                    done = not done
        elif columns[0] == "2":
            subprocess.check_call(
                [
                    "dd",
                    "if=%s" % img,
                    "of=%s" % rootfs,
                    "skip=%s" % columns[1],
                    "count=%d" % (int(columns[3])),
                ],
                stderr=subprocess.STDOUT,
            )
            break
    else:
        raise Exception("%s not found in partx output: %s" % (img, output))


def update_config(rootfs, key, value, filename="mender.conf"):
    get(
        local_path=filename, remote_path="/etc/mender/" + filename, rootfs=rootfs,
    )
    with open(filename) as fd:
        conf = json.load(fd)
    conf[key] = value
    with open(filename, "w") as fd:
        json.dump(conf, fd, indent=4, sort_keys=True)
    put(
        local_path=filename, remote_path="/etc/mender/" + filename, rootfs=rootfs,
    )
    os.unlink(filename)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--img", help="Img to modify", required=True)
    parser.add_argument(
        "--docker-ip", help="IP (in IP/netmask format) to report as Docker IP"
    )
    parser.add_argument("--tenant-token", help="tenant token to use by client")
    parser.add_argument("--server-crt", help="server.crt file to put in image")
    parser.add_argument("--server-url", help="Server address to put in configuration")
    parser.add_argument("--verify-key", help="Key used to verify signed image")
    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        return

    # Extract ext4 image from img.
    rootfs = "%s.ext4" % args.img
    extract_ext4(img=args.img, rootfs=rootfs)

    if args.tenant_token:
        update_config(rootfs, "TenantToken", args.tenant_token)

    if args.server_crt:
        put(
            local_path=args.server_crt,
            remote_path="/etc/ssl/certs/docker.mender.io.crt",
            rootfs=rootfs,
        )

    if args.server_url:
        update_config(rootfs, "ServerURL", args.server_url)

    if args.verify_key:
        key_img_location = "/etc/mender/artifact-verify-key.pem"
        if not os.path.exists(args.verify_key):
            raise SystemExit("failed to load file: " + args.verify_key)
        put(local_path=args.verify_key, remote_path=key_img_location, rootfs=rootfs)
        update_config(rootfs, "ArtifactVerifyKey", key_img_location)

    if args.docker_ip:
        with open("mender-inventory-docker-ip", "w") as fd:
            fd.write(
                """#!/bin/sh
cat <<EOF
network_interfaces=docker
ipv4_docker=%s
EOF
"""
                % args.docker_ip
            )
        os.chmod(
            "mender-inventory-docker-ip",
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
        put(
            local_path="mender-inventory-docker-ip",
            remote_path="/usr/share/mender/inventory/mender-inventory-docker-ip",
            rootfs=rootfs,
        )
        os.unlink("mender-inventory-docker-ip")

    # Put back ext4 image into img.
    insert_ext4(img=args.img, rootfs=rootfs)
    os.unlink(rootfs)


if __name__ == "__main__":
    main()
