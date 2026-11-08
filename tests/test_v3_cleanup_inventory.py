"""V3 READ_ONLY cleanup plan bindings; all receipts are synthetic, no host access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v3_cleanup_observer", ROOT / "scripts/host_cutover_postapply_reconcile.py"
)
assert SPEC is not None and SPEC.loader is not None
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)

RUN = "42405706503"
SOURCE = "1273338005abf7203d26e618648fe55216030cf3"
LATEST_RUN = "42426260583"
LATEST_SOURCE = "f57173862df3143062a136452f2ffc7e3cc51d35"
LEGACY_ID = "a" * 64
PREPARE = "42381545964"


def _receipt(*, v3: bool) -> dict[str, object]:
    obj: dict[str, object] = {
        "version": f"boca-postapply-reconcile-{'v2' if v3 else 'v1'}",
        "incident_run_id": RUN,
        "prepare_run_id": None if v3 else PREPARE,
        "intent": "PRESENT",
        "result": "PRESENT",
        "stage": "ABSENT",
        "promotion_intent": "ABSENT",
        "promotion_result": "ABSENT",
        "terminal_state": "NO_GO",
        "cleanup": "INDETERMINATE",
        "original_restored": True,
        "commit_started": False,
        "legacy_id": LEGACY_ID,
        "original": {
            "id": LEGACY_ID,
            "name": "/boca-socios-controller-1",
            "running": True,
            "health": "healthy",
            "service": "controller",
            "port_binding": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
        },
        "port_8443": "BOCA_CONTROLLER_DOCKER_BOUND",
        "worker_id_recorded": False,
        "candidate_id_recorded": False,
        "go_for_retry": False,
        "runtime_attested": False,
        "foreign_resources_touched": False,
        "prepared_go_marker": "NOT_APPLICABLE" if v3 else "PRESENT_VERIFIED",
        "prepared_go_marker_reason": "V3_DISPATCH_WITHOUT_PREPARE" if v3 else "MARKER_SCHEMA_VALID",
    }
    if v3:
        obj["incident_source_sha"] = SOURCE
    return obj


def _raw(obj: dict[str, object]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def test_v3_original_derived_after_stage_cleared_without_prepare() -> None:
    assert (
        observer.verified_cleanup_legacy_id(_raw(_receipt(v3=True)), RUN, SOURCE, v3=True)
        == LEGACY_ID
    )
    assert (
        observer.verified_cleanup_legacy_id(_raw(_receipt(v3=False)), RUN, PREPARE, v3=False)
        == LEGACY_ID
    )


def test_latest_v3_original_still_requires_exact_incident_sha() -> None:
    record = _receipt(v3=True)
    record.update(incident_run_id=LATEST_RUN, incident_source_sha=LATEST_SOURCE)
    assert (
        observer.verified_cleanup_legacy_id(_raw(record), LATEST_RUN, LATEST_SOURCE, v3=True)
        == LEGACY_ID
    )
    with pytest.raises(observer.ReconcileError):
        observer.verified_cleanup_legacy_id(_raw(record), LATEST_RUN, SOURCE, v3=True)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("terminal_state", "ACCEPTED"),
        ("cleanup", "ACCEPT"),
        ("original_restored", False),
        ("commit_started", True),
        ("legacy_id", "b" * 64),
        ("port_8443", "UNVERIFIED"),
        ("original", None),
    ],
)
def test_v3_original_rejects_unsafe_receipt(field: str, bad: object) -> None:
    obj = _receipt(v3=True)
    obj[field] = bad
    with pytest.raises(observer.ReconcileError):
        observer.verified_cleanup_legacy_id(_raw(obj), RUN, SOURCE, v3=True)


@pytest.mark.parametrize("bad", [{"running": False}, {"health": None}, {"port_binding": {}}])
def test_v3_original_rejects_nonhealthy_or_nonloopback(bad: dict[str, object]) -> None:
    obj = _receipt(v3=True)
    original = obj["original"]
    assert type(original) is dict
    obj["original"] = {**original, **bad}
    with pytest.raises(observer.ReconcileError):
        observer.verified_cleanup_legacy_id(_raw(obj), RUN, SOURCE, v3=True)


def test_v3_original_refuses_cross_version_or_sha() -> None:
    for coordinate, v3 in (("e" * 40, True), (PREPARE, False), ("", True)):
        with pytest.raises(observer.ReconcileError):
            observer.verified_cleanup_legacy_id(_raw(_receipt(v3=True)), RUN, coordinate, v3=v3)


def test_v3_plan_runs_under_existing_reconcile_and_never_removes_docker() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()
    block = workflow.split("      - name: Plan Boca-only Docker cleanup READ_ONLY", 1)[1].split(
        "      - name: Require one unique R96 stage recovery dispatch", 1
    )[0]
    assert "if: inputs.operation == 'cutover-a-reconcile'\n" in block
    assert "inputs.protected_action_context != '42405706503'" not in block
    assert "BOCA_INCIDENT_SOURCE_SHA" in block
    assert "verified_cleanup_legacy_id" in block
    assert "< src/boca_socios/host_boca_cleanup.py" in block
    assert "src/boca_socios/host_boca_cleanup.py verify" in block
    assert all(word not in block for word in ("docker rm", "docker prune", "compose down"))


def test_workflow_reconcile_allowlists_latest_v3_without_prepare() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "42405706503|42426260583" in workflow
    assert 'incident["id"] in (42405706503, 42426260583)' in workflow
    assert f'"{LATEST_RUN}": "{LATEST_SOURCE}"' in workflow
    assert "BOCA_INCIDENT_SOURCE_SHA" in workflow
    assert "host-v3" in workflow and "verify-v3" in workflow


@pytest.mark.parametrize("run_id,sha", [(RUN, SOURCE), (LATEST_RUN, LATEST_SOURCE)])
def test_exact_embedded_github_attestation_accepts_only_trusted_v3_incidents(
    tmp_path: Path, run_id: str, sha: str
) -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    attestation = workflow.split("      - name: Authenticate V3 incident", 1)[1].split(
        "      - name: Reconcile exact failed Cutover A attempt", 1
    )[0]
    script = textwrap.dedent(attestation.split("<<'PY'\n", 1)[1].split("          PY\n", 1)[0])
    incident = {
        "id": int(run_id),
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "failure",
        "head_branch": "main",
        "head_sha": sha,
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        "actor": {"login": "mbalbo2023"},
        "display_title": "BOCA-SIMULATION-DEPLOY-V3",
        "path": ".github/workflows/boca-first-deploy.yml",
    }
    env = {
        **os.environ,
        "GITHUB_ENV": str(tmp_path / "github-env"),
        "BOCA_PROTECTED_ACTION_CONTEXT": run_id,
    }
    for mutation in (
        None,
        {"run_attempt": 2},
        {"head_sha": "d" * 40},
        {"actor": {"login": "another-user"}},
        {"conclusion": "success"},
        {"path": ".github/workflows/other.yml"},
        {"id": 11111111111},
    ):
        candidate = {**incident, **(mutation or {})}
        path = tmp_path / "incident.json"
        path.write_text(json.dumps(candidate))
        for optimize in (False, True):
            result = subprocess.run(  # noqa: S603 - local Python fixture, no network.
                [sys.executable, *(["-O"] if optimize else []), "-c", script, str(path)],
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert (result.returncode == 0) is (mutation is None)
            if mutation is None:
                assert f"BOCA_INCIDENT_SOURCE_SHA={sha}\n" in (tmp_path / "github-env").read_text()


def test_latest_terminal_v3_to_host_and_real_cleanup_handoff_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real observer+runner logic with synthetic owner data; zero Docker/SSH."""
    legacy_sha = "b" * 40
    intent = observer._canonical(
        {
            "version": "boca-cutover-a-intent-v1",
            "attempt_id": LATEST_RUN,
            "legacy_id": LEGACY_ID,
            "legacy_source_sha": legacy_sha,
            "legacy_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
            "legacy_compose_sha": "e" * 64,
            "target_source_sha": LATEST_SOURCE,
            "target_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64,
            "browser_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
            + "0" * 64,
            "target_compose_sha": "e" * 64,
            "overlay_sha": "1" * 64,
            "seccomp_sha": "2" * 64,
            "owner_subject_sha256": "3" * 64,
            "origin": "http://localhost:8443",
        }
    )
    result = {
        "version": "boca-cutover-a-terminal-v3",
        "attempt_id": LATEST_RUN,
        "legacy_id": LEGACY_ID,
        "legacy_source_sha": legacy_sha,
        "target_source_sha": LATEST_SOURCE,
        "intent_sha256": hashlib.sha256(intent).hexdigest(),
        "state": "NO_GO",
        "cleanup": "INDETERMINATE",
        "original_restored": True,
        "irreversible_commit_started": False,
        "candidate_id": None,
        "worker_id": None,
        "worker_primary_phase": "HEALTH_EXITED",
        "worker_compensation": "VERIFIED",
        "worker_exit_code": 1,
        "worker_oom_killed": False,
    }
    stored = {
        f"boca-cutover-a-intent-{LATEST_RUN}.json": intent,
        f"boca-cutover-a-result-{LATEST_RUN}.json": observer._canonical(result),
    }
    original = {
        "id": LEGACY_ID,
        "name": "/boca-socios-controller-1",
        "running": True,
        "health": "healthy",
        "image_id": "sha256:" + "d" * 64,
        "revision": legacy_sha,
        "service": "controller",
        "attempt": LATEST_RUN,
        "port_binding": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
    }
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(observer, "_private_home", lambda: tmp_path)
    monkeypatch.setattr(observer.Path, "is_dir", lambda self: self.name == observer.RECEIPT_DIR)
    monkeypatch.setattr(observer.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(observer, "_read_private", lambda name, *, directory: stored.get(name))
    monkeypatch.setattr(observer, "_docker_snapshot", lambda: [original])
    monkeypatch.setattr(observer, "_stage_preflight", lambda marker: {})
    monkeypatch.setattr(
        observer, "_marker", lambda prepared: ("PRESENT_VERIFIED", "MARKER_SCHEMA_VALID")
    )
    monkeypatch.setattr(
        observer,
        "_staged_attempt",
        lambda run_id: {
            "stage": "ABSENT",
            "promotion_intent": "ABSENT",
            "promotion_result": "ABSENT",
        },
    )
    observed = observer._host(LATEST_RUN, None, source_sha=LATEST_SOURCE)
    raw = _raw(observed)
    assert observer.verify_runner(raw, LATEST_RUN, None, source_sha=LATEST_SOURCE) == observed
    assert observer.verified_cleanup_legacy_id(raw, LATEST_RUN, LATEST_SOURCE, v3=True) == LEGACY_ID
    path = tmp_path / "host-observation.json"
    path.write_bytes(raw)
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    block = workflow.split("      - name: Plan Boca-only Docker cleanup READ_ONLY", 1)[1].split(
        "      - name: Require one unique R96 stage recovery dispatch", 1
    )[0]
    script = textwrap.dedent(block.split("<<'PY'\n", 1)[1].split("          PY\n", 1)[0])
    handoff = subprocess.run(  # noqa: S603 - local synthetic workflow parser.
        [sys.executable, "-c", script, LATEST_RUN, "", LATEST_SOURCE, str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert handoff.returncode == 0
    assert handoff.stdout.strip() == LEGACY_ID
    with pytest.raises(observer.ReconcileError):
        observer._host(LATEST_RUN, PREPARE)
    stored[f"boca-cutover-a-result-{LATEST_RUN}.json"] = observer._canonical(
        {**result, "intent_sha256": "f" * 64}
    )
    with pytest.raises(observer.ReconcileError):
        observer._host(LATEST_RUN, None, source_sha=LATEST_SOURCE)


@pytest.mark.parametrize(
    ("v3", "prepared", "source", "accepted"),
    [
        (True, "", SOURCE, True),
        (False, PREPARE, "", True),
        (True, "", "e" * 40, False),
        (True, PREPARE, SOURCE, False),
        (True, "", "", False),
    ],
)
def test_actual_workflow_runner_parser_accepts_only_one_authenticated_protocol(
    tmp_path: Path, v3: bool, prepared: str, source: str, accepted: bool
) -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    planner = workflow.split("      - name: Plan Boca-only Docker cleanup READ_ONLY", 1)[1].split(
        "      - name: Require one unique R96 stage recovery dispatch", 1
    )[0]
    # Run the Python embedded in the real YAML step, not a duplicate parser.
    script = textwrap.dedent(planner.split("<<'PY'\n", 1)[1].split("          PY\n", 1)[0])
    path = tmp_path / "observation.json"
    path.write_bytes(_raw(_receipt(v3=v3)))
    result = subprocess.run(  # noqa: S603 - local Python, synthetic bytes, no host.
        [sys.executable, "-c", script, RUN, prepared, source, str(path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert (result.returncode == 0) is accepted
    assert result.stdout.strip() == (LEGACY_ID if accepted else "")
