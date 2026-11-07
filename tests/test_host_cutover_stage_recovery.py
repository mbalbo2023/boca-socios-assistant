"""Offline exact-incident stage recovery; no host/Docker/SSH/BLACKBOX calls."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_cutover_stage as stage

# The reviewed host package is streamed with both ``scripts`` and ``src``;
# editable wheels intentionally do not install the operational scripts tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import host_cutover_stage_recovery as recovery

INCIDENT = "42236673419"
PREPARE = "42217108000"
LEGACY = "a" * 64
LEGACY_SHA = "b" * 40
TARGET_SHA = "c" * 40
LEGACY_COMPOSE = b"services:\n  controller:\n    image: legacy\n"
TARGET_COMPOSE = b"services:\n  controller:\n    image: target\n"
OVERLAY = b"services:\n  browser-worker:\n    network_mode: none\n"
SECCOMP = b'{"defaultAction":"SCMP_ACT_ERRNO"}'
TARGET_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
BROWSER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def intent() -> dict:
    return {
        "version": "boca-cutover-a-intent-v1",
        "attempt_id": INCIDENT,
        "legacy_id": LEGACY,
        "legacy_source_sha": LEGACY_SHA,
        "legacy_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64,
        "legacy_compose_sha": sha(LEGACY_COMPOSE),
        "target_source_sha": TARGET_SHA,
        "target_image_ref": TARGET_IMAGE,
        "browser_image_ref": BROWSER_IMAGE,
        "target_compose_sha": sha(TARGET_COMPOSE),
        "overlay_sha": sha(OVERLAY),
        "seccomp_sha": sha(SECCOMP),
        "owner_subject_sha256": "1" * 64,
        "origin": "http://localhost:8443",
    }


def result(input_intent: dict) -> dict:
    return {
        "version": "boca-cutover-a-terminal-v1",
        "attempt_id": INCIDENT,
        "legacy_id": LEGACY,
        "legacy_source_sha": LEGACY_SHA,
        "target_source_sha": TARGET_SHA,
        "intent_sha256": sha(recovery.observer._canonical(input_intent)),
        "state": "NO_GO",
        "cleanup": "INDETERMINATE",
        "original_restored": True,
        "irreversible_commit_started": False,
        "candidate_id": None,
        "worker_id": None,
    }


def snapshot(root: Path) -> dict:
    staged = root / f"cutover-a-{INCIDENT}"
    stage_present = staged.exists()
    inventory = {
        "id": LEGACY,
        "name": f"/boca-socios-controller-legacy-{INCIDENT}",
        "running": True,
        "health": "healthy",
        "image_id": "sha256:" + "f" * 64,
        "revision": LEGACY_SHA,
        "service": "controller",
        "attempt": None,
        "port_binding": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
    }
    names = {p.name for p in root.iterdir()}
    return {
        "version": "boca-postapply-reconcile-v1",
        "incident_run_id": INCIDENT,
        "prepare_run_id": PREPARE,
        "intent": "PRESENT",
        "result": "PRESENT",
        "terminal_state": "NO_GO",
        "cleanup": "INDETERMINATE",
        "commit_started": False,
        "original_restored": True,
        "legacy_id": LEGACY,
        "original": inventory,
        "boca_inventory": [inventory],
        "boca_containers": 1,
        "port_8443": "BOCA_CONTROLLER_DOCKER_BOUND",
        "candidate_controllers": [],
        "browser_workers": [],
        "stage": "PRESENT" if stage_present else "ABSENT",
        "promotion_intent": "PRESENT"
        if staged.exists() and (staged / stage.COMMIT_INTENT).exists()
        else "ABSENT",
        "promotion_result": "ABSENT",
        "stage_preflight": {
            "reason": "STAGE_ROOT_ENTRIES"
            if names != {"compose.beta.yaml"}
            else "STAGE_PREFLIGHT_MATCH",
            "root_entries_count": len(names),
            "root_entries_expected": names == {"compose.beta.yaml"},
            "compose_digest_match": names == {"compose.beta.yaml"},
            "compose_legacy_mode_accepted": True,
            "plan_hashes_unique": True,
        },
        "go_for_retry": False,
        "runtime_attested": False,
        "foreign_resources_touched": False,
    }


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Authenticated stage and immutable records, but every Docker read is a fixture."""
    monkeypatch.setattr(stage, "ROOT", tmp_path)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    tmp_path.chmod(0o700)
    compose = tmp_path / "compose.beta.yaml"
    compose.write_bytes(LEGACY_COMPOSE)
    compose.chmod(0o644)  # physically observed legacy SCP mode
    stage.initialize(
        INCIDENT,
        LEGACY,
        LEGACY_SHA,
        sha(LEGACY_COMPOSE),
        TARGET_SHA,
        TARGET_IMAGE,
        BROWSER_IMAGE,
        sha(TARGET_COMPOSE),
        sha(OVERLAY),
        sha(SECCOMP),
    )
    for slot, payload in (("base", TARGET_COMPOSE), ("overlay", OVERLAY), ("seccomp", SECCOMP)):
        stage.upload(slot, sha(payload), INCIDENT, sha(LEGACY_COMPOSE), io.BytesIO(payload))
    records = {
        f"boca-cutover-a-intent-{INCIDENT}.json": recovery.observer._canonical(intent()),
        f"boca-cutover-a-result-{INCIDENT}.json": recovery.observer._canonical(result(intent())),
    }
    monkeypatch.setattr(recovery.observer, "_private_home", lambda: Path("/home/test-boca"))
    monkeypatch.setattr(
        recovery.observer, "_read_private", lambda name, *, directory: records.get(name)
    )

    @contextmanager
    def held(job: str):
        assert job == INCIDENT
        yield SimpleNamespace(attempt_id=job)

    monkeypatch.setattr(recovery.cleanup, "protected_boca_job_lease", held)
    monkeypatch.setattr(
        recovery.cleanup, "verify_protected_boca_job_lease", lambda lease, job: None
    )
    monkeypatch.setattr(recovery.observer, "_host", lambda run, prep: snapshot(tmp_path))
    return tmp_path, records


