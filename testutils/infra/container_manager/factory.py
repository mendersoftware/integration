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
"define factories from where to create namespaces"

from .docker_compose_manager import (
    DockerComposeStandardSetup,
    DockerComposeStandardSetupWithGateway,
    DockerComposeMonitorCommercialSetup,
    DockerComposeDockerClientSetup,
    DockerComposeRofsClientSetup,
    DockerComposeLegacyClientSetup,
    DockerComposeEnterpriseDockerClientSetup,
    DockerComposeSignedArtifactClientSetup,
    DockerComposeShortLivedTokenSetup,
    DockerComposeFailoverServerSetup,
    DockerComposeEnterpriseSetup,
    DockerComposeEnterpriseSetupWithGateway,
    DockerComposeEnterpriseSignedArtifactClientSetup,
    DockerComposeEnterpriseShortLivedTokenSetup,
    DockerComposeEnterpriseLegacyClientSetup,
    DockerComposeEnterpriseRofsClientSetup,
    DockerComposeCustomSetup,
    DockerComposeCompatibilitySetup,
    DockerComposeMTLSSetup,
    DockerComposeMenderClient_2_5,
)
from .kubernetes_manager import (
    KubernetesEnterpriseSetup,
    KubernetesEnterpriseMonitorCommercialSetup,
    isK8S,
)


class ContainerManagerFactory:
    def getStandardSetup(self, name=None, num_clients=1):
        """Standard setup consisting on all core backend services and optionally clients

        The num_clients define how many QEMU Mender clients will be spawn.
        """
        pass

    def getStandardSetupWithGateway(self, name=None, num_clients=1):
        """Standard setup with the Mender Gateway

        The num_clients define how many QEMU Mender clients will be spawn.
        """
        pass

    def getMonitorCommercialSetup(self, name=None, num_clients=1):
        """Monitor client setup consisting on all core backend services and monitor-client

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

    def getEnterpriseSetupWithGateway(self, name=None, num_clients=0):
        """Setup with enterprise versions and the Mender Gateway"""
        pass

    def getEnterpriseSignedArtifactClientSetup(self, name=None):
        """Enterprise setup with pre-installed verification key in the client"""
        pass

    def getEnterpriseShortLivedTokenSetup(self, name=None, num_clients=0):
        """Enterprise setup on which deviceauth has a short lived token (expire timeout = 0)"""
        pass

    def getEnterpriseLegacyClientSetup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender client v1.7"""
        pass

    def getEnterpriseDockerClientSetup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender Docker client"""
        pass

    def getEnterpriseRofsClientSetup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender QEMU Read-Only FS client"""
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

    def getStandardSetupWithGateway(self, name=None, num_clients=1):
        return DockerComposeStandardSetupWithGateway(name, num_clients)

    def getMonitorCommercialSetup(self, name=None, num_clients=0):
        return DockerComposeMonitorCommercialSetup(name, num_clients)

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

    def getEnterpriseSetupWithGateway(self, name=None, num_clients=0):
        return DockerComposeEnterpriseSetupWithGateway(name, num_clients)

    def getEnterpriseSignedArtifactClientSetup(self, name=None):
        return DockerComposeEnterpriseSignedArtifactClientSetup(name)

    def getEnterpriseShortLivedTokenSetup(self, name=None):
        return DockerComposeEnterpriseShortLivedTokenSetup(name)

    def getEnterpriseLegacyClientSetup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseLegacyClientSetup(name, num_clients)

    def getEnterpriseDockerClientSetup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseDockerClientSetup(name, num_clients)

    def getEnterpriseRofsClientSetup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseRofsClientSetup(name, num_clients)

    def getCompatibilitySetup(self, name=None, **kwargs):
        return DockerComposeCompatibilitySetup(name, **kwargs)

    def getMTLSSetup(self, name=None, **kwargs):
        return DockerComposeMTLSSetup(name, **kwargs)

    def getMenderClient_2_5(self, name=None, **kwargs):
        return DockerComposeMenderClient_2_5(name, **kwargs)

    def getCustomSetup(self, name=None):
        return DockerComposeCustomSetup(name)


class KubernetesManagerFactory(ContainerManagerFactory):
    def getEnterpriseSetup(self, name=None, num_clients=0):
        return KubernetesEnterpriseSetup(name, num_clients)

    def getMonitorCommercialSetup(self, name=None, num_clients=0):
        return KubernetesEnterpriseMonitorCommercialSetup(name, num_clients)


def get_factory():
    if isK8S():
        return KubernetesManagerFactory()
    else:
        return DockerComposeManagerFactory()
