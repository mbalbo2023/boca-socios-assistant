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