def test_positive_single_exact_stage_clear_preserves_live_inode_and_receipts(world):
    root, records = world
    before = (root / "compose.beta.yaml").stat()
    records_before = dict(records)
    receipt = recovery.recover(INCIDENT, PREPARE)
    assert receipt["state"] == "STAGE_CLEARED"
    assert receipt["go_for_retry"] is False
    assert receipt["docker_writes"] == 0
    assert set(p.name for p in root.iterdir()) == {"compose.beta.yaml"}
    after = (root / "compose.beta.yaml").stat()
    assert (before.st_dev, before.st_ino, before.st_mode) == (
        after.st_dev,
        after.st_ino,
        after.st_mode,
    )
    assert (root / "compose.beta.yaml").read_bytes() == LEGACY_COMPOSE
    assert records == records_before
    packed = recovery.observer._canonical(receipt) + b"\n"
    assert recovery.verify_runner(packed, INCIDENT, PREPARE) == receipt
    with pytest.raises((recovery.StageRecoveryError, stage.StageError)):
        recovery.recover(INCIDENT, PREPARE)  # never a blind repeat


def test_typed_v2_result_is_accepted_by_same_stage_recovery_record_gate(world):
    _, records = world
    name = f"boca-cutover-a-result-{INCIDENT}.json"
    terminal = json.loads(records[name])
    terminal.update(
        version="boca-cutover-a-terminal-v2",
        worker_primary_phase="CREATE",
        worker_compensation="INDETERMINATE",
    )
    records[name] = recovery.observer._canonical(terminal)

    verified_intent, verified_result, intent_hash, result_hash = recovery._verified_records(
        INCIDENT
    )
    assert verified_intent["attempt_id"] == INCIDENT
    assert verified_result["version"] == "boca-cutover-a-terminal-v2"
    assert verified_result["worker_primary_phase"] == "CREATE"
    assert verified_result["worker_compensation"] == "INDETERMINATE"
    assert intent_hash == sha(records[f"boca-cutover-a-intent-{INCIDENT}.json"])
    assert result_hash == sha(records[name])


