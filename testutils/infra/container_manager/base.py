
class BaseContainerManagerNamespace:
    """Base class to define a containers namespace
    """

    def __init__(self, name):
        self.name = name

    def setup(self):
        """Starts up required containers for the namespace
        """
        raise NotImplementedError

    def teardown(self):
        """Stops the running containers
        """
        raise NotImplementedError

    def execute(self, container_id, cmd):
        """Executes the given cmd on an specific container
        """
        raise NotImplementedError

    def cmd(self, container_id, docker_cmd, cmd=[]):
        """Executes a docker command with arguments on an specific container
        """
        raise NotImplementedError

    def getid(self, filters):
        """Returns the id for a container matching the given filters
        """
        raise NotImplementedError
