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
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_first_deploy.py",
    "src/boca_socios/host_rootless_setup.py",
    "src/boca_socios/host_boca_cleanup.py",
    "src/boca_socios/host_boca_attempt.py",
    "src/boca_socios/host_boca_transaction.py",
)
MAIN = ("from boca_socios.host_boca_transaction import main\nraise SystemExit(main())\n").encode(
    "ascii"
)
MAX_SOURCE_BYTES = 768_000
MAX_ARCHIVE_BYTES = 512_000


def build(root: Path, target: Path) -> str:
    """Write a reproducible archive to a trusted runner-only target."""
    files: dict[str, bytes] = {"__main__.py": MAIN}
    for rel in SOURCES:
        source = root / rel
        if source.is_symlink():
            raise ValueError("Boca protected package source may not be a symlink")
        item = source.lstat()
        if not stat.S_ISREG(item.st_mode) or not 0 < item.st_size <= MAX_SOURCE_BYTES:
            raise ValueError("Boca protected package source missing/oversized")
        data = source.read_bytes()
        if len(data) != item.st_size:
            raise ValueError("Boca protected package source changed while reading")
        files[rel.removeprefix("src/")] = data
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
