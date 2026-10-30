"""One-time master key provisioning inside a dedicated Docker volume.

The initializer runs as root only inside the rootless Docker user namespace.
It sees the Boca key volume and no host bind mount, database or network.
"""

from __future__ import annotations

import argparse
import base64
import os
import stat
import sys
from pathlib import Path

from boca_socios.security.credential_vault import CredentialVault

KEY = Path("/run/secrets/boca_master_key")
CONTROLLER_UID = 10001


def _directory(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    metadata = os.fstat(fd)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0:
        os.close(fd)
        raise ValueError("Boca key volume owner is unsafe")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        os.close(fd)
        raise ValueError("Boca key volume is writable by another identity")
    return fd


def _entries(directory: int) -> set[str]:
    with os.scandir(directory) as entries:
        return {entry.name for entry in entries}


def initialize(path: Path = KEY) -> None:
    """Create once, without ever replacing or printing the key."""
    if os.geteuid() != 0:
        raise ValueError("key initialization requires root inside the user namespace")
    directory = _directory(path.parent)
    try:
        if _entries(directory):
            raise ValueError("Boca key volume is not empty")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(path.name, flags, 0o400, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as output:
            output.write(base64.b64encode(os.urandom(32)) + b"\n")
            output.flush()
            os.fchmod(output.fileno(), 0o400)
            os.fchown(output.fileno(), CONTROLLER_UID, CONTROLLER_UID)
            os.fsync(output.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)


def inspect(path: Path = KEY) -> None:
    """Check owner-only metadata as the controller UID; do not read the key."""
    if os.geteuid() != CONTROLLER_UID:
        raise ValueError("key inspection requires the controller identity")
    directory = _directory(path.parent)
    try:
        if _entries(directory) != {path.name}:
            raise ValueError("Boca key volume contains unexpected entries")
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != CONTROLLER_UID
                or metadata.st_gid != CONTROLLER_UID
                or stat.S_IMODE(metadata.st_mode) != 0o400
                or metadata.st_nlink != 1
                or metadata.st_size != 45
            ):
                raise ValueError("Boca key metadata is unsafe")
    finally:
        os.close(directory)


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca volume key custody")
    parser.add_argument("operation", choices=("init", "verify", "inspect"))
    args = parser.parse_args()
    try:
        if args.operation == "init":
            initialize()
        else:
            inspect()
            if args.operation == "verify":
                CredentialVault.from_secret_file(KEY)
    except (OSError, ValueError):
        print("BOCA_KEY_NO_GO: key custody check failed", file=sys.stderr)
        return 1
    print("BOCA_KEY_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