def test_v3_uses_git_authenticated_source_and_no_prepare(world, monkeypatch):
    root, _ = world

    def host(run, prepared, *, source_sha):
        assert run == INCIDENT and prepared is None and source_sha == TARGET_SHA
        result = snapshot(root)
        result.update(
            version="boca-postapply-reconcile-v2",
            prepare_run_id=None,
            incident_source_sha=source_sha,
        )
        return result

    monkeypatch.setattr(recovery.observer, "_host", host)
    receipt = recovery.recover_v3(INCIDENT, TARGET_SHA)
    assert receipt["incident_source_sha"] == TARGET_SHA
    assert receipt["prepare_run_id"] is None
    assert receipt["go_for_retry"] is False
    assert (
        recovery.verify_runner_v3(
            recovery.observer._canonical(receipt) + b"\n", INCIDENT, TARGET_SHA
        )
        == receipt
    )


def test_v3_rejects_source_mismatch_before_stage_effect(world):
    root, _ = world
    with pytest.raises(recovery.StageRecoveryError):
        recovery.recover_v3(INCIDENT, "9" * 40)
    assert (root / f"cutover-a-{INCIDENT}").exists()


@pytest.mark.parametrize(
    "override",
    [
        {"commit_started": True},
        {"browser_workers": [{"id": "d" * 64}]},
        {"candidate_controllers": [{"id": "e" * 64}]},
        {"port_8443": "UNVERIFIED"},
        {"incident_source_sha": "9" * 40},
        {"promotion_intent": "PRESENT"},
    ],
)
def test_v3_unsafe_snapshot_never_deletes_stage(world, monkeypatch, override):
    root, _ = world

    def host(run, prepared, *, source_sha):
        observed = snapshot(root)
        observed.update(
            version="boca-postapply-reconcile-v2",
            prepare_run_id=None,
            incident_source_sha=source_sha,
        )
        observed.update(override)
        return observed

    monkeypatch.setattr(recovery.observer, "_host", host)
    with pytest.raises(recovery.StageRecoveryError):
        recovery.recover_v3(INCIDENT, TARGET_SHA)
    assert (root / f"cutover-a-{INCIDENT}").exists()


@pytest.mark.parametrize(
    "override",
    [
        {"original": None},
        {"boca_containers": 2},
        {"port_8443": "UNVERIFIED"},
        {"browser_workers": [{"id": "c" * 64}]},
        {"candidate_controllers": [{"id": "d" * 64}]},
        {"commit_started": True},
        {"original_restored": False},
        {"promotion_intent": "PRESENT"},
        {"go_for_retry": True},
        {"terminal_state": "RECOVERED"},
    ],
)
def test_unsafe_observer_never_deletes_stage(world, monkeypatch, override):
    root, _ = world
    observed = snapshot(root)
    observed.update(override)
    monkeypatch.setattr(recovery.observer, "_host", lambda run, prep: observed)
    with pytest.raises(recovery.StageRecoveryError):
        recovery.recover(INCIDENT, PREPARE)
    assert (root / f"cutover-a-{INCIDENT}").exists()


@pytest.mark.parametrize(
    "key,value",
    [
        ("legacy_id", "f" * 64),
        ("target_image_ref", TARGET_IMAGE.replace("d", "a")),
        ("legacy_compose_sha", "9" * 64),
        ("overlay_sha", "8" * 64),
    ],
)
def test_marker_must_match_durable_intent_exactly(world, key, value):
    root, records = world
    changed = intent()
    changed[key] = value
    records[f"boca-cutover-a-intent-{INCIDENT}.json"] = recovery.observer._canonical(changed)
    receipt = result(changed)
    if key == "legacy_id":
        receipt["legacy_id"] = value
    records[f"boca-cutover-a-result-{INCIDENT}.json"] = recovery.observer._canonical(receipt)
    with pytest.raises((recovery.StageRecoveryError, stage.StageError)):
        recovery.recover(INCIDENT, PREPARE)
    assert (root / f"cutover-a-{INCIDENT}").exists()


