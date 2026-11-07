"""R91 physical target #827: exact stopped-only recovery, no host calls."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_recovery as recovery  # noqa: E402

from test_r82_exact_worker_807_recovery import PROFILE  # noqa: E402
from test_r87_exact_worker_819_recovery import (  # noqa: E402
    _full_worker,
    _simulate,
    _snapshot,
)

ATTEMPT = "42368541950"
CID = "0ae6b61d97ccae77e8373a597f617df52b28ed63f6e49cae1df57f368e46e8e5"
SOURCE = "8a69d155354362e0712dab1229f7d7e4b3e24dd6"
IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "902276a94bbec0ed0be30432baf97b5bd1298fc15e21eda750ccb785fa76bde0"
)


def _target() -> recovery.RecoveryTarget:
    return recovery.TARGET_827


def test_r91_one_immutable_new_target_preserves_historical_isolation() -> None:
    target = _target()
    assert (target.attempt, target.cid, target.source, target.browser_image) == (
        ATTEMPT,
        CID,
        SOURCE,
        IMAGE,
    )
    assert (target.legacy_id, target.legacy_source, target.legacy_image) == (
        recovery.LEGACY_ID,
        recovery.LEGACY_SOURCE,
        recovery.LEGACY_IMAGE,
    )
    recovery._known_target(target)
    with pytest.raises(recovery.RecoveryError, match="UNREVIEWED_TARGET"):
        recovery._known_target(dataclasses.replace(target, cid="f" * 64))


@pytest.mark.parametrize("status", ["created", "exited"])
def test_r91_two_full_checks_one_nonforce_removal_then_healthy_legacy(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    target = _target()
    state = _simulate(monkeypatch, target)
    state["full"]["State"]["Status"] = status
    receipt = recovery.execute(target)
    assert receipt == {
        "version": "boca-worker-recovery-v1",
        "attempt": ATTEMPT,
        "probe_id": CID,
        "legacy_id": recovery.LEGACY_ID,
        "cleanup": "VERIFIED",
        "phase": "COMPLETE",
        "docker_writes": 1,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY",
    }
    assert state["reads"] == 3 and state["full_reads"] == 2
    assert state["rm"] == [CID]
    recovery.verify_runner(observer.canonical(receipt) + b"\n", target)


@pytest.mark.parametrize(
    ("where", "path", "value"),
    [
        ("before", ["probe_id"], "a" * 64),
        ("before", ["probe_running"], True),
        ("before", ["socket"], "FOREIGN"),
        ("before", ["seccomp"], "PRESENT"),
        ("before", ["probe_full_json_stage"], "OVERSIZED"),
        ("before", ["original_port"], "PUBLIC_8443"),
        ("full", ["Id"], "a" * 64),
        ("full", ["Config", "Image"], "ghcr.io/foreign:latest"),
        ("full", ["Config", "Labels", "org.opencontainers.image.revision"], "a" * 40),
        ("full", ["State", "Running"], True),
        ("full", ["HostConfig", "Privileged"], True),
        ("full", ["HostConfig", "NetworkMode"], "bridge"),
        ("full", ["Mounts"], [{}]),
    ],
)
def test_r91_unsafe_precheck_denies_all_docker_writes(
    monkeypatch: pytest.MonkeyPatch, where: str, path: list[str], value: Any
) -> None:
    state = _simulate(monkeypatch, _target())
    node = state[where]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    receipt = recovery.execute(_target())
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert receipt["docker_writes"] == 0 and state["rm"] == []


def test_r91_snapshot_changed_between_checks_denies_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _simulate(monkeypatch, _target())
    state["second"] = _snapshot(present=True, target=_target())
    state["second"]["probe_running"] = True
    receipt = recovery.execute(_target())
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert state["full_reads"] == 1 and state["rm"] == []


@pytest.mark.parametrize("failure", ["wrong_ack", "lost_ack", "legacy_unhealthy"])
def test_r91_after_remove_uncertain_is_never_retried(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = _simulate(monkeypatch, _target())
    if failure == "wrong_ack":
        state["ack"] = "b" * 64
    elif failure == "lost_ack":
        state["rm_error"] = TimeoutError("lost docker ack")
    else:
        state["after"]["original"] = "NOT_HEALTHY"
    receipt = recovery.execute(_target())
    assert receipt["cleanup"] == "INDETERMINATE"
    assert receipt["docker_writes"] == 1 and state["rm"] == [CID]
    assert receipt["retry_authorized"] is False
    assert receipt["cutover_authorized"] is False


def test_r91_seccomp_binary_pin_cannot_be_reformatted() -> None:
    target = _target()
    recovery._validate_isolation(_full_worker(target), PROFILE, target)
    with pytest.raises(recovery.RecoveryError, match="PROFILE_SHA_MISMATCH"):
        recovery._validate_isolation(_full_worker(target), PROFILE + b"\n", target)


def test_r91_cli_has_no_dynamic_cid_and_verifier_does_not_cross_accept(tmp_path: Path) -> None:
    raw = {
        "version": "boca-worker-recovery-v1",
        "attempt": ATTEMPT,
        "probe_id": CID,
        "legacy_id": recovery.LEGACY_ID,
        "cleanup": "VERIFIED",
        "phase": "COMPLETE",
        "docker_writes": 1,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY",
    }
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(observer.canonical(raw) + b"\n")
    assert recovery.main(["verify-827", str(receipt)]) == 0
    assert recovery.main(["verify-819", str(receipt)]) == 3
    assert recovery.main(["host-827", CID]) == 3
    receipt.write_text(json.dumps(raw) + "\n", encoding="ascii")
    assert recovery.main(["verify-827", str(receipt)]) == 3
