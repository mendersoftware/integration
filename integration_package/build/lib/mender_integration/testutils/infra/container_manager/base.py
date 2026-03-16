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
"""define base class and it interface"""

import random


class BaseContainerManagerNamespace:
    """Base class to define a containers namespace"""

    def __init__(self, name=None):
        """Creates instance

        name is the namespace id (project in docker-compose terms).
        If it is None, it will randomly generated
        """
        if name is None:
            name = "mender" + str(random.randint(0, 9999999))
        self.name = name

    def setup(self):
        """Starts up required containers for the namespace"""
        raise NotImplementedError

    def teardown(self):
        """Stops the running containers"""
        raise NotImplementedError

    def execute(self, container_id, cmd):
        """Executes the given cmd on an specific container"""
        raise NotImplementedError

    def cmd(self, container_id, docker_cmd, cmd=[]):
        """Executes a docker command with arguments on an specific container"""
        raise NotImplementedError

    def download(self, container_id, source, destination):
        """Download a file from a container"""
        raise NotImplementedError

    def upload(self, container_id, source, destination):
        """Upload a file to a container"""
        raise NotImplementedError

    def getid(self, filters):
        """Returns the id for a container matching the given filters"""
        raise NotImplementedError
