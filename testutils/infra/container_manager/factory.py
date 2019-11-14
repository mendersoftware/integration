
from .docker_compose_manager import DockerComposeStandardSetup
from .docker_compose_manager import DockerComposeDockerClientSetup
from .docker_compose_manager import DockerComposeRofsClientSetup

class ContainerManagerFactory:
    def getStandardSetup(self, name, num_clients=1): pass
    def getDockerClientSetup(self, name): pass
    def getRofsClientSetup(self, name): pass

class DockerComposeManagerFactory(ContainerManagerFactory):
    def getStandardSetup(self, name, num_clients=1):
        return DockerComposeStandardSetup(name, num_clients)
    def getDockerClientSetup(self, name):
        return DockerComposeDockerClientSetup(name)
    def getRofsClientSetup(self, name):
        return DockerComposeRofsClientSetup(name)

def get_factory(manager_id="docker-compose"):
    if manager_id == "docker-compose":
        return DockerComposeManagerFactory()
    elif manager_id == "minikube":
        raise NotImplementedError("Kubernetes factory not implemented.")
    else:
        raise RuntimeError("Unknown manager id {}".format(manager_id))
