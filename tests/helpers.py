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

import time
from fabric.api import *
from fabric.network import disconnect_all
import subprocess
import logging
import random
import tempfile
import pytest
import os
from fabric.contrib.files import exists


logger = logging.getLogger()

class Helpers:
    artifact_info_file = "/etc/mender/artifact_info"
    artifact_prefix = "artifact_name"



    @classmethod
    def yocto_id_from_ext4(self, filename):
        try:
            cmd = "e2tail %s:%s | sed -n 's/^%s=//p'" % (filename, abself.artifact_info_file)
            output = subprocess.check_output(cmd, shell=True).strip()
            logging.info("Running: " + cmd + " returned: " + output)
            return output

        except subprocess.CalledProcessError:
            pytest.fail("Unable to read: %s, is it a broken image?" % (filename))

        except Exception, e:
            pytest.fail("Unexpected error trying to read ext4 image: %s, error: %s" % (filename, str(e)))

    @classmethod
    def yocto_id_installed_on_machine(self):
        cmd = "cat %s | sed -n 's/^%s=//p'" % (self.artifact_info_file, self.artifact_prefix)
        output = run(cmd).strip()
        return output

    @classmethod
    def artifact_id_randomize(self, install_image, device_type="vexpress-qemu", specific_image_id=None):

        if specific_image_id:
            imageid = specific_image_id
        else:
            imageid = "mender-%s" % str(random.randint(0,99999999))

        config_file = r"""%s=%s""" % (self.artifact_prefix, imageid)
        tfile = tempfile.NamedTemporaryFile(delete=False)
        tfile.write(config_file)
        tfile.close()

        try:
            cmd = "e2cp %s %s:%s" % (tfile.name, install_image, self.artifact_info_file)
            output = subprocess.check_output(cmd, shell=True).strip()
            logging.info("Running: " + cmd + " returned: " + output)

        except subprocess.CalledProcessError:
            pytest.fail("Trying to modify ext4 image failed, probably because it's not a valid image.")

        except Exception, e:
            pytest.fail("Unexpted error trying to modify ext4 image: %s, error: %s" % (install_image, str(e)))

        finally:
            os.remove(tfile.name)

        return imageid

    @staticmethod
    def get_active_partition():
        cmd = "mount | awk '/on \/ / { print $1}'"
        with quiet():
            active = run(cmd)
        return active.strip()

    @staticmethod
    def get_passive_partition():
        active = Helpers.get_active_partition()
        cmd = "fdisk -l | grep $(blockdev --getsz %s) | grep -v %s | awk '{ print $1}'" % (active, active)
        with quiet():
            passive = run(cmd)
        return passive.strip()

    @staticmethod
    # simulate broken internet by drop packets to gateway and fakes3 server
    def gateway_connectivity(accessible):
        try:
            with settings(hide('everything'), warn_only=True):
                hosts = ["mender-artifact-storage.localhost", "mender-api-gateway"]
                for h in hosts:
                    gateway_ip = run("nslookup %s | tail -n 1  | grep -oE '((1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])\.){3}(1?[0-9][0-9]?|2[0-4][0-9]|25[0-5])'" % (h)).strip()

                    if accessible:
                        logger.info("Allowing network communication to %s" % h)
                        run("iptables -D INPUT -s %s -j DROP" % (gateway_ip))
                        run("iptables -D OUTPUT -s %s -j DROP" % (gateway_ip))
                    else:
                        logger.info("Disallowing network communication to %s" % h)
                        run("iptables -I INPUT 1 -s %s -j DROP" % gateway_ip)
                        run("iptables -I OUTPUT 1 -s %s -j DROP" % gateway_ip)
        except Exception, e:
            logging.info("Exception while messing with network connectivity: " + e)

    @staticmethod
    def verify_reboot_performed(max_wait=60*10):
        tfile = "/tmp/mender-testing.%s" % (random.randint(1, 999999))
        cmd = "touch %s" % (tfile)
        try:
            with settings(quiet()):
                run(cmd)
        except BaseException:
            logging.critical("Failed to touch /tmp/ folder, is the device already rebooting?")
            time.sleep(max_wait)
            return

        timeout = time.time() + max_wait

        while time.time() <= timeout:
            time.sleep(15)

            with settings(warn_only=True):
                try:
                    if exists(tfile):
                        logging.debug("temp. file still exists, device hasn't rebooted.")
                        continue
                    else:
                        logging.debug("temp. file no longer exists, device has rebooted.")
                        time.sleep(5)
                    return

                except BaseException:
                    logging.debug("system exit was caught, this is probably because SSH connectivity is broken while the system is rebooting")
                    continue

        if time.time() > timeout:
            pytest.fail("Device never rebooted!")

    @staticmethod
    def verify_reboot_not_performed(wait=60):
        with quiet():
            try:
                cmd = "cat /proc/uptime | awk {'print $1'}"
                t1 = float(run(cmd).strip())
                time.sleep(wait)
                t2 = float(run(cmd).strip())
            except:
                pytest.fail("A reboot was performed when it was not expected")
        assert t2 > t1
