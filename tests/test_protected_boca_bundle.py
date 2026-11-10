"""PR-only offline transport smoke: no host/Docker/blackbox access."""

from __future__ import annotations

import base64
import hashlib
import io
import json
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
    raw: bytes,
    digest: str,
    mode: str = "bundle-selftest",
    *arguments: str,
    stdlib_only: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed local Python and tested bootstrap path
        [
            sys.executable,
            *(["-S"] if stdlib_only else []),
            str(ROOT / "scripts" / "boca_protected_memfd_bootstrap.py"),
            digest,
            mode,
            *arguments,
        ],
        input=raw,
        capture_output=True,
        timeout=15,
        check=False,
    )


def test_bounded_source_growth_keeps_archive_digest_and_archive_limit_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = (*builder.SOURCES, *builder.OPTION_B_SOURCES)
    total = sum((ROOT / item).stat().st_size for item in sources)
    assert 830_000 < total < builder.MAX_SOURCE_BYTES == 926_000
    assert builder.MAX_ARCHIVE_BYTES == 512_000
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    assert len(raw) <= builder.MAX_ARCHIVE_BYTES
    assert hashlib.sha256(raw).hexdigest() == digest
    bootstrap.verify(raw, digest)
    assert bootstrap.MAX_ZIP == 512_000
    assert bootstrap.MAX_UNCOMPRESSED == builder.MAX_SOURCE_BYTES
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        total_uncompressed = sum(item.file_size for item in package.infolist())
    monkeypatch.setattr(bootstrap, "MAX_UNCOMPRESSED", total_uncompressed - 1)
    with pytest.raises(ValueError, match="entry allowlist mismatch"):
        bootstrap.verify(raw, digest)
    monkeypatch.setattr(bootstrap, "MAX_UNCOMPRESSED", builder.MAX_SOURCE_BYTES)
    with pytest.raises(ValueError, match="SHA/size mismatch"):
        bootstrap.verify(raw, "0" * 64)
    # A one-byte-shorter hard cap must still fail before writing any output.
    monkeypatch.setattr(builder, "MAX_SOURCE_BYTES", total - 1)
    rejected = tmp_path / "rejected.pyz"
    with pytest.raises(ValueError, match="total exceeds bounded contract"):
        builder.build(ROOT, rejected)
    assert not rejected.exists()


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
        assert "boca_socios/integration/command_host.py" not in names
        assert "boca_socios/security/credential_vault.py" not in names
        assert package.read("boca_socios/panel/__init__.py").startswith(b'"""Protected host')
        assert package.read("boca_socios/integration/__init__.py").startswith(b'"""Protected host')
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


def test_stage_recovery_transport_is_self_contained_and_rejects_invalid_incident(
    tmp_path: Path,
) -> None:
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    result = _run(raw, digest, "cutover-stage-recover", "0", "0", stdlib_only=True)
    assert result.returncode == 3
    assert result.stdout == b""
    assert b"BOCA_STAGE_RECOVERY state=NO_GO" in result.stderr


