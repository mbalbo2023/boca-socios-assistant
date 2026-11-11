"""R82 RED: only two fixed host modes in the same minimal recovery memfd ZIP.

Every execution in this module uses a harmless synthetic recovery entrypoint;
it never calls Docker, SSH, GitHub Actions, or the production host recovery.
"""

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

R80_MODE = "cutover-worker-recover"
R82_MODE = "cutover-worker-807-recover"
EXPECTED_RECOVERY_ENTRIES = {
    "__main__.py",
    "boca_socios/__init__.py",
    "boca_socios/host_boca_cleanup.py",
    "docker/seccomp_profile.json",
    "scripts/__init__.py",
    "scripts/host_cutover_worker_inspect.py",
    "scripts/host_cutover_worker_recovery.py",
}
R80_RECEIPT = b"BOCA_RECOVERY_FIXTURE incident=795 host=UNTOUCHED\n"
R82_RECEIPT = b"BOCA_RECOVERY_FIXTURE incident=807 host=UNTOUCHED\n"
FAKE_RECOVERY = (
    "def main(argv):\n"
    "    if argv == ['host']:\n"
    "        print('BOCA_RECOVERY_FIXTURE incident=795 host=UNTOUCHED')\n"
    "        return 0\n"
    "    if argv == ['host-807']:\n"
    "        print('BOCA_RECOVERY_FIXTURE incident=807 host=UNTOUCHED')\n"
    "        return 0\n"
    "    return 3\n"
).encode("ascii")
# Snapshot of the unchanged complete Cutover ZIP from R81 main 8146ab94.
# Its composition must not change merely to add a recovery-only entrypoint.
R81_FULL_CUTOVER_SHA = "a7c43c6f8ea944cd8ec8e7180efa540203c42d5cbde90258f6ae8caad0e387fd"
# R83 deliberately splits the worker preflight into its own immutable bundle.
# Preserve the R81 checksum as historical evidence and pin the new composition.
# ADR0206 V3 deliberately updates CLI and entrypoint, retaining identical ZIP
# composition and recovery/preflight isolation; this is the reviewed new pin.
R83_FULL_CUTOVER_SHA = "8b3082dcf6de0f7bfeb8fac784a6d3ea56a655085c33224547f558200abc9476"
# R101: the V3 read-only observer is a reviewed member of the full host ZIP.
# Preserve the prior R83 checksum above as immutable historical evidence.
R101_FULL_CUTOVER_SHA = "4509410ee64a6108649402a8ef2a0038b6847fd9965917452c49497eab36557e"
V3_STAGE_RECOVERY_FULL_CUTOVER_SHA = (
    "8fd17dc5e6fcebabc4fe051c7ef0ed6fb662c734b694f9619b3fe2ebcca4bf73"
)
# R103: the reviewed read-only postapply inventory helper enters the host ZIP.
# Historical V3 Stage recovery checksum above remains unchanged.
R103_CLEANUP_INVENTORY_FULL_CUTOVER_SHA = (
    "f63434d671ff55d3d71ffb0d73dc97cecbdc0b1f13ad58066461e52fe57d40ef"
)
# R104: one combined candidate also carries the typed PREPARE_WORKER failure
# receipt and its strict V1/V2 READ_ONLY consumer. Preserve the R103 pin.
R104_COMBINED_DIAGNOSTIC_FULL_CUTOVER_SHA = (
    "6c3d11bcffe2961c2ad185481277e2f86b673072f2210daa16e4f3fa5c9abe87"
)
# R108: one exact historical-image quarantine and v2 postflight proof; keep
# every prior pin as immutable historical evidence.
R108_HISTORICAL_QUARANTINE_FULL_CUTOVER_SHA = (
    "8fca328150a3046960494b3d5e253294ffab80f6463ce9f6ccb67ae85f47b0d4"
)
# R110: retain the historical R108 proof and pin the diagnostic-only extension
# of worker health categories; no new host entrypoint or recovery mode.
R110_HEALTH_DIAGNOSTIC_FULL_CUTOVER_SHA = (
    "4a2e770876434db1e3b6b1f74364da1296f129945220e49e0f9e76dd5525a08e"
)
# R114 adds only two typed Docker state fields, before compensating exited
# worker, and adjusts the verified uncompressed bound; immutable ZIP bytes
# therefore change. Preserve R110's historical digest above.
R114_EXIT_EVIDENCE_FULL_CUTOVER_SHA = (
    "3716ed03c841ec8a8adb7ab7809d32d23853a47c2733403921215edf10c25811"
)
# R116: same strict allowlist and capacity caps; the reviewed IPC controller
# now includes and verifies the encrypted Telegram staging selector.
# R114 remains an immutable historical digest for incident provenance.
R116_TELEGRAM_STAGE_PARITY_FULL_CUTOVER_SHA = (
    "2e6eb49323be4edcbe427aee34c7f2801c8698f8ccf8ba46945907550749c14d"
)
# R118: the existing READ_ONLY observer now verifies terminal v3 exit fields;
# R116 remains the immutable pin of the earlier physical Cutover code.
R118_READONLY_LATEST_CUTOVER_SHA = (
    "a34535af33d9e7073d16a97c50ce1e0a529db39dae35302b79c0cb0ecb152e77"
)
# R119: the strict positive recovery gate and typed evidence projection alter
# only the reviewed READ_ONLY observer. Preserve R118's prior physical pin.
R119_RECOVERED_READONLY_FULL_CUTOVER_SHA = (
    "aa43ffb3ec71104707b6df7eb14a5d66fb10df25aeb3297305854fbf27db75b7"
)
# R127: V4 finite worker metadata, same entry allowlist and compressed caps.
# Preserve R119 as a historical provenance pin, never replace its literal.
R127_WORKER_EXIT_CAPTURE_FULL_CUTOVER_SHA = (
    "df11ea1c522252a89fade7b1261b05c110176bfd6a067967f74c83c3418b0808"
)
# R132 binds the external collector, private readback and controller peer check.
R132_PREARMED_CAPTURE_FULL_CUTOVER_SHA = (
    "a903cfefe6e18dd70c28c4c1190730a219169489464bbf10a64d79d81f642070"
)
# R135 packages the idle installer, request executor and read-only physical observer.
R135_IDLE_INSTALL_FULL_CUTOVER_SHA = (
    "2a91c7efd38e2d67b32c56838543c043b1d1f576d7da2e6b6784af7f794291eb"
)
# R136 reads the fixed historical idle installation and controller inventory.
R136_INCIDENT_OBSERVER_FULL_CUTOVER_SHA = (
    "0bc394e88b9837cd92ef5fdb5db7e277f93522e1c19ca962a9c458b764ee421f"
)
# R137 preserves the precise panel check and verified compensation across SSH loss.
R137_CANDIDATE_ACCEPTANCE_FULL_CUTOVER_SHA = (
    "104590e66572b395d38061059fed9fe2550954a459a27512dc1faef6110ec53c"
)
# R138 verifies each obsolete image and completes the stage after restoring the panel.
R138_RESTORED_PANEL_FINISH_FULL_CUTOVER_SHA = (
    "f8513a879e2530f6f51dea256f4b3e1502eba11048360d193d5f26a02bf3583b"
)
# R139 uses the portable stop argument for exact Docker acknowledgements.
R139_PORTABLE_PANEL_STOP_FULL_CUTOVER_SHA = (
    "bef701b7719e370790f9d6e6afe01a7e7e77dc490485e998ba77314c78c11aeb"
)
# R171 adds one dedicated rootless browser egress bridge and pins the updated
# host-side validator bytes; it does not authorize a physical cutover.
R171_BROWSER_EGRESS_FULL_CUTOVER_SHA = (
    "e6b95d4ff20d97e444f611d616f38653f69cb404f2574dbd38df36253a5fd32e"
)
# R173 pins the integrated source including the Boca-only URL pre-START gate,
# protected-volume cleanup and release wiring. Twice independently rebuilt
# byte-identically after that host change; older SHA remains only in history.
R173_SITE_CONFIG_FULL_CUTOVER_SHA = (
    "c4958187deae82c0732c59861ccc6ce8258274b44d5c96a2e022d46d577beaa7"
)
# R178 adds a narrow read-only DNS/TLS/HTTPS attestor to the existing
# run-pinned Boca host bundle. The former R173 digest is preserved above.
R178_WORKER_EGRESS_READONLY_FULL_CUTOVER_SHA = (
    "80c458fbe314eadbd47e474dbdefa9d2f055f2e70137ef28110cc9ad241568fb"
)


