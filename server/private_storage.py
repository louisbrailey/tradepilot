"""Platform-specific private storage, preserving existing POSIX behavior."""
import os
from pathlib import Path


def ensure_private_directory(path):
    path = Path(path)
    if os.name == 'nt':
        from windows_runtime import private_directory
        return private_directory(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def runtime_path(value):
    path = Path(value)
    return path.absolute() if os.name == "nt" else path.resolve()
