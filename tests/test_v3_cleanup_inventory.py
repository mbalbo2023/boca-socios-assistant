"""V3 READ_ONLY cleanup plan bindings; all receipts are synthetic, no host access."""

from __future__ import annotations

import importlib.util
import json
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