def test_cutover_memfd_end_to_end_selftest_and_unapproved_apply_are_inert(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    tested = _run(raw, digest, "bundle-cutover-selftest")
    assert tested.returncode == 0, (tested.stdout, tested.stderr)
    assert tested.stdout == b"BOCA_CUTOVER_MEMFD state=PASS host=untouched option_b=present\n"

    invocation = {
        "version": "boca-cutover-a-host-invocation-v1",
        "plan": {
            "attempt_id": "42025021984",
            "legacy_id": "1" * 64,
            "legacy_sha": "a" * 40,
            "legacy_image": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "2" * 64,
            "legacy_compose_sha": "3" * 64,
            "target_sha": "b" * 40,
            "target_image": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "4" * 64,
            "browser_image": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "5" * 64,
            "target_compose_sha": hashlib.sha256(
                (ROOT / "compose.beta.yaml").read_bytes()
            ).hexdigest(),
            "overlay_sha": hashlib.sha256(
                (ROOT / "compose.beta.browser.yaml").read_bytes()
            ).hexdigest(),
            "seccomp_sha": hashlib.sha256(
                (ROOT / "docker/seccomp_profile.json").read_bytes()
            ).hexdigest(),
            "owner_subject": "synthetic_owner",
            "origin": "http://localhost:8443",
        },
        "bundle_sha256": digest,
        "go_binding_sha256": "6" * 64,
    }
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(invocation, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    refused = _run(raw, digest, "cutover-a-apply", encoded)
    assert refused.returncode == 3, (refused.stdout, refused.stderr)
    assert refused.stdout == (
        b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=UNVERIFIED runtime=UNVERIFIED\n"
    )


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


def test_lifecycle_memfd_stdlib_only_import_and_no_go_without_context(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    tested = _run(raw, digest, "lifecycle-bridge-selftest", stdlib_only=True)
    assert tested.returncode == 0, (tested.stdout, tested.stderr)
    assert tested.stdout == (b"BOCA_LIFECYCLE_MEMFD state=PASS host=untouched blackbox=excluded\n")
    missing_go = _run(raw, digest, "lifecycle-apply", stdlib_only=True)
    assert missing_go.returncode == 3
    assert json.loads(missing_go.stdout)["status"] == "NO_GO"


def test_lifecycle_observer_memfd_stdlib_and_readonly_no_context(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        names = set(package.namelist())
        assert "boca_socios/host_lifecycle_observe.py" in names
        assert "boca_socios/browser/synthetic.py" not in names
        assert "boca_socios/browser/ipc_worker.py" not in names
    selftest = _run(raw, digest, "lifecycle-observe-selftest", stdlib_only=True)
    assert selftest.returncode == 0, (selftest.stdout, selftest.stderr)
    assert selftest.stdout == (
        b"BOCA_LIFECYCLE_OBSERVE_MEMFD state=PASS host=untouched blackbox=excluded\n"
    )
    missing = _run(raw, digest, "lifecycle-observe", stdlib_only=True)
    assert missing.returncode == 3
    assert missing.stdout == b""
    assert missing.stderr == b"BOCA_LIFECYCLE_OBSERVE state=NO_GO\n"


def test_cutover_inventory_observer_in_protected_memfd_without_host(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        names = set(package.namelist())
        assert "boca_socios/host_cutover_inventory_observe.py" in names
        assert "boca_socios/browser/synthetic.py" not in names
        assert "boca_socios/browser/ipc_worker.py" not in names
    smoke = _run(raw, digest, "cutover-inventory-selftest", stdlib_only=True)
    assert smoke.returncode == 0, (smoke.stdout, smoke.stderr)
    assert smoke.stdout == (
        b"BOCA_CUTOVER_INVENTORY_MEMFD state=PASS host=untouched blackbox=excluded\n"
    )
    missing = _run(raw, digest, "cutover-inventory-observe", stdlib_only=True)
    assert missing.returncode == 3
    assert missing.stdout == b""
    assert missing.stderr == b"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO\n"


def test_official_inventory_observer_in_memfd_without_mutation(tmp_path: Path) -> None:
    output, digest = _build(tmp_path)
    raw = output.read_bytes()
    smoke = _run(raw, digest, "official-inventory-selftest", stdlib_only=True)
    assert smoke.returncode == 0, (smoke.stdout, smoke.stderr)
    assert smoke.stdout == (
        b"BOCA_OFFICIAL_INVENTORY_MEMFD state=PASS host=untouched blackbox=excluded\n"
    )
    missing = _run(raw, digest, "official-inventory-observe", stdlib_only=True)
    assert missing.returncode == 3
    assert missing.stdout == b""
    assert missing.stderr == b"BOCA_OFFICIAL_INVENTORY_OBSERVE state=NO_GO\n"