@pytest.mark.parametrize(
    "residue", [".cutover-base-42236673419.part", "unknown.txt", stage.COMMIT_INTENT]
)
def test_unknown_part_or_promotion_marker_quarantined(world, residue):
    root, _ = world
    (root / f"cutover-a-{INCIDENT}" / residue).write_text("quarantine")
    with pytest.raises((recovery.StageRecoveryError, stage.StageError)):
        recovery.recover(INCIDENT, PREPARE)
    assert (root / f"cutover-a-{INCIDENT}" / residue).exists()


def test_root_count_two_is_not_identity_of_exact_stage(world):
    root, _ = world
    (root / f"cutover-a-{INCIDENT}").rename(root / "other-directory")
    with pytest.raises((recovery.StageRecoveryError, stage.StageError)):
        recovery.recover(INCIDENT, PREPARE)
    assert (root / "other-directory").exists()


def test_symlinked_stage_rejected(world):
    root, _ = world
    original = root / f"cutover-a-{INCIDENT}"
    original.rename(root / "retained-stage")
    original.symlink_to("retained-stage")
    with pytest.raises((recovery.StageRecoveryError, stage.StageError)):
        recovery.recover(INCIDENT, PREPARE)
    assert original.is_symlink()


@pytest.mark.parametrize(
    "change",
    [
        {"state": "ACCEPTED"},
        {"cleanup": "ACCEPT"},
        {"original_restored": False},
        {"irreversible_commit_started": True},
        {"intent_sha256": "f" * 64},
    ],
)
def test_durable_terminal_must_be_precommit_recovered(world, change):
    root, records = world
    record = json.loads(records[f"boca-cutover-a-result-{INCIDENT}.json"])
    record.update(change)
    records[f"boca-cutover-a-result-{INCIDENT}.json"] = recovery.observer._canonical(record)
    with pytest.raises(recovery.StageRecoveryError):
        recovery.recover(INCIDENT, PREPARE)
    assert (root / f"cutover-a-{INCIDENT}").exists()


def test_observer_drift_between_pre_effect_reads_rejected(world, monkeypatch):
    root, _ = world
    calls = 0

    def drift(run, prep):
        nonlocal calls
        calls += 1
        value = snapshot(root)
        if calls == 2:
            value["prepared_go_marker"] = "ABSENT"
        return value

    monkeypatch.setattr(recovery.observer, "_host", drift)
    with pytest.raises(recovery.StageRecoveryError, match="changed"):
        recovery.recover(INCIDENT, PREPARE)
    assert (root / f"cutover-a-{INCIDENT}").exists()


def test_discard_failure_cannot_report_success(world, monkeypatch):
    root, _ = world

    def fail(incident, legacy_sha):
        raise stage.StageError("injected FS uncertainty")

    monkeypatch.setattr(stage, "discard_recovered", fail)
    with pytest.raises(stage.StageError):
        recovery.recover(INCIDENT, PREPARE)
    assert (root / f"cutover-a-{INCIDENT}").exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw + b" ",
        lambda raw: raw.replace(b'"state":"STAGE_CLEARED"', b'"state":"ACCEPTED"'),
        lambda raw: raw.replace(b'"docker_writes":0', b'"docker_writes":1'),
        lambda raw: raw.replace(b'"go_for_retry":false', b'"go_for_retry":true'),
        lambda raw: raw.replace(b'"incident_run_id":"42236673419"', b'"incident_run_id":"1"'),
        lambda raw: raw.replace(
            b'"state":"STAGE_CLEARED"', b'"state":"STAGE_CLEARED","state":"STAGE_CLEARED"'
        ),
    ],
)
def test_runner_rejects_forged_or_ambiguous_receipts(world, mutate):
    receipt = recovery.observer._canonical(recovery.recover(INCIDENT, PREPARE)) + b"\n"
    with pytest.raises(recovery.StageRecoveryError):
        recovery.verify_runner(mutate(receipt), INCIDENT, PREPARE)


def test_public_cli_wrong_arguments_fail_closed():
    assert recovery.main(["host", "1", "1"]) == 3
    assert recovery.main(["host", "42236673419"]) == 3
    assert recovery.main(["run", INCIDENT, PREPARE]) == 3
