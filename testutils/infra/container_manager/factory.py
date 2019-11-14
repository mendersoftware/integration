
from .docker_compose_manager import DockerComposeStandardSetup
from .docker_compose_manager import DockerComposeDockerClientSetup
from .docker_compose_manager import DockerComposeRofsClientSetup
from .docker_compose_manager import DockerComposeLegacyClientSetup
from .docker_compose_manager import DockerComposeSignedArtifactClientSetup
from .docker_compose_manager import DockerComposeShortLivedTokenSetup
from .docker_compose_manager import DockerComposeFailoverServerSetup
from .docker_compose_manager import DockerComposeEnterpriseSetup
from .docker_compose_manager import DockerComposeEnterpriseSMTPSetup

class ContainerManagerFactory:
    def getStandardSetup(self, name, num_clients=1): pass
    def getDockerClientSetup(self, name): pass
    def getRofsClientSetup(self, name): pass
    def getLegacyClientSetup(self, name): pass
    def getSignedArtifactClientSetup(self, name): pass
    def getShortLivedTokenSetup(self, name): pass
    def getFailoverServerSetup(self, name): pass
    def getEnterpriseSetup(self, name, num_clients=0): pass
    def getEnterpriseSMTPSetup(self, name): pass

class DockerComposeManagerFactory(ContainerManagerFactory):
    def getStandardSetup(self, name, num_clients=1):
        return DockerComposeStandardSetup(name, num_clients)
    def getDockerClientSetup(self, name):
        return DockerComposeDockerClientSetup(name)
    def getRofsClientSetup(self, name):
        return DockerComposeRofsClientSetup(name)
    def getLegacyClientSetup(self, name):
        return DockerComposeLegacyClientSetup(name)
    def getSignedArtifactClientSetup(self, name):
        return DockerComposeSignedArtifactClientSetup(name)
    def getShortLivedTokenSetup(self, name):
        return DockerComposeShortLivedTokenSetup(name)
    def getFailoverServerSetup(self, name):
        return DockerComposeFailoverServerSetup(name)
    def getEnterpriseSetup(self, name, num_clients=0):
        return DockerComposeEnterpriseSetup(name, num_clients)
    def getEnterpriseSMTPSetup(self, name):
        return DockerComposeEnterpriseSMTPSetup(name)

def get_factory(manager_id="docker-compose"):
    if manager_id == "docker-compose":
        return DockerComposeManagerFactory()
    elif manager_id == "minikube":
        raise NotImplementedError("Kubernetes factory not implemented.")
    else:
        raise RuntimeError("Unknown manager id {}".format(manager_id))
