"""R94 one-shot stopped-only #834 recovery; never contacts a Docker host."""

from __future__ import annotations

import copy
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

ATTEMPT = "42375050546"
CID = "b2312004b4fc4e789fb58ce0c40eb2dc14ab132150d0da420657c4d29ef326d3"
SOURCE = "79da7ebe9918d98216ac7eb46ff008d7f6e62429"
IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "ed276066b108fad5b130d0fdffdd3f38a5a3d912253b1d4267bd4b6184992ba8"
)


def test_r94_exact_834_stopped_worker_target_is_immutable() -> None:
    target = getattr(recovery, "TARGET_834", None)
    assert target is not None
    assert (target.attempt, target.cid, target.source, target.browser_image) == (
        ATTEMPT,
        CID,
        SOURCE,
        IMAGE,
    )
    recovery._known_target(target)
    assert (target.legacy_id, target.legacy_source, target.legacy_image) == (
        recovery.LEGACY_ID,
        recovery.LEGACY_SOURCE,
        recovery.LEGACY_IMAGE,
    )
    with pytest.raises(recovery.RecoveryError, match="UNREVIEWED_TARGET"):
        recovery._known_target(dataclasses.replace(target, cid="f" * 64))


@pytest.mark.parametrize("status", ["created", "exited"])
def test_r94_double_fresh_full_checks_then_one_exact_nonforce_rm(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    target = recovery.TARGET_834
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
    assert recovery.verify_runner(observer.canonical(receipt) + b"\n", target) == receipt


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempt", "42375050547"),
        ("probe_id", "f" * 64),
        ("probe_candidate_id", "f" * 64),
        ("probe", "PRESENT_UNVERIFIED"),
        ("probe_running", True),
        ("probe_full_json_stage", "AT_OR_ABOVE_CLEANUP_LIMIT"),
        ("socket", "FOREIGN"),
        ("seccomp", "PRESENT_OWNED"),
        ("original", "UNVERIFIED"),
        ("original_port", "PUBLIC_8443"),
        ("observer_writes", 1),
        ("foreign_resources_touched", True),
        ("cutover_authorized", True),
    ],
)
def test_r94_malicious_or_ambiguous_observer_blocks_all_writes(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    state = _simulate(monkeypatch, recovery.TARGET_834)
    state["before"][field] = value
    receipt = recovery.execute(recovery.TARGET_834)
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert receipt["phase"] == "PRECHECK" and receipt["docker_writes"] == 0
    assert state["rm"] == []


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["Id"], "f" * 64),
        (["Name"], "/foreign"),
        (["Config", "Image"], "ghcr.io/foreign:latest"),
        (["Config", "Labels", "org.opencontainers.image.revision"], "f" * 40),
        (["Config", "Env"], ["BOCA_ENGINE_MODE=on"]),
        (
            ["Config", "Env"],
            [
                "BOCA_ENVIRONMENT=staging",
                "BOCA_RUNTIME_MODE=simulation",
                "BOCA_ENGINE_MODE=off",
                "BOCA_ENGINE_MODE=off",
                "BOCA_OBSERVER_STOP=1",
            ],
        ),
        (["State", "Running"], True),
        (["State", "Status"], "running"),
        (["HostConfig", "NetworkMode"], "bridge"),
        (["HostConfig", "Privileged"], True),
        (["Mounts"], [{"Source": "/host"}]),
    ],
)
def test_r94_full_inspect_identity_or_isolation_mutation_blocks_rm(
    monkeypatch: pytest.MonkeyPatch, path: list[str], value: Any
) -> None:
    state = _simulate(monkeypatch, recovery.TARGET_834)
    node = state["full"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    receipt = recovery.execute(recovery.TARGET_834)
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert receipt["docker_writes"] == 0 and state["rm"] == []


def test_r94_binary_seccomp_profile_sha_never_relaxed() -> None:
    worker = _full_worker(recovery.TARGET_834)
    recovery._validate_isolation(worker, PROFILE, recovery.TARGET_834)
    assert json.loads(PROFILE + b"\n") == json.loads(PROFILE)
    with pytest.raises(recovery.RecoveryError, match="PROFILE_SHA_MISMATCH"):
        recovery._validate_isolation(worker, PROFILE + b"\n", recovery.TARGET_834)


def test_r94_changed_second_snapshot_race_blocks_rm(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _simulate(monkeypatch, recovery.TARGET_834)
    state["second"] = _snapshot(present=True, target=recovery.TARGET_834)
    state["second"]["probe_running"] = True
    receipt = recovery.execute(recovery.TARGET_834)
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert state["full_reads"] == 1 and state["rm"] == []


def test_r94_second_full_inspect_race_blocks_rm(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _simulate(monkeypatch, recovery.TARGET_834)

    def inspect(_cid: str, *, target: recovery.RecoveryTarget) -> dict[str, Any]:
        assert _cid == CID and target is recovery.TARGET_834
        state["full_reads"] += 1
        record = copy.deepcopy(state["full"])
        if state["full_reads"] == 2:
            record["State"]["Running"] = True
        return record

    monkeypatch.setattr(recovery, "_inspect_full_exact", inspect)
    receipt = recovery.execute(recovery.TARGET_834)
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert state["full_reads"] == 2 and state["rm"] == []


def test_r94_lease_failure_never_reaches_docker_write(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _simulate(monkeypatch, recovery.TARGET_834)

    def busy(_attempt: str) -> None:
        raise RuntimeError("private protected lease unavailable")

    monkeypatch.setattr(recovery.cleanup, "protected_boca_job_lease", busy)
    receipt = recovery.execute(recovery.TARGET_834)
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert receipt["docker_writes"] == 0 and state["rm"] == []


@pytest.mark.parametrize("failure", ["wrong_ack", "lost_ack", "timeout", "post_cid", "legacy"])
def test_r94_any_ambiguous_rm_or_postflight_is_indeterminate_without_retry(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = _simulate(monkeypatch, recovery.TARGET_834)
    if failure == "wrong_ack":
        state["ack"] = "f" * 64
    elif failure == "lost_ack":
        state["rm_error"] = OSError("private Docker error must not leak")
    elif failure == "timeout":
        state["rm_error"] = TimeoutError("private timeout must not leak")
    elif failure == "post_cid":
        monkeypatch.setattr(recovery, "_cid_present", lambda *_a, **_k: True)
    else:
        state["after"]["original"] = "UNVERIFIED"
    receipt = recovery.execute(recovery.TARGET_834)
    assert receipt["cleanup"] == "INDETERMINATE"
    assert receipt["phase"] in {"REMOVE", "POSTCHECK"}
    assert receipt["docker_writes"] == 1 and state["rm"] == [CID]
    assert receipt["retry_authorized"] is False
    assert receipt["cutover_authorized"] is False
    assert "private" not in observer.canonical(receipt).decode("ascii")


def test_r94_legacy_unhealthy_after_remove_cannot_claim_original_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _simulate(monkeypatch, recovery.TARGET_834)
    state["after"]["original_port"] = "PUBLIC_8443"
    receipt = recovery.execute(recovery.TARGET_834)
    assert receipt["original"] == "UNVERIFIED"
    assert receipt["cleanup"] == "INDETERMINATE" and state["rm"] == [CID]


def test_r94_actual_docker_remove_adapter_uses_only_exact_nonforce_full_cid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], int]] = []

    def fake_reader(command: tuple[str, ...], *, stdout_limit: int = 0) -> str:
        calls.append((command, stdout_limit))
        return CID

    monkeypatch.setattr(observer, "_run_bounded", fake_reader)
    assert recovery._remove_exact(CID, recovery.TARGET_834) == CID
    assert calls == [(("docker", "container", "rm", CID), 128)]
    with pytest.raises(recovery.RecoveryError, match="EXACT_CID_REQUIRED"):
        recovery._remove_exact("f" * 64, recovery.TARGET_834)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("stdout", "present"),
    [("", False), (CID + "\n", True), ("f" * 64 + "\n", None), (CID + "\n" + CID, None)],
)
def test_r94_actual_postcheck_reader_never_accepts_ambiguous_id_set(
    monkeypatch: pytest.MonkeyPatch, stdout: str, present: bool | None
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_reader(command: tuple[str, ...], *, stdout_limit: int = 0) -> str:
        calls.append(command)
        return stdout

    monkeypatch.setattr(observer, "_run_bounded", fake_reader)
    if present is None:
        with pytest.raises(recovery.RecoveryError):
            recovery._cid_present(CID, recovery.TARGET_834)
    else:
        assert recovery._cid_present(CID, recovery.TARGET_834) is present
    assert calls == [("docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={CID}")]


def test_r94_actual_full_json_reader_rejects_duplicate_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_reader(command: tuple[str, ...], *, stdout_limit: int = 0) -> str:
        assert command == ("docker", "inspect", "--format", recovery.FULL_FORMAT, CID)
        assert stdout_limit == 65535
        return '{"Id":"' + CID + '","Id":"' + CID + '"}'

    monkeypatch.setattr(observer, "_run_bounded", fake_reader)
    with pytest.raises(recovery.RecoveryError, match="DUPLICATE_JSON_KEY"):
        recovery._inspect_full_exact(CID, recovery.TARGET_834)


def test_r94_cli_has_no_external_cid_selector_and_no_cross_incident_receipts(
    tmp_path: Path,
) -> None:
    record = {
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
    path = tmp_path / "receipt"
    path.write_bytes(observer.canonical(record) + b"\n")
    assert recovery.main(["verify-834", str(path)]) == 0
    assert recovery.main(["verify-827", str(path)]) == 3
    assert recovery.main(["host-834", CID]) == 3
    path.write_text(json.dumps(record) + "\n", encoding="ascii")
    assert recovery.main(["verify-834", str(path)]) == 3


@pytest.mark.parametrize("previous", ["TARGET_795", "TARGET_807", "TARGET_819", "TARGET_827"])
def test_r94_earlier_reviewed_fixed_targets_remain_known(previous: str) -> None:
    recovery._known_target(getattr(recovery, previous))
