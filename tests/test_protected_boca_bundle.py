"""PR-only offline transport smoke: no host/Docker/blackbox access."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def _build(tmp_path: Path) -> tuple[Path, str]:
    output = tmp_path / "protected.pyz"
    return output, builder.build(ROOT, output)


def _run(
    raw: bytes, digest: str, mode: str = "bundle-selftest"
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed local Python and tested bootstrap path
        [sys.executable, str(ROOT / "scripts" / "boca_protected_memfd_bootstrap.py"), digest, mode],
        input=raw,
        capture_output=True,
        timeout=15,
        check=False,
    )


def test_verified_memfd_zip_selftest_never_touches_host(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    assert len(raw) <= builder.MAX_ARCHIVE_BYTES
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        names = set(package.namelist())
        assert names in (
            bootstrap.EXPECTED_ENTRIES,
            bootstrap.EXPECTED_ENTRIES | bootstrap.OPTION_B_ENTRIES,
        )
        assert all("synthetic.py" not in name and "ipc_worker.py" not in name for name in names)
        assert package.read("compose.yaml") == (ROOT / "compose.yaml").read_bytes()
        assert package.read("compose.beta.yaml") == (ROOT / "compose.beta.yaml").read_bytes()
        assert (
            package.read("compose.beta.browser.yaml")
            == (ROOT / "compose.beta.browser.yaml").read_bytes()
        )
        assert (
            package.read("docker/seccomp_profile.json")
            == (ROOT / "docker/seccomp_profile.json").read_bytes()
        )
    result = _run(raw, digest)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == b"BOCA_BUNDLE_SELFTEST state=PASS host=untouched blackbox=excluded\n"


def test_effectful_dispatch_deliberately_no_go_and_no_host(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    result = _run(output.read_bytes(), digest, "protected-beta-install")
    assert result.returncode == 3
    assert result.stdout == b"BOCA_PROTECTED_INSTALL state=NO_GO reason=transaction_not_wired\n"


def test_tampered_transport_fails_before_import_or_dispatch(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    raw = bytearray(output.read_bytes())
    raw[50] ^= 1
    result = _run(bytes(raw), digest)
    assert result.returncode == 1
    assert b"state=PASS" not in result.stdout


def test_option_b_sql_and_stdlib_helper_must_be_both_present(tmp_path: Path) -> None:
    copied = tmp_path / "repository"
    copied.mkdir()
    for rel in builder.SOURCES:
        to = copied / rel
        to.parent.mkdir(parents=True, exist_ok=True)
        to.write_bytes((ROOT / rel).read_bytes())
    stdlib = copied / builder.OPTION_B_SOURCES[0]
    stdlib.parent.mkdir(parents=True, exist_ok=True)
    stdlib.write_bytes(b"# unreviewed partial B\n")
    with pytest.raises(ValueError, match="both reviewed"):
        builder.build(copied, tmp_path / "incomplete.pyz")
    sql = copied / builder.OPTION_B_SOURCES[1]
    sql.parent.mkdir(parents=True, exist_ok=True)
    sql.write_bytes(b"CREATE TABLE example (id TEXT);\n")
    output = tmp_path / "complete.pyz"
    digest = builder.build(copied, output)
    with zipfile.ZipFile(output) as package:
        assert set(package.namelist()) == (bootstrap.EXPECTED_ENTRIES | bootstrap.OPTION_B_ENTRIES)
    result = _run(output.read_bytes(), digest)
    assert result.returncode == 0


def test_unreviewed_zip_entry_rejected_even_with_matching_digest(tmp_path: Path) -> None:
    output, _ = _build(tmp_path)
    with zipfile.ZipFile(io.BytesIO(output.read_bytes()), "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}
    extra = tmp_path / "extra.pyz"
    with zipfile.ZipFile(extra, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
        item = zipfile.ZipInfo("boca_socios/browser/synthetic.py", (1980, 1, 1, 0, 0, 0))
        item.external_attr = 0o100644 << 16
        archive.writestr(item, b"BLOCKED")
    raw = extra.read_bytes()
    result = _run(raw, hashlib.sha256(raw).hexdigest())
    assert result.returncode == 1
    assert b"state=PASS" not in result.stdout


def test_bundle_deterministic_and_target_overwrite_forbidden(tmp_path: Path) -> None:
    one, digest_one = _build(tmp_path)
    with pytest.raises(ValueError, match="fresh artifact"):
        builder.build(ROOT, one)
    two = tmp_path / "second.pyz"
    digest_two = builder.build(ROOT, two)
    assert digest_one == digest_two
    assert one.read_bytes() == two.read_bytes()


def test_symlink_target_forbidden(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign"
    foreign.write_text("preserve")
    marker = tmp_path / "linked.pyz"
    marker.symlink_to(foreign)
    with pytest.raises(ValueError, match="fresh artifact"):
        builder.build(ROOT, marker)
    assert foreign.read_text() == "preserve"
