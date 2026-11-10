"""Offline contract for the one-purpose Boca worker-recovery memfd package."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
from scripts import build_protected_boca_bundle as builder  # noqa: E402

EXPECTED_RECOVERY = {
    "__main__.py",
    "boca_socios/__init__.py",
    "boca_socios/host_boca_cleanup.py",
    "docker/seccomp_profile.json",
    "scripts/__init__.py",
    "scripts/host_cutover_worker_inspect.py",
    "scripts/host_cutover_worker_recovery.py",
}
FIXTURE_RECOVERY = (
    "def main(argv):\n"
    "    if argv != ['host']:\n"
    "        return 3\n"
    "    print('BOCA_RECOVERY_FIXTURE state=PASS host=UNTOUCHED')\n"
    "    return 0\n"
).encode("ascii")


def _fixture_root(tmp_path: Path) -> Path:
    """Use real dependencies, with a harmless synthetic recovery entrypoint."""
    repository = tmp_path / "repository"
    paths = {
        "src/boca_socios/__init__.py",
        "src/boca_socios/host_boca_cleanup.py",
        "docker/seccomp_profile.json",
        "scripts/__init__.py",
        "scripts/host_cutover_worker_inspect.py",
    }
    for name in paths:
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    recovery = repository / "scripts/host_cutover_worker_recovery.py"
    recovery.write_bytes(FIXTURE_RECOVERY)
    return repository


def _cli_build(repository: Path, target: Path) -> tuple[bytes, str]:
    command = subprocess.run(  # noqa: S603 - trusted local Python/builder fixture
        [
            sys.executable,
            str(ROOT / "scripts/build_protected_boca_bundle.py"),
            "--worker-recovery",
            str(repository),
            str(target),
        ],
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert command.returncode == 0, (command.stdout, command.stderr)
    digest = command.stdout.decode("ascii").strip().removeprefix("BOCA_PROTECTED_BUNDLE sha256=")
    assert len(digest) == 64
    return target.read_bytes(), digest


def _boot(
    raw: bytes, digest: str, mode: str = "cutover-worker-recover", *args: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - local stdlib-only memfd contract
        [
            sys.executable,
            "-S",
            str(ROOT / "scripts/boca_protected_memfd_bootstrap.py"),
            digest,
            mode,
            *args,
        ],
        input=raw,
        capture_output=True,
        check=False,
        timeout=15,
    )


def test_recovery_cli_builds_only_seven_reviewed_entries(tmp_path: Path) -> None:
    raw, digest = _cli_build(_fixture_root(tmp_path), tmp_path / "worker-recover.pyz")
    assert hashlib.sha256(raw).hexdigest() == digest
    assert len(raw) <= 128_000
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        assert set(package.namelist()) == EXPECTED_RECOVERY
        assert package.read("scripts/host_cutover_worker_recovery.py") == FIXTURE_RECOVERY
        assert (
            package.read("scripts/host_cutover_worker_inspect.py")
            == (ROOT / "scripts/host_cutover_worker_inspect.py").read_bytes()
        )
        assert sum(item.file_size for item in package.infolist()) <= 256_000
    bootstrap.verify(raw, digest, recovery=True)
    with pytest.raises(ValueError, match="allowlist"):
        bootstrap.verify(raw, digest)
    assert builder.MAX_SOURCE_BYTES == bootstrap.MAX_UNCOMPRESSED == 1_100_000
    assert builder.MAX_ARCHIVE_BYTES == bootstrap.MAX_ZIP == 512_000


def test_recovery_zip_executes_only_its_fixed_host_entrypoint(tmp_path: Path) -> None:
    raw, digest = _cli_build(_fixture_root(tmp_path), tmp_path / "worker-recover.pyz")
    allowed = _boot(raw, digest)
    assert allowed.returncode == 0, (allowed.stdout, allowed.stderr)
    assert allowed.stdout == b"BOCA_RECOVERY_FIXTURE state=PASS host=UNTOUCHED\n"
    assert allowed.stderr == b""
    for mode, args in (
        ("bundle-selftest", ()),
        ("cutover-worker-recover", ("unreviewed-cid",)),
    ):
        refused = _boot(raw, digest, mode, *args)
        assert refused.returncode != 0
        assert b"state=PASS" not in refused.stdout


def test_recovery_and_full_bundle_are_distinct_verified_variants(tmp_path: Path) -> None:
    raw, digest = _cli_build(_fixture_root(tmp_path), tmp_path / "worker-recover.pyz")
    full = tmp_path / "complete.pyz"
    full_digest = builder.build(ROOT, full)
    full_raw = full.read_bytes()
    bootstrap.verify(full_raw, full_digest)
    # The full payload may be rejected by either smaller ZIP cap or entry set.
    with pytest.raises(ValueError):
        bootstrap.verify(full_raw, full_digest, recovery=True)
    refused = _boot(full_raw, full_digest)
    assert refused.returncode == 1
    assert b"state=PASS" not in refused.stdout
    assert builder.build(ROOT, tmp_path / "complete-again.pyz") == full_digest
    assert hashlib.sha256(raw).hexdigest() == digest


def test_recovery_tamper_or_extra_entry_fails_before_exec(tmp_path: Path) -> None:
    raw, digest = _cli_build(_fixture_root(tmp_path), tmp_path / "worker-recover.pyz")
    changed = bytearray(raw)
    changed[50] ^= 1
    assert _boot(bytes(changed), digest).returncode == 1
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    extra = tmp_path / "with-extra.pyz"
    with zipfile.ZipFile(extra, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in {**entries, "unreviewed.py": b"print('FORBIDDEN')\n"}.items():
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data)
    altered = extra.read_bytes()
    assert _boot(altered, hashlib.sha256(altered).hexdigest()).returncode == 1


def test_recovery_source_cap_and_fresh_target_are_independent(tmp_path: Path) -> None:
    repository = _fixture_root(tmp_path)
    accepted = tmp_path / "accepted.pyz"
    raw, _digest = _cli_build(repository, accepted)
    assert len(raw) <= 128_000
    total = sum((repository / name).stat().st_size for name in builder.RECOVERY_SOURCES)
    assert total < builder.RECOVERY_MAX_SOURCE_BYTES == 256_000
    with pytest.raises(ValueError, match="fresh artifact"):
        builder.build_worker_recovery(repository, accepted)
    # The hard budget is enforced before producing an artifact.
    rejected = tmp_path / "rejected.pyz"
    source = repository / "scripts/host_cutover_worker_recovery.py"
    source.write_bytes(FIXTURE_RECOVERY + b"#" * 120_000)
    with pytest.raises(ValueError, match="bounded contract"):
        builder.build_worker_recovery(repository, rejected)
    assert not rejected.exists()


def test_recovery_rejects_untrusted_source_symlink(tmp_path: Path) -> None:
    repository = _fixture_root(tmp_path)
    source = repository / "scripts/host_cutover_worker_recovery.py"
    source.unlink()
    source.symlink_to(ROOT / "scripts/host_cutover_worker_inspect.py")
    with pytest.raises(ValueError, match="symlink"):
        builder.build_worker_recovery(repository, tmp_path / "unsafe.pyz")
