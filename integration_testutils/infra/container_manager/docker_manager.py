# Copyright 2022 Northern.tech AS
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
import subprocess
import logging

from .base import BaseContainerManagerNamespace

logger = logging.getLogger()


class DockerNamespace(BaseContainerManagerNamespace):
    def __init__(self, name):
        BaseContainerManagerNamespace.__init__(self, name)

    def setup(self):
        pass

    def teardown(self):
        pass

    def execute(self, container_id, cmd):
        cmd = ["docker", "exec", "{}".format(container_id)] + cmd
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            ret = result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Command failed with exit code {e.returncode}. "
                f"Command attempted: {e.cmd}\n"
                f"Captured STDOUT:\n{e.stdout}\n"
                f"Captured STDERR:\n{e.stderr}\n"
                f"-------------------------"
            )
            raise  # re-raise as we want the test to end with an error
        return ret

    def cmd(self, container_id, docker_cmd, cmd=[]):
        cmd = ["docker", docker_cmd] + [str(container_id)] + cmd
        ret = subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return ret.stdout.decode("utf-8").strip()

    def download(self, container_id, source, destination):
        return self._cp(f"{container_id}:{source}", destination)

    def upload(self, container_id, source, destination):
        return self._cp(source, f"{container_id}:{destination}")

    def _cp(self, source, destination):
        cmd = ["docker", "cp", source, destination]
        ret = subprocess.check_output(cmd).decode("utf-8").strip()
        return ret

    def getid(self, filters):
        filters.append(self.name)
        filters = ["grep {}".format(f) for f in filters]
        cmd = "docker ps | " + " | ".join(filters) + " | awk '{print $1}'"

        ret = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()

        if ret == "":
            raise RuntimeError("container id for {} not found".format(str(filters)))

        return ret
