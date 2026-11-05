"""Build deterministic, minimal Boca-only host transaction ZIP (code-only).

The archive is never executed by this builder; the protected GitHub job must
hash its exact bytes and its host-side bootstrap must compare that digest
before executing anything. BLACKBOX and other project files are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import zipfile
from pathlib import Path

SOURCES = (
    "compose.yaml",
    "compose.beta.yaml",
    "compose.beta.browser.yaml",
    "docker/seccomp_profile.json",
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_first_deploy.py",
    "src/boca_socios/host_rootless_setup.py",
    "src/boca_socios/host_boca_cleanup.py",
    "src/boca_socios/host_boca_attempt.py",
    "src/boca_socios/host_boca_transaction.py",
    "src/boca_socios/host_boca_cutover.py",
    "src/boca_socios/host_boca_cutover_backend.py",
    "src/boca_socios/host_boca_cutover_cli.py",
    "src/boca_socios/host_boca_cutover_receipt.py",
    "src/boca_socios/host_cutover_stage.py",
    # Host-only lifecycle bridge and bounded stdlib dependency closure.
    "src/boca_socios/host_lifecycle_actions.py",
    "src/boca_socios/host_lifecycle_observe.py",
    "src/boca_socios/host_lifecycle_rootless_adapter.py",
    "src/boca_socios/host_boca_lifecycle.py",
    "src/boca_socios/panel/lifecycle_intents.py",
    "src/boca_socios/integration/engine_socket.py",
    "src/boca_socios/storage/__init__.py",
    "src/boca_socios/storage/migrations/__init__.py",
    "src/boca_socios/storage/migrations/0001_initial.sql",
    "src/boca_socios/storage/migrations/0002_notification_outbox.sql",
    "src/boca_socios/storage/migrations/0003_reservation_guard.sql",
    "src/boca_socios/storage/migrations/0004_credential_key_policy.sql",
    "src/boca_socios/storage/migrations/0005_simulation_outcomes.sql",
    "src/boca_socios/storage/migrations/0006_beta_commands.sql",
    "src/boca_socios/storage/migrations/0007_telegram_delivery.sql",
)
# The controller's normal panel/integration package initializers eagerly import
# application modules. In the HOST-ONLY memfd package, only the reviewed
# lifecycle receipt submodules may be imported; never BLACKBOX/navigation.
HOST_ONLY_INIT = {
    "boca_socios/panel/__init__.py": b'"""Protected host ledger-only namespace."""\n',
    "boca_socios/integration/__init__.py": b'"""Protected host engine-wire-only namespace."""\n',
}
# Source-owned by #321, merged only after that PR passes its own QA.  The
# standalone #320 bundle has the core profile; after integration it gains
# BOTH exact Option B files. One present without the other is always NO_GO.
OPTION_B_SOURCES = (
    "src/boca_socios/panel/owner_session_disk_bootstrap.py",
    "src/boca_socios/panel/owner_session_sql/0001_owner_browser_session.sql",
)
OPTION_B_STDLIB_BUNDLE_NAME = "boca_socios/owner_session_disk_bootstrap.py"
MAIN = (
    "import sys\n"
    "if len(sys.argv) > 1 and sys.argv[1] in ('lifecycle-apply', 'lifecycle-bridge-selftest'):\n"
    "    from boca_socios import host_lifecycle_actions as bridge\n"
    "    if sys.argv[1] == 'lifecycle-bridge-selftest':\n"
    "        raise SystemExit(bridge.selftest_main())\n"
    "    raise SystemExit(bridge.main(sys.argv[2:]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] in ('lifecycle-observe', 'lifecycle-observe-selftest'):\n"
    "    from boca_socios import host_lifecycle_observe as observe\n"
    "    if sys.argv[1] == 'lifecycle-observe-selftest':\n"
    "        raise SystemExit(observe.selftest_main())\n"
    "    raise SystemExit(observe.main(sys.argv[2:]))\n"
    "from boca_socios.host_boca_transaction import main\n"
    "raise SystemExit(main())\n"
).encode("ascii")
MAX_SOURCE_BYTES = 768_000
MAX_ARCHIVE_BYTES = 512_000


def build(root: Path, target: Path) -> str:
    """Write a reproducible archive to a trusted runner-only target."""
    files: dict[str, bytes] = {"__main__.py": MAIN, **HOST_ONLY_INIT}
    b_sources = tuple(root / rel for rel in OPTION_B_SOURCES)
    if any(source.exists() or source.is_symlink() for source in b_sources):
        if not all(source.is_file() and not source.is_symlink() for source in b_sources):
            raise ValueError("Boca Option B requires both reviewed session source and SQL")
        sources = (*SOURCES, *OPTION_B_SOURCES)
    else:
        sources = SOURCES
    for rel in sources:
        source = root / rel
        if source.is_symlink():
            raise ValueError("Boca protected package source may not be a symlink")
        item = source.lstat()
        if not stat.S_ISREG(item.st_mode) or not 0 < item.st_size <= MAX_SOURCE_BYTES:
            raise ValueError("Boca protected package source missing/oversized")
        data = source.read_bytes()
        if len(data) != item.st_size:
            raise ValueError("Boca protected package source changed while reading")
        # The full Boca `panel/__init__.py` has UI imports. The standalone
        # stdlib-only disk attestor is shipped under a private ZIP import name
        # instead of importing any unreviewed panel or BLACKBOX dependency.
        name = (
            OPTION_B_STDLIB_BUNDLE_NAME if rel == OPTION_B_SOURCES[0] else rel.removeprefix("src/")
        )
        files[name] = data
    if not 0 < sum(len(item) for item in files.values()) <= MAX_SOURCE_BYTES:
        raise ValueError("Boca protected package total exceeds bounded contract")
    if target.is_symlink() or target.exists():
        raise ValueError("Boca protected package target must be a fresh artifact")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for name in sorted(files):
                    entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.create_system = 3
                    entry.external_attr = 0o100644 << 16
                    bundle.writestr(entry, files[name])
            stream.flush()
            os.fsync(stream.fileno())
        raw = target.read_bytes()
        if not 0 < len(raw) <= MAX_ARCHIVE_BYTES:
            raise ValueError("Boca protected package ZIP exceeds bounded contract")
        return hashlib.sha256(raw).hexdigest()
    except Exception:
        # Target was freshly created by us and never shared with other jobs.
        # Preserve partial evidence for investigation; never broad-delete.
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca-only deterministic host code bundle")
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("runner_target", type=Path)
    args = parser.parse_args()
    print(f"BOCA_PROTECTED_BUNDLE sha256={build(args.repository_root, args.runner_target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
