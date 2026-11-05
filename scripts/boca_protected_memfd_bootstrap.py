"""Tiny host-side ZIP verifier; Python source passed as -c, ZIP on stdin.

No host filesystem writes, Docker calls or network access occur before the
expected package SHA256 and strict allowed-entry list are checked. The exact
verified payload is run via a non-CLOEXEC Linux memfd in a single process.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import sys
import zipfile

EXPECTED_ENTRIES = frozenset(
    {
        "__main__.py",
        "compose.yaml",
        "compose.beta.yaml",
        "compose.beta.browser.yaml",
        "docker/seccomp_profile.json",
        "boca_socios/__init__.py",
        "boca_socios/host_first_deploy.py",
        "boca_socios/host_rootless_setup.py",
        "boca_socios/host_boca_cleanup.py",
        "boca_socios/host_boca_attempt.py",
        "boca_socios/host_boca_transaction.py",
        "boca_socios/host_boca_cutover.py",
        "boca_socios/host_boca_cutover_backend.py",
        "boca_socios/host_boca_cutover_cli.py",
        "boca_socios/host_boca_cutover_receipt.py",
        "boca_socios/host_cutover_stage.py",
        "boca_socios/host_lifecycle_actions.py",
        "boca_socios/host_lifecycle_observe.py",
        "boca_socios/host_lifecycle_rootless_adapter.py",
        "boca_socios/host_boca_lifecycle.py",
        "boca_socios/panel/lifecycle_intents.py",
        "boca_socios/integration/engine_socket.py",
        "boca_socios/storage/__init__.py",
        "boca_socios/panel/__init__.py",
        "boca_socios/integration/__init__.py",
        "boca_socios/storage/migrations/__init__.py",
        "boca_socios/storage/migrations/0001_initial.sql",
        "boca_socios/storage/migrations/0002_notification_outbox.sql",
        "boca_socios/storage/migrations/0003_reservation_guard.sql",
        "boca_socios/storage/migrations/0004_credential_key_policy.sql",
        "boca_socios/storage/migrations/0005_simulation_outcomes.sql",
        "boca_socios/storage/migrations/0006_beta_commands.sql",
        "boca_socios/storage/migrations/0007_telegram_delivery.sql",
    }
)
OPTION_B_ENTRIES = frozenset(
    {
        "boca_socios/owner_session_disk_bootstrap.py",
        "boca_socios/panel/owner_session_sql/0001_owner_browser_session.sql",
    }
)
MAX_ZIP = 512_000
MAX_UNCOMPRESSED = 768_000


def verify(raw: bytes, expected_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("protected Boca bundle expected digest invalid")
    if not raw or len(raw) > MAX_ZIP or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("protected Boca bundle SHA/size mismatch")
    with zipfile.ZipFile(io.BytesIO(raw), "r") as package:
        entries = package.infolist()
        names = [entry.filename for entry in entries]
        if (
            set(names) not in (EXPECTED_ENTRIES, EXPECTED_ENTRIES | OPTION_B_ENTRIES)
            or len(names) != len(set(names))
            or any(entry.is_dir() for entry in entries)
            or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED
        ):
            raise ValueError("protected Boca bundle entry allowlist mismatch")
        for entry in entries:
            if entry.file_size == 0 or entry.file_size > MAX_UNCOMPRESSED:
                raise ValueError("protected Boca bundle entry size invalid")
            # The ZIP is a code bundle, never a deployed filesystem tree.
            # Refuse symlink/special entries to avoid importing from outside.
            mode = (entry.external_attr >> 16) & 0o170000
            if mode != 0o100000:
                raise ValueError("protected Boca bundle entry mode invalid")


def main() -> int:
    if len(sys.argv) < 3:
        print("BOCA_BUNDLE state=NO_GO reason=arguments", file=sys.stderr)
        return 2
    try:
        raw = sys.stdin.buffer.read(MAX_ZIP + 1)
        verify(raw, sys.argv[1])
        # The memfd is passed to the *same* process via exec. No temporary
        # container, host file or broader Docker resource is ever created.
        fd = os.memfd_create("boca-protected-transaction", flags=0)
        try:
            written = os.write(fd, raw)
            if written != len(raw):
                raise OSError("short protected Boca memfd write")
            os.lseek(fd, 0, os.SEEK_SET)
            os.execv(  # noqa: S606 - exact Python binary/verified memfd, no shell
                sys.executable, (sys.executable, f"/proc/self/fd/{fd}", *sys.argv[2:])
            )
        finally:
            os.close(fd)
    except (OSError, ValueError, zipfile.BadZipFile):
        # Never print raw ZIP contents or exception text from a remote host.
        print("BOCA_BUNDLE state=NO_GO reason=hash_or_host_runtime", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
