
from .docker_compose_manager import DockerComposeStandardSetup
from .docker_compose_manager import DockerComposeDockerClientSetup
from .docker_compose_manager import DockerComposeRofsClientSetup

class ContainerManagerFactory:
    def getStandardSetup(self): pass
    def getDockerClientSetup(self): pass
    def getRofsClientSetup(self): pass

class DockerComposeManagerFactory(ContainerManagerFactory):
    def getStandardSetup(self, num_clients=1):
        return DockerComposeStandardSetup(num_clients)
    def getDockerClientSetup(self):
        return DockerComposeDockerClientSetup()
    def getRofsClientSetup(self):
        return DockerComposeRofsClientSetup()

def get_factory(manager_id="docker-compose"):
    if manager_id == "docker-compose":
        return DockerComposeManagerFactory()
    elif manager_id == "minikube":
        raise NotImplementedError("Kubernetes factory not implemented.")
    else:
        raise RuntimeError("Unknown manager id {}".format(manager_id))
