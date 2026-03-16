import contextlib
import os
from importlib import resources
from pathlib import Path
from mender_integration.compose_files import ENV_FILE_PATH

@contextlib.contextmanager
def get_compose_path(filename: str):
    """Safely fetches the path of a compose file."""
    resource_path = resources.files("mender_integration.compose_files") / filename
    with resources.as_file(resource_path) as path:
        yield str(path)

def install_shell_hook():
    home = Path.home()
    symlink_path = home / ".mender.env"
    rc_file = home / ".bashrc"

    # 1. Create or update the symlink
    if symlink_path.exists() or symlink_path.is_symlink():
        symlink_path.unlink()  # Remove old link if it exists

    os.symlink(ENV_FILE_PATH, symlink_path)
    print(f"✅ Created symlink: {symlink_path} -> {ENV_FILE_PATH}")

    # 2. Add the loader line to .bashrc if not already present
    # We use 'set -a' to tell bash to export everything it finds in the file
    loader_line = f'[ -f "{symlink_path}" ] && export $(grep -v "^#" {symlink_path} | xargs)\n'

    current_content = rc_file.read_text() if rc_file.exists() else ""

    if ".mender.env" not in current_content:
        with open(rc_file, "a") as f:
            f.write(f"\n# Mender Package Variables\n{loader_line}")
        print(f"✅ Added loader to {rc_file}")
    else:
        print(f"ℹ️ Loader already present in {rc_file}")

    print("\nDone! Run 'source ~/.bashrc' to apply variables to this session.")
