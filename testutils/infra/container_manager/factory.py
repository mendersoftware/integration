# Copyright 2019 Northern.tech AS
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
"define factories from where to create namespaces"

from .docker_compose_manager import DockerComposeStandardSetup
from .docker_compose_manager import DockerComposeDockerClientSetup
from .docker_compose_manager import DockerComposeRofsClientSetup
from .docker_compose_manager import DockerComposeLegacyClientSetup
from .docker_compose_manager import DockerComposeSignedArtifactClientSetup
from .docker_compose_manager import DockerComposeShortLivedTokenSetup
from .docker_compose_manager import DockerComposeFailoverServerSetup
from .docker_compose_manager import DockerComposeEnterpriseSetup
from .docker_compose_manager import DockerComposeEnterpriseSMTPSetup
from .docker_compose_manager import DockerComposeCustomSetup


class ContainerManagerFactory:
    def getStandardSetup(self, name=None, num_clients=1):
        """Standard setup consisting on all core backend services and optionally clients

        The num_clients define how many QEMU Mender clients will be spawn.
        """
        pass

    def getDockerClientSetup(self, name=None):
        """Standard setup with one Docker client instead of QEMU one"""
        pass

    def getRofsClientSetup(self, name=None):
        """Standard setup with one QEMU Read-Only FS client instead of standard R/W"""
        pass

    def getLegacyClientSetup(self, name=None):
        """Setup with one Mender client v1.7"""
        pass

    def getSignedArtifactClientSetup(self, name=None):
        """Standard setup with pre-installed verification key in the client"""
        pass

    def getShortLivedTokenSetup(self, name=None):
        """Standard setup on which deviceauth has a short lived token (expire timeout = 0)"""
        pass

    def getFailoverServerSetup(self, name=None):
        """Setup with two servers and one client.

        First server (A) behaves as usual, whereas the second server (B) should
        not expect any clients. Client is initially set up against server A.
        """
        pass

    def getEnterpriseSetup(self, name=None, num_clients=0):
        """Setup with enterprise versions for the applicable services"""
        pass

    def getEnterpriseSMTPSetup(self, name=None):
        """Enterprise setup with SMTP enabled"""
        pass

    def getCustomSetup(self, name=None):
        """A noop setup for tests that use custom setups

        It only implements teardown() for these tests to still have a way
        for the framework to clean after them (most importantly on errors).
        """
        pass


class DockerComposeManagerFactory(ContainerManagerFactory):
    def getStandardSetup(self, name=None, num_clients=1):
        return DockerComposeStandardSetup(name, num_clients)

    def getDockerClientSetup(self, name=None):
        return DockerComposeDockerClientSetup(name)

    def getRofsClientSetup(self, name=None):
        return DockerComposeRofsClientSetup(name)

    def getLegacyClientSetup(self, name=None):
        return DockerComposeLegacyClientSetup(name)

    def getSignedArtifactClientSetup(self, name=None):
        return DockerComposeSignedArtifactClientSetup(name)

    def getShortLivedTokenSetup(self, name=None):
        return DockerComposeShortLivedTokenSetup(name)

    def getFailoverServerSetup(self, name=None):
        return DockerComposeFailoverServerSetup(name)

    def getEnterpriseSetup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseSetup(name, num_clients)

    def getEnterpriseSMTPSetup(self, name=None):
        return DockerComposeEnterpriseSMTPSetup(name)

    def getCustomSetup(self, name=None):
        return DockerComposeCustomSetup(name)


def get_factory(manager_id="docker-compose"):
    if manager_id == "docker-compose":
        return DockerComposeManagerFactory()
    elif manager_id == "minikube":
        raise NotImplementedError("Kubernetes factory not implemented.")
    else:
        raise RuntimeError("Unknown manager id {}".format(manager_id))
