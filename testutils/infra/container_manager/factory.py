# Copyright 2023 Northern.tech AS
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
"""Define factories from where to create namespaces"""

from .docker_compose_manager import (
    DockerComposeStandardSetup,
    DockerComposeStandardSetupWithGateway,
    DockerComposeMonitorCommercialSetup,
    DockerComposeDockerClientSetup,
    DockerComposeRofsClientSetup,
    DockerComposeLegacyV1ClientSetup,
    DockerComposeLegacyV3ClientSetup,
    DockerComposeEnterpriseDockerClientSetup,
    DockerComposeSignedArtifactClientSetup,
    DockerComposeShortLivedTokenSetup,
    DockerComposeFailoverServerSetup,
    DockerComposeEnterpriseSetup,
    DockerComposeEnterpriseSetupWithGateway,
    DockerComposeEnterpriseSignedArtifactClientSetup,
    DockerComposeEnterpriseShortLivedTokenSetup,
    DockerComposeEnterpriseLegacyV1ClientSetup,
    DockerComposeEnterpriseLegacyV3ClientSetup,
    DockerComposeEnterpriseRofsClientSetup,
    DockerComposeEnterpriseRofsCommercialClientSetup,
    DockerComposeCustomSetup,
    DockerComposeCompatibilitySetup,
    DockerComposeMTLSSetup,
)
from .kubernetes_manager import (
    KubernetesEnterpriseSetup,
    KubernetesEnterpriseSetupWithGateway,
    KubernetesEnterpriseMonitorCommercialSetup,
    isK8S,
)


class ContainerManagerFactory:
    def get_standard_setup(self, name=None, num_clients=1):
        """Standard setup consisting on all core backend services and optionally clients

        The num_clients define how many QEMU Mender clients will be spawn.
        """
        pass

    def get_standard_setup_with_gateway(self, name=None, num_clients=1):
        """Standard setup with the Mender Gateway

        The num_clients define how many QEMU Mender clients will be spawn.
        """
        pass

    def get_monitor_commercial_setup(self, name=None, num_clients=1):
        """Monitor client setup consisting on all core backend services and monitor-client

        The num_clients define how many QEMU Mender clients will be spawn.
        """
        pass

    def get_docker_client_setup(self, name=None):
        """Standard setup with one Docker client instead of QEMU one"""
        pass

    def get_rofs_client_setup(self, name=None):
        """Standard setup with one QEMU Read-Only FS client instead of standard R/W"""
        pass

    def get_legacy_v1_client_setup(self, name=None):
        """Setup with one Mender client v1.7"""
        pass

    def get_legacy_v3_client_setup(self, name=None):
        """Setup with one Mender bundle v3.6"""
        pass

    def get_signed_artifact_client_setup(self, name=None):
        """Standard setup with pre-installed verification key in the client"""
        pass

    def get_short_lived_token_setup(self, name=None):
        """Standard setup on which deviceauth has a short lived token (expire timeout = 0)"""
        pass

    def get_failover_server_setup(self, name=None):
        """Setup with two servers and one client.

        First server (A) behaves as usual, whereas the second server (B) should
        not expect any clients. Client is initially set up against server A.
        """
        pass

    def get_enterprise_setup(self, name=None, num_clients=0):
        """Setup with enterprise versions for the applicable services"""
        pass

    def get_enterprise_setup_with_gateway(self, name=None, num_clients=0):
        """Setup with enterprise versions and the Mender Gateway"""
        pass

    def get_enterprise_signed_artifact_client_setup(self, name=None):
        """Enterprise setup with pre-installed verification key in the client"""
        pass

    def get_enterprise_short_lived_token_setup(self, name=None, num_clients=0):
        """Enterprise setup on which deviceauth has a short lived token (expire timeout = 0)"""
        pass

    def get_enterprise_legacy_v1_client_setup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender client v1.7"""
        pass

    def get_enterprise_legacy_v3_client_setup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender bundle v3.6"""
        pass

    def get_enterprise_docker_client_setup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender Docker client"""
        pass

    def get_enterprise_rofs_client_setup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender QEMU Read-Only FS client"""
        pass

    def get_enterprise_rofs_commercial_client_setup(self, name=None, num_clients=0):
        """Enterprise setup with one Mender QEMU Read-Only FS commercial client"""
        pass

    def get_enterprise_smtp_setup(self, name=None):
        """Enterprise setup with SMTP enabled"""
        pass

    def get_custom_setup(self, name=None):
        """A noop setup for tests that use custom setups

        It only implements teardown() for these tests to still have a way
        for the framework to clean after them (most importantly on errors).
        """
        pass


