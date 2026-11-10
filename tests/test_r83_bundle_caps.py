"""R83 TDD: isolated seven-entry worker preflight transport, no broader Cutover cap.

The fixtures contain artificial bytes only. Tests never run Docker, SSH, GitHub,
host operations, or BLACKBOX code.
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402

WORKER_SOURCES = (
    "docker/seccomp_profile.json",
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_first_deploy.py",
    "src/boca_socios/host_boca_cleanup.py",
    "scripts/__init__.py",
    "scripts/host_cutover_worker_preflight.py",
)
WORKER_ENTRIES = frozenset({"__main__.py", *(item.removeprefix("src/") for item in WORKER_SOURCES)})
WORKER_SOURCE_CAP = 520_000
WORKER_ZIP_CAP = 128_000
INVALID_COORDINATES = ("bad-coordinate",) * 7


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def real_archives(tmp_path: Path) -> dict[str, tuple[bytes, str]]:
    """Three reviewed transports without running their contents."""
    results: dict[str, tuple[bytes, str]] = {}
    for mode, kwargs in (
        ("full", {}),
        ("worker", {"worker_preflight": True}),
        ("recovery", {"worker_recovery": True}),
    ):
        path = tmp_path / f"{mode}.pyz"
        digest = builder.build(ROOT, path, **kwargs)
        results[mode] = path.read_bytes(), digest
    return results


def _synthetic_sources(root: Path) -> None:
    for relative in WORKER_SOURCES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"X")


def _build_synthetic_worker_to_exact_source_size(
    tmp_path: Path, total: int
) -> tuple[Path, bytes, str]:
    """Discover the real generated __main__ length; pad one allowlisted source."""
    root = tmp_path / "synthetic-repo"
    _synthetic_sources(root)
    initial = tmp_path / "small.pyz"
    builder.build(root, initial, worker_preflight=True)
    with zipfile.ZipFile(initial) as package:
        boot_size = package.getinfo("__main__.py").file_size
    last = root / WORKER_SOURCES[-1]
    last.write_bytes(b"X" * (total - boot_size - len(WORKER_SOURCES) + 1))
    target = tmp_path / "bounded-worker.pyz"
    if total > WORKER_SOURCE_CAP:
        with pytest.raises(ValueError, match="bounded|oversized|exceeds"):
            builder.build(root, target, worker_preflight=True)
        assert not target.exists()
        return target, b"", ""
    digest = builder.build(root, target, worker_preflight=True)
    return target, target.read_bytes(), digest


def _zip_with_entries(
    names: tuple[str, ...],
    *,
    filler: int = 1,
    special: str | None = None,
    stored: bool = False,
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        for index, name in enumerate(names):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            entry.create_system = 3
            mode = (stat.S_IFLNK | 0o777) if name == special else (stat.S_IFREG | 0o644)
            entry.external_attr = mode << 16
            package.writestr(entry, b"X" * filler if index == 0 else b"Y")
    return stream.getvalue()


def _zip_of_exact_size(size: int) -> bytes:
    """Use STORED to make an exact 128000/128001-byte ZIP, not zip-bomb inference."""
    names = tuple(sorted(WORKER_ENTRIES))
    baseline = _zip_with_entries(names, stored=True)
    payload = size - len(baseline) + 1
    assert payload > 0
    result = _zip_with_entries(names, filler=payload, stored=True)
    assert len(result) == size
    return result


def test_transport_caps_are_separate_from_full_cutover_and_recovery() -> None:
    assert builder.MAX_SOURCE_BYTES == bootstrap.MAX_UNCOMPRESSED == 1_100_000
    assert builder.MAX_ARCHIVE_BYTES == bootstrap.MAX_ZIP == 512_000
    assert builder.RECOVERY_MAX_SOURCE_BYTES == bootstrap.RECOVERY_MAX_UNCOMPRESSED == 256_000
    assert builder.RECOVERY_MAX_ARCHIVE_BYTES == bootstrap.RECOVERY_MAX_ZIP == 128_000
    assert builder.PREFLIGHT_MAX_SOURCE_BYTES == bootstrap.PREFLIGHT_MAX_UNCOMPRESSED == 520_000
    assert builder.PREFLIGHT_MAX_ARCHIVE_BYTES == bootstrap.PREFLIGHT_MAX_ZIP == 128_000
    assert "scripts/host_cutover_worker_preflight.py" not in builder.SOURCES


def test_protected_pr_gate_actually_runs_the_new_bundle_boundary_matrix() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    header = "      - name: Validate protected Cutover A, Option B ZIP and cleanup offline only"
    assert workflow.count(header) == 1
    gate = workflow.split(header, 1)[1].split("\n      - name:", 1)[0]
    assert "tests/test_r83_bundle_caps.py" in gate
    assert "uv run pytest -q" in gate


def test_worker_archive_has_exactly_seven_allowlisted_entries_and_no_other_dispatch(
    tmp_path: Path,
) -> None:
    target = tmp_path / "worker.pyz"
    digest = builder.build(ROOT, target, worker_preflight=True)
    raw = target.read_bytes()
    assert 0 < len(raw) <= WORKER_ZIP_CAP
    assert digest == _sha(raw)
    bootstrap.verify(raw, digest, worker_preflight=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        assert frozenset(package.namelist()) == WORKER_ENTRIES
        assert len(package.namelist()) == 7
        assert sum(entry.file_size for entry in package.infolist()) <= WORKER_SOURCE_CAP
        main = package.read("__main__.py")
    assert b"cutover-worker-preflight" in main
    assert b"cutover-stage-recover" not in main
    assert b"lifecycle-apply" not in main
    assert b"cutover-worker-recover" not in main
    assert b"host_boca_transaction" not in main


@pytest.mark.parametrize(
    "source_size,allowed", [(WORKER_SOURCE_CAP, True), (WORKER_SOURCE_CAP + 1, False)]
)
def test_builder_exact_worker_source_size_boundary(
    tmp_path: Path, source_size: int, allowed: bool
) -> None:
    target, raw, digest = _build_synthetic_worker_to_exact_source_size(tmp_path, source_size)
    if allowed:
        assert target.is_file()
        assert 0 < len(raw) <= WORKER_ZIP_CAP
        assert digest == _sha(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            assert frozenset(package.namelist()) == WORKER_ENTRIES
            assert sum(entry.file_size for entry in package.infolist()) == source_size
        bootstrap.verify(raw, digest, worker_preflight=True)
    else:
        assert not target.exists()


@pytest.mark.parametrize("zip_size,allowed", [(WORKER_ZIP_CAP, True), (WORKER_ZIP_CAP + 1, False)])
def test_bootstrap_exact_worker_zip_size_boundary(zip_size: int, allowed: bool) -> None:
    raw = _zip_of_exact_size(zip_size)
    if allowed:
        bootstrap.verify(raw, _sha(raw), worker_preflight=True)
    else:
        with pytest.raises(ValueError, match="SHA/size mismatch"):
            bootstrap.verify(raw, _sha(raw), worker_preflight=True)


def test_bootstrap_rejects_worker_uncompressed_overcap_even_with_valid_digest() -> None:
    raw = _zip_with_entries(tuple(sorted(WORKER_ENTRIES)), filler=WORKER_SOURCE_CAP)
    assert len(raw) < WORKER_ZIP_CAP
    with pytest.raises(ValueError, match="allowlist|size"):
        bootstrap.verify(raw, _sha(raw), worker_preflight=True)


def test_worker_builder_rejects_archive_over_128k_even_when_sources_within_480k(
    tmp_path: Path,
) -> None:
    root = tmp_path / "incompressible-sources"
    _synthetic_sources(root)
    # Deterministic incompressible input; per-source and aggregate remain <480k.
    (root / WORKER_SOURCES[-1]).write_bytes(
        hashlib.shake_256(b"worker-preflight-zip-cap").digest(145_000)
    )
    output = tmp_path / "too-large-worker.pyz"
    with pytest.raises(ValueError, match="ZIP exceeds bounded contract"):
        builder.build(root, output, worker_preflight=True)
    # Builder retains its own partial/rejected artifact as forensic evidence.
    assert output.is_file()
    assert output.stat().st_size > WORKER_ZIP_CAP


def test_bundle_modes_are_nonreplayable_even_with_correct_hash(
    tmp_path: Path, real_archives: dict[str, tuple[bytes, str]]
) -> None:
    full, full_hash = real_archives["full"]
    worker, worker_hash = real_archives["worker"]
    recovery, recovery_hash = real_archives["recovery"]
    bootstrap.verify(full, full_hash)
    bootstrap.verify(worker, worker_hash, worker_preflight=True)
    bootstrap.verify(recovery, recovery_hash, recovery=True)

    with zipfile.ZipFile(io.BytesIO(full)) as package:
        assert "scripts/host_cutover_worker_preflight.py" not in package.namelist()
        assert b"cutover-worker-preflight" not in package.read("__main__.py")

    for raw, digest, wrong_flags in (
        (full, full_hash, {"worker_preflight": True}),
        (full, full_hash, {"recovery": True}),
        (worker, worker_hash, {}),
        (worker, worker_hash, {"recovery": True}),
        (recovery, recovery_hash, {}),
        (recovery, recovery_hash, {"worker_preflight": True}),
    ):
        with pytest.raises(ValueError):
            bootstrap.verify(raw, digest, **wrong_flags)

    with pytest.raises(ValueError):
        bootstrap.verify(worker, worker_hash, recovery=True, worker_preflight=True)
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "ambiguous.pyz", worker_recovery=True, worker_preflight=True)
    assert not (tmp_path / "ambiguous.pyz").exists()


def test_actual_worker_memfd_runs_under_stdlib_only_python_and_rejects_bad_pins(
    tmp_path: Path, real_archives: dict[str, tuple[bytes, str]]
) -> None:
    """Import closure must succeed from the seven-entry ZIP, before host lease."""
    raw, digest = real_archives["worker"]
    isolated_env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"}
    }
    isolated_env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(  # noqa: S603 - local bootstrap with fake pins only
        (
            sys.executable,
            "-S",
            str(ROOT / "scripts" / "boca_protected_memfd_bootstrap.py"),
            digest,
            "cutover-worker-preflight",
            *INVALID_COORDINATES,
        ),
        input=raw,
        cwd=tmp_path,
        env=isolated_env,
        capture_output=True,
        timeout=12,
        check=False,
    )
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert result.stderr == b""
    assert result.stdout == (
        b"BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO failed_phase=UNVERIFIED "
        b"cleanup=UNVERIFIED primary_failed_phase=UNVERIFIED "
        b"cleanup_failed_stage=UNVERIFIED stop_failure_cause=UNVERIFIED\n"
    )


@pytest.mark.parametrize(
    "archive_mode,operation,extra_args",
    [
        ("full", "cutover-worker-preflight", INVALID_COORDINATES),
        ("recovery", "cutover-worker-preflight", INVALID_COORDINATES),
        ("worker", "bundle-selftest", ()),
        ("worker", "cutover-stage-recover", ()),
        ("worker", "cutover-a-apply", ()),
        ("worker", "cutover-worker-recover", ()),
        ("worker", "cutover-worker-807-recover", ()),
        ("full", "cutover-worker-recover", ()),
        ("recovery", "bundle-selftest", ()),
    ],
)
def test_cli_rejects_cross_mode_replay_before_any_memfd_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    real_archives: dict[str, tuple[bytes, str]],
    archive_mode: str,
    operation: str,
    extra_args: tuple[str, ...],
) -> None:
    raw, digest = real_archives[archive_mode]

    class FakeStdin:
        buffer = io.BytesIO(raw)

    def no_memfd(*_args: object, **_kwargs: object) -> int:
        pytest.fail("cross-mode ZIP reached memfd creation")

    monkeypatch.setattr(bootstrap.sys, "stdin", FakeStdin())
    monkeypatch.setattr(bootstrap.sys, "argv", ["bootstrap.py", digest, operation, *extra_args])
    monkeypatch.setattr(bootstrap.os, "memfd_create", no_memfd)
    assert bootstrap.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "BOCA_BUNDLE state=NO_GO reason=hash_or_host_runtime\n"


def test_worker_digest_remains_mandatory(tmp_path: Path) -> None:
    target = tmp_path / "worker.pyz"
    digest = builder.build(ROOT, target, worker_preflight=True)
    raw = target.read_bytes()
    bootstrap.verify(raw, digest, worker_preflight=True)
    with pytest.raises(ValueError, match="SHA/size mismatch"):
        bootstrap.verify(raw, "0" * 64, worker_preflight=True)


@pytest.mark.parametrize(
    "attack", ["extra", "missing", "duplicate", "symlink", "directory", "traversal"]
)
def test_worker_bootstrap_rejects_hostile_entries_even_with_correct_digest(attack: str) -> None:
    names = list(sorted(WORKER_ENTRIES))
    if attack == "extra":
        names.append("scripts/unreviewed.py")
    elif attack == "missing":
        names.pop()
    elif attack == "duplicate":
        names.append(names[0])
    elif attack == "directory":
        names[0] = names[0] + "/"
    elif attack == "traversal":
        names.append("../escape.py")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        raw = _zip_with_entries(tuple(names), special=names[0] if attack == "symlink" else None)
    assert len(raw) < WORKER_ZIP_CAP
    with pytest.raises(ValueError):
        bootstrap.verify(raw, _sha(raw), worker_preflight=True)


def test_builder_refuses_symlink_source_without_creating_output(tmp_path: Path) -> None:
    root = tmp_path / "synthetic"
    _synthetic_sources(root)
    source = root / WORKER_SOURCES[-1]
    source.unlink()
    target_data = tmp_path / "benign-source"
    target_data.write_bytes(b"X")
    source.symlink_to(target_data)
    output = tmp_path / "no-worker.pyz"
    with pytest.raises(ValueError, match="symlink"):
        builder.build(root, output, worker_preflight=True)
    assert not output.exists()
