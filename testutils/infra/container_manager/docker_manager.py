# Copyright 2018 Northern.tech AS
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
import subprocess

from .base import BaseContainerManagerNamespace

class DockerNamespace(BaseContainerManagerNamespace):

    def __init__(self, name):
        BaseContainerManagerNamespace.__init__(self, name)

    def setup(self):
        pass

    def teardown(self):
        pass

    def execute(self, container_id, cmd):
        cmd = ['docker', 'exec', '{}'.format(container_id)] + cmd
        ret = subprocess.check_output(cmd).decode('utf-8').strip()
        return ret

    def cmd(self, container_id, docker_cmd, cmd=[]):
        cmd = ['docker', docker_cmd] + [str(container_id)] + cmd
        ret = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return ret.stdout.decode('utf-8').strip()

    def getid(self, filters):
        filters.append(self.name)
        filters = ["grep {}".format(f) for f in filters]
        cmd = "docker ps | " + " | ".join(filters)  + " | awk '{print $1}'"

        ret = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()

        if ret == '':
            raise RuntimeError('container id for {} not found'.format(str(filters)))

        return ret
