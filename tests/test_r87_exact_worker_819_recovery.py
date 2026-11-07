"""TDD contracts for an exact, non-force stopped-only #819 recovery (offline)."""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_recovery as recovery  # noqa: E402

from test_r82_exact_worker_807_recovery import (  # noqa: E402
    PROFILE,
)
from test_r82_exact_worker_807_recovery import (  # noqa: E402
    _full_worker as r82_full,
)
from test_r82_exact_worker_807_recovery import (  # noqa: E402
    _snapshot as r82_snapshot,
)

ATTEMPT = "42353468231"
CID = "4c2c40eaa7183e83440792466e844093a29c8b977e72c098c7be6a469f066547"
SOURCE = "0538b3fb29cc0245a8387b7023c394883d0ea9a8"
IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "d740c610d032aa20fecff1602cc96e49fd63c597c49855990a9bc081a6998619"
)


def _snapshot(*, present: bool) -> dict[str, Any]:
    record = r82_snapshot(present=present)
    record["attempt"] = ATTEMPT
    if present:
        record["probe_id"] = CID
        record["probe_candidate_id"] = CID
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, recovery.LEGACY_ID)
    return record


def _full_worker() -> dict[str, Any]:
    record = r82_full()
    record["Id"] = CID
    record["Name"] = f"/{observer.PREFIX}{ATTEMPT}"
    record["Config"]["Image"] = IMAGE
    record["Config"]["Labels"]["boca.socios.cutover-preflight-attempt"] = ATTEMPT
    record["Config"]["Labels"]["org.opencontainers.image.revision"] = SOURCE
    return record


