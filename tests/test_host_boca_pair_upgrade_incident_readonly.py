"""G17 #1241: five inert markers, private terminal, and canonical runner GO."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from boca_socios import host_boca_pair_upgrade_incident_readonly as forensic
from boca_socios import host_cutover_stage as stage

ATTEMPT = "44315372494"
OLD = "75b00d8e1cd903d3d727a2628134a27fd740fc42"
NEW = "7f20bf0acf43b2e17812bfc35efc86a552b5a404"
RELEASE = "44313076076"
RUN = "44398765432"
OLD_CONTROLLER, OLD_WORKER = "1" * 64, "2" * 64
NEW_CONTROLLER, NEW_WORKER = "3" * 64, "4" * 64
PREFIX = ".boca-pair-upgrade-44315372494."


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _markers(state: str = "ACCEPTED") -> dict[str, bytes]:
    cref = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
    wref = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
    plan = {
        "attempt_id": ATTEMPT,
        "observation_run_id": "44310000001",
        "old_attempt_id": "43920000001",
        "old_source_sha": OLD,
        "old_controller_id": OLD_CONTROLLER,
        "old_worker_id": OLD_WORKER,
        "old_controller_image_id": "sha256:" + "c" * 64,
        "old_worker_image_id": "sha256:" + "d" * 64,
        "new_source_sha": NEW,
        "release_run_id": RELEASE,
        "controller_ref": cref,
        "worker_ref": wref,
    }
    release = {
        "source_sha": NEW,
        "release_run_id": RELEASE,
        "controller_ref": cref,
        "worker_ref": wref,
        "controller_manifest_sha256": "5" * 64,
        "paired_manifest_sha256": "6" * 64,
    }
    witness = {
        "observation_run_id": plan["observation_run_id"],
        "old_attempt_id": plan["old_attempt_id"],
        "old_source_sha": OLD,
        "controller_id": OLD_CONTROLLER,
        "worker_id": OLD_WORKER,
        "controller_image_id": plan["old_controller_image_id"],
        "worker_image_id": plan["old_worker_image_id"],
        "control_inode_sha256": "7" * 64,
        "retained": {},
    }
    evidence = _canonical(
        {
            "version": "boca-successor-pair-intent-evidence-v1",
            "plan": plan,
            "release": release,
            "witness": witness,
        }
    )
    intent = _canonical(
        {
            "attempt": ATTEMPT,
            "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
            "old_controller": OLD_CONTROLLER,
            "old_worker": OLD_WORKER,
            "old_source": OLD,
            "new_source": NEW,
            "release": RELEASE,
        }
    )
    pair = {
        "attempt_id": ATTEMPT,
        "source_sha": NEW,
        "services": [
            {"container_id": NEW_CONTROLLER, "role": "controller"},
            {"container_id": NEW_WORKER, "role": "browser-worker"},
        ],
    }
    technical = (
        b"BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2 "
        + _canonical(
            {
                "schema": 2,
                "state": "TECHNICAL_PROOF_ONLY",
                "attempt_id": ATTEMPT,
                "source_sha": NEW,
                "release_run_id": RELEASE,
                "controller_manifest_sha256": release["controller_manifest_sha256"],
                "paired_manifest_sha256": release["paired_manifest_sha256"],
                "pair": pair,
                "binding": {
                    "installation_attempt": ATTEMPT,
                    "source_sha": NEW,
                    "controller_id": NEW_CONTROLLER,
                    "worker_id": NEW_WORKER,
                    "controller_image_ref": cref,
                    "worker_image_ref": wref,
                },
                "rootless_uid": 10001,
                "rootless_gid": 10001,
                "panel": {
                    "origin": "http://localhost:8443",
                    "probe": "HEALTH_HTTP_200",
                    "scope": "LOOPBACK_HEALTH_ONLY",
                },
                "monitor": {
                    "source": "NOT_CONNECTED",
                    "observations": 0,
                    "provider_attested": False,
                    "owner_monitor": "NOT_ATTESTED",
                    "semantics": "NO_MONITOR_SESSION_OBSERVED",
                },
                "passkey_chrome": "NOT_ATTESTED",
                "beta_deploy": "NO_GO",
                "observer_writes": 0,
                "foreign_resources_touched": 0,
                "cleanup": {"status": "ACCEPT", "sha256": "8" * 64, "r108": "RETAINED_ATTESTED"},
                "storage": {},
                "retained": {},
                "site_url": {},
            }
        )
        + b"\n"
    )
    terminal = (
        b"BOCA_PAIR_UPGRADE "
        + _canonical(
            {
                "schema": 1,
                "attempt_id": ATTEMPT,
                "state": state,
                "cleanup": "ACCEPT" if state == "ACCEPTED" else "INDETERMINATE",
                "old_restored": False,
                "commit_started": True,
                "controller_id": NEW_CONTROLLER,
                "worker_id": NEW_WORKER,
                "failed_phase": "NONE" if state == "ACCEPTED" else "RETIRE_OLD",
            }
        )
        + b"\n"
    )
    return {
        "evidence": evidence,
        "intent": intent,
        "commit": hashlib.sha256(intent).hexdigest().encode("ascii"),
        "technical-postflight-v2": technical,
        "terminal": terminal,
    }


@pytest.fixture
def boca_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(stage, "ROOT", tmp_path)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    return tmp_path


def _write(directory: Path, markers: dict[str, bytes]) -> None:
    for suffix, content in markers.items():
        path = directory / f"{PREFIX}{suffix}"
        path.write_bytes(content)
        path.chmod(0o600)


@pytest.mark.parametrize("state", ["ACCEPTED", "NO_GO"])
def test_canonical_durable_terminal_is_verified_only_on_runner(boca_dir: Path, state: str) -> None:
    _write(boca_dir, _markers(state))
    private = forensic.observe_private(RUN)
    summary = forensic.verify_private(private, RUN)
    assert (
        "HISTORICAL_TERMINAL_ACCEPTED" if state == "ACCEPTED" else "HISTORICAL_TERMINAL_NO_GO"
    ) in summary
    assert "observer_writes=0" in summary
    assert "recovery_authorized=false" in summary
    assert "beta_deploy=NO_GO" in summary
    assert NEW_CONTROLLER not in summary and NEW_WORKER not in summary
    assert b"BOCA_PAIR_UPGRADE " in private
    assert b"BOCA_PAIR_UPGRADE " not in summary.encode()


@pytest.mark.parametrize(
    "missing", ["evidence", "intent", "commit", "technical-postflight-v2", "terminal"]
)
def test_missing_marker_is_unknown_not_accepted(boca_dir: Path, missing: str) -> None:
    markers = _markers()
    markers.pop(missing)
    _write(boca_dir, markers)
    result = forensic.verify_private(forensic.observe_private(RUN), RUN)
    assert "HISTORICAL_TERMINAL_ACCEPTED" not in result
    assert "UNKNOWN" in result or "NO_GO" in result
    assert "observer_writes=0" in result


@pytest.mark.parametrize(
    "bad",
    [
        "intent_hash",
        "commit",
        "old_source",
        "new_source",
        "release",
        "technical_binding",
        "terminal_state",
        "duplicate",
        "truncated",
        "technical_scope",
        "technical_cleanup",
        "technical_false_zero",
    ],
)
def test_corrupted_chain_or_terminal_is_never_accepted(boca_dir: Path, bad: str) -> None:
    markers = _markers()
    if bad == "intent_hash":
        markers["intent"] = markers["intent"].replace(
            b'"evidence_sha256":"', b'"evidence_sha256":"0', 1
        )
    elif bad == "commit":
        markers["commit"] = b"0" * 64
    elif bad == "old_source":
        markers["intent"] = markers["intent"].replace(OLD.encode(), ("f" * 40).encode())
    elif bad == "new_source":
        markers["evidence"] = markers["evidence"].replace(NEW.encode(), ("f" * 40).encode())
    elif bad == "release":
        markers["evidence"] = markers["evidence"].replace(RELEASE.encode(), b"44313076075")
    elif bad == "technical_binding":
        markers["technical-postflight-v2"] = markers["technical-postflight-v2"].replace(
            NEW_WORKER.encode(), ("f" * 64).encode(), 1
        )
    elif bad == "terminal_state":
        markers["terminal"] = markers["terminal"].replace(
            b'"state":"ACCEPTED"', b'"state":"PENDING"'
        )
    elif bad == "duplicate":
        markers["intent"] = markers["intent"].replace(
            b'"release":', b'"release":"44313076076","release":'
        )
    elif bad == "truncated":
        markers["terminal"] = markers["terminal"][:-1]
    elif bad == "technical_scope":
        markers["technical-postflight-v2"] = markers["technical-postflight-v2"].replace(
            b'"scope":"LOOPBACK_HEALTH_ONLY"', b'"scope":"OWNER_AUTHENTICATED"'
        )
    elif bad == "technical_cleanup":
        markers["technical-postflight-v2"] = markers["technical-postflight-v2"].replace(
            b'"status":"ACCEPT"', b'"status":"NO_GO"'
        )
    elif bad == "technical_false_zero":
        markers["technical-postflight-v2"] = markers["technical-postflight-v2"].replace(
            b'"observer_writes":0', b'"observer_writes":false'
        )
    _write(boca_dir, markers)
    result = forensic.verify_private(forensic.observe_private(RUN), RUN)
    assert "HISTORICAL_TERMINAL_ACCEPTED" not in result


@pytest.mark.parametrize("bad", ["symlink", "hardlink", "mode", "owner", "race"])
def test_inode_owner_or_double_snapshot_attack_fails_closed(
    boca_dir: Path, bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    markers = _markers()
    _write(boca_dir, markers)
    intent = boca_dir / f"{PREFIX}intent"
    if bad == "symlink":
        intent.unlink()
        intent.symlink_to(boca_dir / f"{PREFIX}evidence")
    elif bad == "hardlink":
        other = boca_dir / "extra-hardlink"
        os.link(intent, other)
    elif bad == "mode":
        intent.chmod(0o644)
    elif bad == "owner":
        monkeypatch.setattr(stage, "UID", -1)
    elif bad == "race":
        read = stage._read_file
        touched = False

        def swapping(
            fd: int,
            name: str,
            expected_sha: str | None,
            *,
            limit: int,
            historical_compose: bool = False,
        ):  # type: ignore[no-untyped-def]
            nonlocal touched
            result = read(
                fd, name, expected_sha, limit=limit, historical_compose=historical_compose
            )
            if name.endswith("intent") and not touched:
                touched = True
                os.unlink(intent)
                _replace = os.open(intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(_replace, result[0])
                os.close(_replace)
            return result

        monkeypatch.setattr(stage, "_read_file", swapping)
    result = forensic.verify_private(forensic.observe_private(RUN), RUN)
    assert "HISTORICAL_TERMINAL_ACCEPTED" not in result


def test_private_frame_tamper_oversize_and_wrong_run_are_rejected(boca_dir: Path) -> None:
    _write(boca_dir, _markers())
    private = forensic.observe_private(RUN)
    for mutated, run in (
        (private + b"extra", RUN),
        (private.replace(b"BOCA_PAIR_UPGRADE ", b"BOCA_PAIR_UPGRADX "), RUN),
        (private[:20], RUN),
        (private + b"x" * 8192, RUN),
        (private, "44399999999"),
    ):
        assert "HISTORICAL_TERMINAL_ACCEPTED" not in forensic.verify_private(mutated, run)


@pytest.mark.parametrize("state", ["RECOVERED", "NO_GO"])
def test_precommit_terminal_cannot_coexist_with_commit_and_technical_markers(
    boca_dir: Path, state: str
) -> None:
    """Canonical CLI validity is weaker than the five-file journal invariant."""
    from boca_socios.host_boca_pair_upgrade_cli import verify_upgrade

    markers = _markers()
    raw = json.loads(markers["terminal"].removeprefix(b"BOCA_PAIR_UPGRADE "))
    raw.update(
        state=state,
        cleanup="ACCEPT" if state == "RECOVERED" else "INDETERMINATE",
        old_restored=state == "RECOVERED",
        commit_started=False,
        controller_id=None,
        worker_id=None,
        failed_phase="ATTEST",
    )
    markers["terminal"] = b"BOCA_PAIR_UPGRADE " + _canonical(raw) + b"\n"
    assert verify_upgrade(markers["terminal"], ATTEMPT) == markers["terminal"]
    _write(boca_dir, markers)
    result = forensic.verify_private(forensic.observe_private(RUN), RUN)
    assert "state=NO_GO reason=TERMINAL_JOURNAL_CONTRADICTION" in result
    assert "HISTORICAL_TERMINAL_RECOVERED" not in result
    assert "HISTORICAL_TERMINAL_NO_GO" not in result


def test_private_reader_never_creates_or_changes_markers(boca_dir: Path) -> None:
    _write(boca_dir, _markers())
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in boca_dir.iterdir()}
    forensic.observe_private(RUN)
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in boca_dir.iterdir()}
    assert before == after


def test_isolated_runner_verifies_actual_framed_terminal_without_site_packages(
    boca_dir: Path,
) -> None:
    """Match the exact Actions -I/-S/-B invocation, including lazy CLI graph."""
    _write(boca_dir, _markers())
    raw = forensic.observe_private(RUN)
    script = (
        "import sys;sys.path.insert(0,sys.argv[1]);"
        "from boca_socios.host_boca_pair_upgrade_incident_readonly import main;"
        "raise SystemExit(main(['verify',sys.argv[2]]))"
    )
    source = str(Path(__file__).resolve().parents[1] / "src")
    # argv is fixed local test code, no shell or untrusted input.
    good = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-S", "-B", "-c", script, source, RUN],
        input=raw,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert good.returncode == 0, good.stderr.decode(errors="replace")
    assert b"HISTORICAL_TERMINAL_ACCEPTED" in good.stdout
    assert b"BOCA_PAIR_UPGRADE " not in good.stdout
    assert NEW_CONTROLLER.encode() not in good.stdout
    bad = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-S", "-B", "-c", script, source, RUN],
        input=raw[:-1] + b"x",
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert bad.returncode == 3
    assert b"FRAME_UNVERIFIED" in bad.stdout


# G18 #1251 is a distinct historical PRECOMMIT failure.  The same bounded
# stage reader and terminal CLI must serve it without changing #1241 semantics.
ATTEMPT_1251 = "44352430452"
OLD_1251 = NEW
NEW_1251 = "dbd3f1c494c341c980625da3660e10cc28fa8446"
RELEASE_1251 = "44348462224"
PREFIX_1251 = ".boca-pair-upgrade-44352430452."


def _precommit_1251_markers() -> dict[str, bytes]:
    original = _markers("NO_GO")
    evidence = json.loads(original["evidence"])
    plan = evidence["plan"]
    release = evidence["release"]
    witness = evidence["witness"]
    plan.update(
        attempt_id=ATTEMPT_1251,
        old_source_sha=OLD_1251,
        new_source_sha=NEW_1251,
        release_run_id=RELEASE_1251,
    )
    release.update(source_sha=NEW_1251, release_run_id=RELEASE_1251)
    witness["old_source_sha"] = OLD_1251
    witness["retained"] = {
        "ipc_creator_attempt": "43920000001",
        "ipc_inode_sha256": "8" * 64,
        "site_creator_attempt": "43920000002",
        "site_inode_sha256": "9" * 64,
        "egress_creator_attempt": "43920000003",
        "egress_id": "a" * 64,
    }
    raw_evidence = _canonical(evidence)
    intent = json.loads(original["intent"])
    intent.update(
        attempt=ATTEMPT_1251,
        evidence_sha256=hashlib.sha256(raw_evidence).hexdigest(),
        old_source=OLD_1251,
        new_source=NEW_1251,
        release=RELEASE_1251,
    )
    terminal = {
        "schema": 1,
        "attempt_id": ATTEMPT_1251,
        "state": "NO_GO",
        "cleanup": "INDETERMINATE",
        "old_restored": False,
        "commit_started": False,
        "controller_id": None,
        "worker_id": None,
        "failed_phase": "ATTEST",
    }
    return {
        "evidence": raw_evidence,
        "intent": _canonical(intent),
        "terminal": b"BOCA_PAIR_UPGRADE " + _canonical(terminal) + b"\n",
        "commit": hashlib.sha256(_canonical(intent)).hexdigest().encode("ascii"),
        "technical-postflight-v2": original["technical-postflight-v2"],
    }


def _write_1251(directory: Path, markers: dict[str, bytes]) -> None:
    for suffix, content in markers.items():
        target = directory / f"{PREFIX_1251}{suffix}"
        target.write_bytes(content)
        target.chmod(0o600)


@pytest.mark.parametrize(
    ("present", "state", "reason"),
    [
        ((), "UNKNOWN", "NO_MARKERS"),
        (("evidence",), "PRECOMMIT_EVIDENCE_ONLY", "EVIDENCE_ONLY"),
        (("evidence", "intent"), "PRECOMMIT_INTENT_ONLY", "INTENT_NO_TERMINAL"),
        (
            ("evidence", "intent", "terminal"),
            "PRECOMMIT_TERMINAL_NO_GO",
            "CANONICAL_ATTEST_NO_GO",
        ),
    ],
)
def test_1251_coherent_precommit_markers_use_same_canonical_verifier(
    boca_dir: Path, present: tuple[str, ...], state: str, reason: str
) -> None:
    markers = _precommit_1251_markers()
    _write_1251(boca_dir, {key: markers[key] for key in present})
    private = forensic.observe_private_1251(RUN)
    result = forensic.verify_private_1251(private, RUN)
    assert f"state={state} reason={reason}" in result
    assert "observer_writes=0" in result and "recovery_authorized=false" in result
    assert "beta_deploy=NO_GO" in result
    assert b"BOCA_PAIR_UPGRADE " not in result.encode()
    assert OLD_CONTROLLER not in result
    assert NEW_CONTROLLER not in result


@pytest.mark.parametrize(
    "selected",
    [
        {"terminal"},
        {"intent"},
        {"evidence", "terminal"},
        {"evidence", "intent", "commit"},
        {"evidence", "intent", "terminal", "commit"},
        {"evidence", "intent", "terminal", "technical-postflight-v2"},
        {"evidence", "intent", "terminal", "commit", "technical-postflight-v2"},
    ],
)
def test_1251_partial_out_of_order_or_postcommit_markers_never_certify_precommit(
    boca_dir: Path, selected: set[str]
) -> None:
    markers = _precommit_1251_markers()
    _write_1251(boca_dir, {key: markers[key] for key in selected})
    result = forensic.verify_private_1251(forensic.observe_private_1251(RUN), RUN)
    assert "state=UNKNOWN" in result or "state=NO_GO" in result
    assert "PRECOMMIT_TERMINAL_NO_GO" not in result


@pytest.mark.parametrize("fault", ["hash", "coordinate", "terminal", "mode", "symlink"])
def test_1251_invalid_chain_and_marker_identity_rejected(boca_dir: Path, fault: str) -> None:
    markers = _precommit_1251_markers()
    selected = {key: markers[key] for key in ("evidence", "intent", "terminal")}
    if fault == "hash":
        selected["intent"] = selected["intent"].replace(
            b'"evidence_sha256":"', b'"evidence_sha256":"0', 1
        )
    elif fault == "coordinate":
        selected["intent"] = selected["intent"].replace(NEW_1251.encode(), b"f" * 40)
    elif fault == "terminal":
        selected["terminal"] = selected["terminal"].replace(
            b'"commit_started":false', b'"commit_started":true'
        )
    _write_1251(boca_dir, selected)
    target = boca_dir / f"{PREFIX_1251}intent"
    if fault == "mode":
        target.chmod(0o644)
    elif fault == "symlink":
        target.unlink()
        target.symlink_to(boca_dir / f"{PREFIX_1251}evidence")
    result = forensic.verify_private_1251(forensic.observe_private_1251(RUN), RUN)
    assert "state=NO_GO" in result or "state=UNKNOWN" in result
    assert "state=PRECOMMIT_TERMINAL_NO_GO" not in result


def test_1251_private_frame_tampering_and_read_only_invariant(boca_dir: Path) -> None:
    markers = _precommit_1251_markers()
    _write_1251(boca_dir, {key: markers[key] for key in ("evidence", "intent", "terminal")})
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in boca_dir.iterdir()}
    private = forensic.observe_private_1251(RUN)
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in boca_dir.iterdir()}
    assert before == after
    assert b"BOCA_PAIR_UPGRADE " in private
    for invalid, run in (
        (private + b"trailing", RUN),
        (private[:-1] + b"0", RUN),
        (private[:20], RUN),
        (private, "44399999999"),
    ):
        assert "state=NO_GO" in forensic.verify_private_1251(invalid, run)


def test_1251_canonical_terminal_error_is_not_misreported_as_transport_frame(
    boca_dir: Path,
) -> None:
    markers = _precommit_1251_markers()
    markers["terminal"] = markers["terminal"].replace(b'"schema":1', b'"schema":1,"schema":1', 1)
    _write_1251(boca_dir, {key: markers[key] for key in ("evidence", "intent", "terminal")})
    result = forensic.verify_private_1251(forensic.observe_private_1251(RUN), RUN)
    assert "state=NO_GO reason=TERMINAL_UNVERIFIED" in result


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "missing_key",
        "extra_key",
        "bool_run",
        "bad_run",
        "bool_hash",
        "bad_hash",
        "wrong_type",
    ],
)
def test_1251_retained_pins_must_match_actual_producer_contract(boca_dir: Path, fault: str) -> None:
    markers = _precommit_1251_markers()
    evidence = json.loads(markers["evidence"])
    retained = evidence["witness"]["retained"]
    assert set(retained) == {
        "ipc_creator_attempt",
        "ipc_inode_sha256",
        "site_creator_attempt",
        "site_inode_sha256",
        "egress_creator_attempt",
        "egress_id",
    }
    if fault == "empty":
        retained.clear()
    elif fault == "missing_key":
        retained.pop("egress_id")
    elif fault == "extra_key":
        retained["unreviewed"] = "x"
    elif fault == "bool_run":
        retained["ipc_creator_attempt"] = True
    elif fault == "bad_run":
        retained["site_creator_attempt"] = "0"
    elif fault == "bool_hash":
        retained["egress_id"] = True
    elif fault == "bad_hash":
        retained["site_inode_sha256"] = "z" * 64
    elif fault == "wrong_type":
        evidence["witness"]["retained"] = []
    markers["evidence"] = _canonical(evidence)
    intent = json.loads(markers["intent"])
    intent["evidence_sha256"] = hashlib.sha256(markers["evidence"]).hexdigest()
    markers["intent"] = _canonical(intent)
    _write_1251(boca_dir, {key: markers[key] for key in ("evidence", "intent")})
    result = forensic.verify_private_1251(forensic.observe_private_1251(RUN), RUN)
    assert "state=NO_GO reason=MARKER_UNVERIFIED" in result