def _fixture_root(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    for name in (
        "src/boca_socios/__init__.py",
        "src/boca_socios/host_boca_cleanup.py",
        "docker/seccomp_profile.json",
        "scripts/__init__.py",
        "scripts/host_cutover_worker_inspect.py",
    ):
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    source = repository / "scripts/host_cutover_worker_recovery.py"
    source.write_bytes(FAKE_RECOVERY)
    return repository


def _build(tmp_path: Path) -> tuple[bytes, str]:
    target = tmp_path / "worker-recovery.pyz"
    command = subprocess.run(  # noqa: S603 - local deterministic builder only
        (
            sys.executable,
            str(ROOT / "scripts/build_protected_boca_bundle.py"),
            "--worker-recovery",
            str(_fixture_root(tmp_path)),
            str(target),
        ),
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert command.returncode == 0, (command.stdout, command.stderr)
    digest = command.stdout.decode("ascii").strip().removeprefix("BOCA_PROTECTED_BUNDLE sha256=")
    assert len(digest) == 64
    return target.read_bytes(), digest


def _boot(raw: bytes, digest: str, mode: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - local stdlib-only memfd fixture
        (
            sys.executable,
            "-S",
            str(ROOT / "scripts/boca_protected_memfd_bootstrap.py"),
            digest,
            mode,
            *args,
        ),
        input=raw,
        capture_output=True,
        check=False,
        timeout=15,
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [(R80_MODE, R80_RECEIPT), (R82_MODE, R82_RECEIPT)],
)
def test_only_fixed_recovery_modes_reach_their_distinct_host_handlers(
    tmp_path: Path, mode: str, expected: bytes
) -> None:
    """Catch R82 refusal or accidental dispatch through the consumed R80 path."""
    raw, digest = _build(tmp_path)
    result = _boot(raw, digest, mode)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == expected
    assert result.stderr == b""


@pytest.mark.parametrize("mode", [R80_MODE, R82_MODE])
@pytest.mark.parametrize(
    "extra",
    [
        ("06ac6e6b596c8286957cdfa21d6f4e3f6b7f19a7da4cff8b8c9ba47a1307a70d",),
        ("42341290485", "arbitrary-browser-image"),
        ("--force",),
    ],
)
def test_no_fixed_recovery_mode_accepts_host_coordinates(
    tmp_path: Path, mode: str, extra: tuple[str, ...]
) -> None:
    """A caller cannot add a Docker CID, image, attempt, or mutation flag."""
    raw, digest = _build(tmp_path)
    result = _boot(raw, digest, mode, *extra)
    assert result.returncode != 0
    assert b"BOCA_RECOVERY_FIXTURE" not in result.stdout


@pytest.mark.parametrize(
    "mode", ["cutover-worker-808-recover", "cutover-worker-preflight", "shell"]
)
def test_unknown_mode_cannot_enter_minimal_recovery_payload(tmp_path: Path, mode: str) -> None:
    raw, digest = _build(tmp_path)
    result = _boot(raw, digest, mode)
    assert result.returncode != 0
    assert b"BOCA_RECOVERY_FIXTURE" not in result.stdout


def test_r82_stays_within_seven_entry_recovery_only_allowlist(tmp_path: Path) -> None:
    """A new R82 mode must not pull Compose, BLACKBOX, or other host scripts."""
    raw, digest = _build(tmp_path)
    assert hashlib.sha256(raw).hexdigest() == digest
    assert len(raw) <= 128_000
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        assert len(names) == len(EXPECTED_RECOVERY_ENTRIES)
        assert set(names) == EXPECTED_RECOVERY_ENTRIES
        assert archive.read("scripts/host_cutover_worker_recovery.py") == FAKE_RECOVERY
        assert sum(entry.file_size for entry in archive.infolist()) <= 256_000
        assert not any(
            "browser/synthetic.py" in name or "browser/ipc_worker.py" in name for name in names
        )
    bootstrap.verify(raw, digest, recovery=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, recovery=False)


@pytest.mark.parametrize("mode", [R80_MODE, R82_MODE])
def test_both_recovery_modes_reject_modified_bytes_and_injected_entries(
    tmp_path: Path, mode: str
) -> None:
    raw, digest = _build(tmp_path)
    corrupted = bytearray(raw)
    corrupted[50] ^= 1
    changed = _boot(bytes(corrupted), digest, mode)
    assert changed.returncode != 0
    assert b"BOCA_RECOVERY_FIXTURE" not in changed.stdout

    # A self-consistent SHA must not make an unreviewed BLACKBOX entry safe.
    # Only synthetic bytes are injected; no BLACKBOX source is read here.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    altered = io.BytesIO()
    with zipfile.ZipFile(altered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in {
            **entries,
            "boca_socios/browser/ipc_worker.py": b"# forbidden fixture; never execute\n",
        }.items():
            member = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = 0o100644 << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, data)
    injected = altered.getvalue()
    injected_sha = hashlib.sha256(injected).hexdigest()
    result = _boot(injected, injected_sha, mode)
    assert result.returncode != 0
    assert b"BOCA_RECOVERY_FIXTURE" not in result.stdout


def test_current_cutover_zip_is_pinned_and_excludes_preflight(tmp_path: Path) -> None:
    """R101 observer does not change the intentionally isolated R83 recovery modes."""
    target = tmp_path / "full-cutover.pyz"
    digest = builder.build(ROOT, target)
    raw = target.read_bytes()
    assert digest == hashlib.sha256(raw).hexdigest() == R178_WORKER_EGRESS_READONLY_FULL_CUTOVER_SHA
    assert digest != R173_SITE_CONFIG_FULL_CUTOVER_SHA
    assert digest != R171_BROWSER_EGRESS_FULL_CUTOVER_SHA
    assert digest != R139_PORTABLE_PANEL_STOP_FULL_CUTOVER_SHA
    assert digest != R138_RESTORED_PANEL_FINISH_FULL_CUTOVER_SHA
    assert digest != R137_CANDIDATE_ACCEPTANCE_FULL_CUTOVER_SHA
    assert digest != R136_INCIDENT_OBSERVER_FULL_CUTOVER_SHA
    assert digest != R135_IDLE_INSTALL_FULL_CUTOVER_SHA
    assert digest != R132_PREARMED_CAPTURE_FULL_CUTOVER_SHA
    assert digest != R127_WORKER_EXIT_CAPTURE_FULL_CUTOVER_SHA
    assert digest != R119_RECOVERED_READONLY_FULL_CUTOVER_SHA
    assert digest != R118_READONLY_LATEST_CUTOVER_SHA
    assert digest != R116_TELEGRAM_STAGE_PARITY_FULL_CUTOVER_SHA
    assert digest != R114_EXIT_EVIDENCE_FULL_CUTOVER_SHA
    assert digest != R110_HEALTH_DIAGNOSTIC_FULL_CUTOVER_SHA
    assert digest != R108_HISTORICAL_QUARANTINE_FULL_CUTOVER_SHA
    assert digest != R104_COMBINED_DIAGNOSTIC_FULL_CUTOVER_SHA
    assert digest != R103_CLEANUP_INVENTORY_FULL_CUTOVER_SHA
    assert digest != V3_STAGE_RECOVERY_FULL_CUTOVER_SHA
    assert digest != R101_FULL_CUTOVER_SHA
    assert digest != R83_FULL_CUTOVER_SHA  # historical pin retained, explicitly superseded
    assert digest != R81_FULL_CUTOVER_SHA
    assert len(raw) <= 512_000
    bootstrap.verify(raw, digest)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, recovery=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert "scripts/host_cutover_worker_recovery.py" not in archive.namelist()
        assert "scripts/host_cutover_worker_inspect.py" not in archive.namelist()
        assert "scripts/host_cutover_worker_preflight.py" not in archive.namelist()
        assert b"cutover-worker-preflight" not in archive.read("__main__.py")