class DockerComposeManagerFactory(ContainerManagerFactory):
    def get_standard_setup(self, name=None, num_clients=1):
        return DockerComposeStandardSetup(name, num_clients)

    def get_standard_setup_with_gateway(self, name=None, num_clients=1):
        return DockerComposeStandardSetupWithGateway(name, num_clients)

    def get_monitor_commercial_setup(self, name=None, num_clients=0):
        return DockerComposeMonitorCommercialSetup(name, num_clients)

    def get_docker_client_setup(self, name=None):
        return DockerComposeDockerClientSetup(name)

    def get_rofs_client_setup(self, name=None):
        return DockerComposeRofsClientSetup(name)

    def get_legacy_v1_client_setup(self, name=None):
        return DockerComposeLegacyV1ClientSetup(name)

    def get_legacy_v3_client_setup(self, name=None):
        return DockerComposeLegacyV3ClientSetup(name)

    def get_signed_artifact_client_setup(self, name=None):
        return DockerComposeSignedArtifactClientSetup(name)

    def get_short_lived_token_setup(self, name=None):
        return DockerComposeShortLivedTokenSetup(name)

    def get_failover_server_setup(self, name=None):
        return DockerComposeFailoverServerSetup(name)

    def get_enterprise_setup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseSetup(name, num_clients)

    def get_enterprise_setup_with_gateway(self, name=None, num_clients=0):
        return DockerComposeEnterpriseSetupWithGateway(name, num_clients)

    def get_enterprise_signed_artifact_client_setup(self, name=None):
        return DockerComposeEnterpriseSignedArtifactClientSetup(name)

    def get_enterprise_short_lived_token_setup(self, name=None):
        return DockerComposeEnterpriseShortLivedTokenSetup(name)

    def get_enterprise_legacy_v1_client_setup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseLegacyV1ClientSetup(name, num_clients)

    def get_enterprise_legacy_v3_client_setup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseLegacyV3ClientSetup(name, num_clients)

    def get_enterprise_docker_client_setup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseDockerClientSetup(name, num_clients)

    def get_enterprise_rofs_client_setup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseRofsClientSetup(name, num_clients)

    def get_enterprise_rofs_commercial_client_setup(self, name=None, num_clients=0):
        return DockerComposeEnterpriseRofsCommercialClientSetup(name, num_clients)

    def get_compatibility_setup(self, name=None, **kwargs):
        return DockerComposeCompatibilitySetup(name, **kwargs)

    def get_mtls_setup(self, name=None, **kwargs):
        return DockerComposeMTLSSetup(name, **kwargs)

    def get_custom_setup(self, name=None):
        return DockerComposeCustomSetup(name)


class KubernetesManagerFactory(ContainerManagerFactory):
    def get_enterprise_setup(self, name=None, num_clients=0):
        return KubernetesEnterpriseSetup(name, num_clients)

    def get_enterprise_docker_client_setup(self, name=None, num_clients=0):
        return KubernetesEnterpriseSetup(name, num_clients)

    def get_enterprise_setup_with_gateway(self, name=None, num_clients=0):
        return KubernetesEnterpriseSetupWithGateway(name, num_clients)

    def get_monitor_commercial_setup(self, name=None, num_clients=0):
        return KubernetesEnterpriseMonitorCommercialSetup(name, num_clients)

    def get_enterprise_signed_artifact_client_setup(self, name=None, num_clients=0):
        return KubernetesEnterpriseSetup(name, num_clients)

    def get_enterprise_short_lived_token_setup(self, name=None, num_clients=0):
        return KubernetesEnterpriseSetup(name, num_clients)


def get_factory():
    if isK8S():
        return KubernetesManagerFactory()
    else:
        return DockerComposeManagerFactory()
