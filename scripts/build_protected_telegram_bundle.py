"""Build a standalone, reviewed Boca Telegram host *code-only* ZIP.

The Cutover A ZIP has a deliberately tight, independent 768 KiB source cap.
Telegram's crypto/owner/lease dependency closure must NEVER be appended to
that transaction. This archive is not dispatched to a host, cannot activate
Telegram and deliberately exposes only a bounded import self-test.

A future independently reviewed ``telegram-activate`` backend must verify
the exact archive digest, Environment GO_B, real UID10001 crypto/volume
capability, existing Cutover A receipt and one held Boca job lease before any
host effect. No such authority can be inferred from this builder or self-test.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import zipfile
from pathlib import Path

SOURCES = (
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_boca_cleanup.py",
    "src/boca_socios/host_boca_lifecycle.py",
    "src/boca_socios/host_lifecycle_rootless_adapter.py",
    "src/boca_socios/host_telegram_active_helper_topology.py",
    "src/boca_socios/host_telegram_egress_helper.py",
    "src/boca_socios/host_telegram_owner_stage.py",
    "src/boca_socios/host_telegram_postcutover.py",
    "src/boca_socios/host_telegram_production_reader.py",
    "src/boca_socios/host_telegram_protected_custody_caller.py",
    "src/boca_socios/host_telegram_protected_readonly_caller.py",
    "src/boca_socios/telegram_bootstrap.py",
    "src/boca_socios/telegram_host_readonly_session.py",
    "src/boca_socios/telegram_owner_webauthn.py",
    "src/boca_socios/telegram_pairing_bootstrap.py",
    "src/boca_socios/telegram_pairing_cutover.py",
    "src/boca_socios/telegram_pairing_install.py",
    "src/boca_socios/telegram_pairing_issuer.py",
    "src/boca_socios/telegram_pairing_resolver.py",
    "src/boca_socios/telegram_private_chat_discovery.py",
    "src/boca_socios/telegram_same_lease_stage.py",
    "src/boca_socios/integration/engine_socket.py",
    "src/boca_socios/panel/lifecycle_intents.py",
    "src/boca_socios/panel/passkey.py",
    "src/boca_socios/panel/owner_sessions.py",
    "src/boca_socios/panel/owner_session_store.py",
    "src/boca_socios/panel/telegram_pairing_staging.py",
    "src/boca_socios/owner_origin.py",
    "src/boca_socios/storage/database.py",
    "src/boca_socios/domain/policy.py",
    "src/boca_socios/security/credential_vault.py",
)

# The host package never imports the application/panel/integration package
# initializers; those import additional runtime routes and could drift into
# BLACKBOX. The reviewed leaf modules above are imported explicitly instead.
PRIVATE_INITIALIZERS = {
    "boca_socios/panel/__init__.py": b'"""Host Telegram reviewed panel leaf namespace."""\n',
    "boca_socios/integration/__init__.py": b'"""Host Telegram reviewed engine leaf namespace."""\n',
    "boca_socios/storage/__init__.py": b'"""Host Telegram reviewed storage leaf namespace."""\n',
    "boca_socios/domain/__init__.py": b'"""Host Telegram reviewed policy leaf namespace."""\n',
    "boca_socios/security/__init__.py": b'"""Host Telegram reviewed custody leaf namespace."""\n',
}

MAIN = (
    "import sys\n"
    "if sys.argv[1:] != ['selftest']:\n"
    "    print('BOCA_TELEGRAM_HOST state=NO_GO reason=protected_activation_not_wired sender=OFF')\n"
    "    raise SystemExit(2)\n"
    "from boca_socios import host_telegram_protected_custody_caller as custody\n"
    "from boca_socios import host_telegram_owner_stage as owner\n"
    "from boca_socios import host_telegram_egress_helper as helper\n"
    "from boca_socios import telegram_pairing_issuer as issuer\n"
    "assert callable(custody.run_bound_telegram_staged_custody)\n"
    "assert callable(owner.observe_owner_stage_under_same_lease)\n"
    "assert callable(helper.protected_ephemeral_get_session)\n"
    "assert callable(issuer.issue_owner_pairing_receipt)\n"
    "print('BOCA_TELEGRAM_HOST state=CODE_ONLY_CLOSURE_READY host=untouched sender=OFF')\n"
).encode("ascii")
MAX_SOURCE_BYTES = 450_000
MAX_ARCHIVE_BYTES = 300_000


def build(root: Path, target: Path) -> str:
    """Create an immutable deterministic ZIP under runner-only destination."""
    files: dict[str, bytes] = {"__main__.py": MAIN, **PRIVATE_INITIALIZERS}
    for source_name in SOURCES:
        source = root / source_name
        if source.is_symlink():
            raise ValueError("reviewed Boca Telegram source is a symlink")
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_SOURCE_BYTES:
            raise ValueError("reviewed Boca Telegram source missing or oversized")
        content = source.read_bytes()
        if len(content) != metadata.st_size:
            raise ValueError("reviewed Boca Telegram source changed during reading")
        bundle_name = source_name.removeprefix("src/")
        if bundle_name in files:
            raise ValueError("duplicate Boca Telegram archive entry")
        files[bundle_name] = content
    if not 0 < sum(len(data) for data in files.values()) <= MAX_SOURCE_BYTES:
        raise ValueError("Boca Telegram reviewed source closure exceeds bound")
    if target.is_symlink() or target.exists():
        raise ValueError("Boca Telegram bundle target must be fresh")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as output:
            with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in sorted(files):
                    item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    item.compress_type = zipfile.ZIP_DEFLATED
                    item.create_system = 3
                    item.external_attr = 0o100644 << 16
                    archive.writestr(item, files[name])
            output.flush()
            os.fsync(output.fileno())
        packed = target.read_bytes()
        if not 0 < len(packed) <= MAX_ARCHIVE_BYTES:
            raise ValueError("Boca Telegram compressed closure exceeds bound")
        return hashlib.sha256(packed).hexdigest()
    except Exception:
        # Preserve partially written, now untrusted evidence on failure.
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca-only offline Telegram host archive")
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("runner_target", type=Path)
    args = parser.parse_args()
    print(f"BOCA_TELEGRAM_BUNDLE sha256={build(args.repository_root, args.runner_target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
