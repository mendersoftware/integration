import contextlib
from importlib import resources

@contextlib.contextmanager
def get_compose_path(filename: str):
    """Safely fetches the path of a compose file."""
    resource_path = resources.files("mender_integration.compose_files") / filename
    with resources.as_file(resource_path) as path:
        yield str(path)
