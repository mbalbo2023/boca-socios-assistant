"""Single-process protected Boca install transaction (draft #323).

This module is currently CODE ONLY: no live workflow calls it. The transport
and strict negative selftest are published before any host effectful phase is
connected. A future protected entrypoint must hold one flock before staging,
complete success/failure cleanup in try/finally, and fail closed on lost SSH.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile


class TransactionError(ValueError):
    """No install can be authorized until the entire host gate exists."""


def _bundled_reviewed_file(path: str) -> bytes:
    if path not in (
        "compose.yaml",
        "compose.beta.yaml",
        "compose.beta.browser.yaml",
        "docker/seccomp_profile.json",
    ):
        raise TransactionError("unreviewed Boca bundle file entry")
    # Source package is the already verified SHA-pinned memfd ZIP. Never
    # import a Compose file from host filesystem or a secondary SSH session.
    with zipfile.ZipFile(sys.argv[0], "r") as package:
        data = package.read(path)
    if not 0 < len(data) <= 32768:
        raise TransactionError("Boca bundled reviewed file size invalid")
    return data


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "bundle-selftest":
        try:
            assert hashlib.sha256(_bundled_reviewed_file("compose.yaml")).digest()
            assert hashlib.sha256(_bundled_reviewed_file("compose.beta.yaml")).digest()
            assert hashlib.sha256(_bundled_reviewed_file("compose.beta.browser.yaml")).digest()
            assert hashlib.sha256(_bundled_reviewed_file("docker/seccomp_profile.json")).digest()
        except (TransactionError, AssertionError, OSError, KeyError, zipfile.BadZipFile):
            print("BOCA_BUNDLE_SELFTEST state=NO_GO reason=source_unverified")
            return 1
        print("BOCA_BUNDLE_SELFTEST state=PASS host=untouched blackbox=excluded")
        return 0
    # P0 intentionally refuses effectful dispatch until source transaction,
    # runtime attestation, selective finalizer and YAML assertion are proven.
    print("BOCA_PROTECTED_INSTALL state=NO_GO reason=transaction_not_wired")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
