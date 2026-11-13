"""R247 exact V2 evidence archive; host-side parsing is never GitHub authority."""

from __future__ import annotations

import ast
import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from boca_socios import host_boca_current_pair_v2 as current
from test_r247_runner_current_pair_v2 import NOW, _inputs_for_runner, runner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def _authenticated_directory(tmp_path: Path) -> Path:
    github, catalog, args, folder = _inputs_for_runner(tmp_path)
    runner.attest_runner(*args, github=github, release_catalog=catalog, now=NOW)
    return folder


def _rewrite_current_v2(source: bytes, *, change: str) -> bytes:
    record = current.verify_current_pair_v2(source)
    payload = {key: value for key, value in record.items() if key != "integrity_sha256"}
    if change == "pair":
        payload["previous_controller_id"] = "f" * 64
    elif change == "historical_creator":
        payload["historical_resource_custody"]["creator_ipc_inode_sha256"] = "f" * 64
    elif change == "target":
        payload["target_main_sha"] = "f" * 40
    payload["integrity_sha256"] = hashlib.sha256(current._canonical(payload)).hexdigest()
    return current._PREFIX + current._canonical(payload)


def test_builder_and_bootstrap_allow_exact_eight_authenticated_evidence_files(
    tmp_path: Path,
) -> None:
    evidence = _authenticated_directory(tmp_path)
    target = tmp_path / "paired.pyz"
    digest = builder.build(ROOT, target, pair_upgrade=True, pair_upgrade_release_dir=evidence)
    bootstrap.verify(target.read_bytes(), digest, pair_upgrade=True)
    with zipfile.ZipFile(io.BytesIO(target.read_bytes())) as archive:
        assert set(archive.namelist()) == bootstrap.PAIR_UPGRADE_ENTRIES
        assert len([name for name in archive.namelist() if name.startswith("release/")]) == 8
        assert (
            archive.read("release/current-pair-v2.receipt")
            == (evidence / "current-pair-v2.receipt").read_bytes()
        )
        assert archive.read("release/retained-proof.json") == b'{"state":"NO_GO"}\n'
        assert "boca_socios/host_boca_successor_integrations.py" in archive.namelist()
        assert "boca_socios/host_boca_current_pair_v2.py" in archive.namelist()
        assert "boca_socios/host_boca_upgrade_failure_cleanup_v2.py" in archive.namelist()
        assert "boca_socios/host_boca_successor_physical_v2.py" in archive.namelist()
        # R258's measured successor closure may now fit the reviewed 1.5MB
        # bound without compaction. If it does not, ONLY comment tokens may
        # disappear, preserving AST, bytecode and exact source line counts.
        compacted = []
        for source in builder.PAIR_UPGRADE_SOURCES:
            if not source.endswith(".py"):
                continue
            name = source.removeprefix("src/")
            original = (ROOT / source).read_bytes()
            packaged = archive.read(name)
            assert ast.dump(ast.parse(packaged)) == ast.dump(ast.parse(original))
            assert compile(packaged, name, "exec") == compile(original, name, "exec")
            assert packaged.count(b"\n") == original.count(b"\n")
            if packaged != original:
                compacted.append(name)
        source_names = {rel.removeprefix("src/") for rel in builder.PAIR_UPGRADE_SOURCES}
        original_total = sum((ROOT / rel).stat().st_size for rel in builder.PAIR_UPGRADE_SOURCES)
        original_total += sum(
            len(archive.read(name)) for name in archive.namelist() if name not in source_names
        )
        assert bool(compacted) is (
            original_total
            > builder.PAIR_UPGRADE_MAX_SOURCE_BYTES - builder.PAIR_UPGRADE_MIN_SOURCE_RESERVE
        )
        assert (
            sum(item.file_size for item in archive.infolist())
            <= builder.PAIR_UPGRADE_MAX_SOURCE_BYTES
        )
        assert target.stat().st_size <= builder.PAIR_UPGRADE_MAX_ARCHIVE_BYTES
        assert (
            current.verify_current_pair_v2(archive.read("release/current-pair-v2.receipt"))[
                "apply_authorized"
            ]
            is False
        )
    # Standalone memfd import graph must work without PYTHONPATH or this repo
    # on sys.path. An allowlisted but missing transitive host module is NO_GO.
    check = subprocess.run(  # noqa: S603 - fixed executable/local verified ZIP
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0,sys.argv[1]); "
            "from boca_socios import host_boca_pair_upgrade_cli; "
            "from boca_socios import host_boca_successor_integrations; "
            "from boca_socios import host_boca_upgrade_failure_cleanup_v2; "
            "from boca_socios import host_boca_successor_physical_v2",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    assert check.returncode == 0, check.stderr


@pytest.mark.parametrize(
    "change",
    [
        "missing_v2",
        "extra",
        "v2_symlink",
        "v2_tamper",
        "pair",
        "target",
        "historical_creator",
        "historical_missing",
        "sentinel_changed",
        "retained_symlink",
    ],
)
def test_builder_fails_closed_on_directory_or_evidence_mismatch(
    tmp_path: Path, change: str
) -> None:
    evidence = _authenticated_directory(tmp_path)
    v2 = evidence / "current-pair-v2.receipt"
    if change == "missing_v2":
        v2.unlink()
    elif change == "extra":
        (evidence / "untrusted.env").write_text("none")
    elif change == "v2_symlink":
        v2.unlink()
        v2.symlink_to(evidence / "boca-retained-observation.receipt")
    elif change == "v2_tamper":
        v2.write_bytes(v2.read_bytes() + b"X")
    elif change in {"pair", "target", "historical_creator"}:
        v2.write_bytes(_rewrite_current_v2(v2.read_bytes(), change=change))
    elif change == "historical_missing":
        (evidence / "boca-retained-observation.receipt").unlink()
    elif change == "sentinel_changed":
        (evidence / "retained-proof.json").write_bytes(b'{"state":"GO"}\n')
    elif change == "retained_symlink":
        history = evidence / "boca-retained-observation.receipt"
        history.unlink()
        history.symlink_to(v2)
    target = tmp_path / "reject.pyz"
    with pytest.raises(ValueError, match="Boca"):
        builder.build(ROOT, target, pair_upgrade=True, pair_upgrade_release_dir=evidence)
    assert not target.exists()


@pytest.mark.parametrize(
    "omit,extra", [("release/current-pair-v2.receipt", None), (None, "release/extra.bin")]
)
def test_memfd_bootstrap_rejects_missing_or_extra_member_even_if_digest_recomputed(
    tmp_path: Path, omit: str | None, extra: str | None
) -> None:
    evidence = _authenticated_directory(tmp_path)
    target = tmp_path / "original.pyz"
    builder.build(ROOT, target, pair_upgrade=True, pair_upgrade_release_dir=evidence)
    source = io.BytesIO(target.read_bytes())
    modified = io.BytesIO()
    with (
        zipfile.ZipFile(source) as first,
        zipfile.ZipFile(modified, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output,
    ):
        for member in first.namelist():
            if member != omit:
                output.writestr(member, first.read(member))
        if extra is not None:
            output.writestr(extra, b"NO_GO")
    rebuilt = modified.getvalue()
    with pytest.raises(ValueError, match="allowlist"):
        bootstrap.verify(rebuilt, hashlib.sha256(rebuilt).hexdigest(), pair_upgrade=True)
