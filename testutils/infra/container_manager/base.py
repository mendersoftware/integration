
class BaseContainerManagerNamespace:
    """Base class to define a containers namespace
    """

    def setup(self):
        """Starts up required containers for the namespace
        """
        raise NotImplementedError

    def teardown(self):
        """Stops the running containers
        """
        raise NotImplementedError