def _simulate(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Exercise the real transaction, with every host effect replaced by a fake."""
    state: dict[str, Any] = {
        "reads": 0,
        "full_reads": 0,
        "rm": [],
        "removed": False,
        "before": _snapshot(present=True),
        "after": _snapshot(present=False),
        "full": _full_worker(),
        "second": None,
        "ack": CID,
        "rm_error": None,
    }

    @contextmanager
    def lease(attempt: str) -> Iterator[object]:
        assert attempt == ATTEMPT
        yield object()

    def verify_lease(_lease: object, attempt: str) -> None:
        assert attempt == ATTEMPT

    def observe(*_args: object, **_kwargs: object) -> dict[str, Any]:
        state["reads"] += 1
        if state["removed"]:
            return copy.deepcopy(state["after"])
        if state["reads"] == 2 and state["second"] is not None:
            return copy.deepcopy(state["second"])
        return copy.deepcopy(state["before"])

    def inspect_full(_cid: str, *, target: recovery.RecoveryTarget) -> dict[str, Any]:
        assert _cid == CID and target is recovery.TARGET_819
        state["full_reads"] += 1
        return copy.deepcopy(state["full"])

    def remove(_cid: str, *, target: recovery.RecoveryTarget) -> str:
        assert _cid == CID and target is recovery.TARGET_819
        state["rm"].append(_cid)
        if state["rm_error"] is not None:
            raise state["rm_error"]
        state["removed"] = True
        return state["ack"]

    def cid_present(_cid: str, *, target: recovery.RecoveryTarget) -> bool:
        assert _cid == CID and target is recovery.TARGET_819
        return not state["removed"]

    monkeypatch.setattr(recovery.cleanup, "protected_boca_job_lease", lease)
    monkeypatch.setattr(recovery.cleanup, "verify_protected_boca_job_lease", verify_lease)
    monkeypatch.setattr(recovery, "_observe", observe)
    monkeypatch.setattr(recovery, "_inspect_full_exact", inspect_full)
    monkeypatch.setattr(recovery, "_profile", lambda: PROFILE)
    monkeypatch.setattr(recovery, "_remove_exact", remove)
    monkeypatch.setattr(recovery, "_cid_present", cid_present)
    return state


def test_r87_target_is_a_single_immutable_reviewed_object() -> None:
    target = recovery.TARGET_819
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
    with pytest.raises(recovery.RecoveryError):
        recovery._known_target(dataclasses.replace(target, cid="a" * 64))


@pytest.mark.parametrize("status", ["created", "exited"])
def test_r87_exact_stopped_worker_removed_once_with_dual_precheck(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    state = _simulate(monkeypatch)
    state["full"]["State"]["Status"] = status

    receipt = recovery.execute(target=recovery.TARGET_819)

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
    recovery.verify_runner(observer.canonical(receipt) + b"\n", target=recovery.TARGET_819)


@pytest.mark.parametrize(
    ("mutator", "field", "value"),
    [
        ("before", "probe_running", True),
        ("before", "seccomp", "PRESENT"),
        ("before", "original", "NOT_HEALTHY"),
        ("full", "Name", "/foreign-container"),
        ("full", "Id", "e" * 64),
    ],
)
def test_r87_unsafe_identity_or_running_probe_never_removed(
    monkeypatch: pytest.MonkeyPatch, mutator: str, field: str, value: Any
) -> None:
    state = _simulate(monkeypatch)
    state[mutator][field] = value
    receipt = recovery.execute(target=recovery.TARGET_819)
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert receipt["docker_writes"] == 0 and state["rm"] == []


def test_r87_second_snapshot_race_never_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _simulate(monkeypatch)
    state["second"] = _snapshot(present=True)
    state["second"]["probe_running"] = True
    receipt = recovery.execute(target=recovery.TARGET_819)
    assert receipt["cleanup"] == "NO_GO_PRECHECK"
    assert state["rm"] == [] and state["full_reads"] == 1


@pytest.mark.parametrize("failure", ["wrong_ack", "exception"])
def test_r87_lost_docker_rm_ack_never_retried(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = _simulate(monkeypatch)
    if failure == "wrong_ack":
        state["ack"] = "a" * 64
    else:
        state["rm_error"] = RuntimeError("docker unavailable")
    receipt = recovery.execute(target=recovery.TARGET_819)
    assert receipt["cleanup"] == "INDETERMINATE"
    assert receipt["phase"] == "REMOVE" and receipt["docker_writes"] == 1
    assert receipt["retry_authorized"] is False and state["rm"] == [CID]


def test_r87_postcheck_legacy_loss_indeterminate_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _simulate(monkeypatch)
    state["after"]["original"] = "NOT_HEALTHY"
    receipt = recovery.execute(target=recovery.TARGET_819)
    assert receipt["cleanup"] == "INDETERMINATE"
    assert receipt["docker_writes"] == 1 and state["rm"] == [CID]


def test_r87_seccomp_sha_pinned_even_with_equivalent_json_profile() -> None:
    target = recovery.TARGET_819
    variant = PROFILE + b"\n"
    assert json.loads(variant) == json.loads(PROFILE)
    with pytest.raises(recovery.RecoveryError, match="PROFILE_SHA_MISMATCH"):
        recovery._validate_isolation(_full_worker(), variant, target=target)
    recovery._validate_isolation(_full_worker(), PROFILE, target=target)


def test_r87_cli_verifier_accepts_only_exact_attempt(tmp_path: Path) -> None:
    exact = {
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
    receipt = tmp_path / "exact.json"
    receipt.write_bytes(observer.canonical(exact) + b"\n")
    assert recovery.main(["verify-819", str(receipt)]) == 0
    assert recovery.main(["verify-807", str(receipt)]) == 3
    assert recovery.main(["host-819", CID]) == 3  # no user-provided target


def test_r87_protected_zip_bootstrap_and_workflow_use_one_shared_recovery() -> None:
    builder = (ROOT / "scripts/build_protected_boca_bundle.py").read_text()
    bootstrap = (ROOT / "scripts/boca_protected_memfd_bootstrap.py").read_text()
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "cutover-worker-819-recover" in builder
    assert "cutover-worker-819-recover" in bootstrap
    assert "host-819" in builder
    assert "cutover-a-worker-recover-819" in workflow
    assert "BOCA-R87-WORKER-819-RECOVER-ONCE" in workflow
    assert "boca-worker-recovery-42353468231" in workflow
    assert workflow.count("cutover-a-worker-recover-819,") == 1
    assert "--worker-recovery" in workflow
    host = workflow.split(
        "      - name: Recover only the stopped exact 795 807 or 819 worker probe under Boca lease\n",
        1,
    )[1].split("\n      - name:", 1)[0]
    assert not any(line.lstrip().startswith("docker container rm ") for line in host.splitlines())
    assert not any(line.lstrip().startswith("docker stop ") for line in host.splitlines())
