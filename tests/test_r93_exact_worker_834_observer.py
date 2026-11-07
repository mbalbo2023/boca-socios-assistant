"""R93: an exact, READ_ONLY investigation of the failed R92 #834 probe."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_recovery as recovery  # noqa: E402

ATTEMPT = "42375050546"
SOURCE = "79da7ebe9918d98216ac7eb46ff008d7f6e62429"
BROWSER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "ed276066b108fad5b130d0fdffdd3f38a5a3d912253b1d4267bd4b6184992ba8"
)
LEGACY_ID = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
LEGACY_SOURCE = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
LEGACY_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59"
)
CID = "b2" * 32


@pytest.mark.parametrize("running", [False, True])
def test_r93_834_inspects_exact_probe_without_host_writes(
    monkeypatch: pytest.MonkeyPatch, running: bool
) -> None:
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(
        observer,
        "_runtime_stat",
        lambda name: "PRESENT_OWNED" if name == "docker.sock" else "ABSENT",
    )
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if args[0] == "ps":
            assert args[-1] == f"name=^/boca-socios-cutover-preflight-{ATTEMPT}$"
            return CID
        assert args[:2] == ("inspect", "--format")
        if args[3] == CID and args[2] == observer.INSPECT_FULL_JSON_LENGTH:
            return "54321"
        if args[3] == CID:
            assert args[2] == observer.INSPECT_NO_HEALTH
            return json.dumps(
                {
                    "id": CID,
                    "name": f"/boca-socios-cutover-preflight-{ATTEMPT}",
                    "image_ref": BROWSER,
                    "revision": SOURCE,
                    "project": "boca-socios",
                    "attempt": ATTEMPT,
                    "running": running,
                    "health": None,
                    "ports": {},
                }
            )
        assert args[3] == LEGACY_ID and args[2] == observer.INSPECT
        return json.dumps(
            {
                "id": LEGACY_ID,
                "name": "/boca-socios-controller-1",
                "image_ref": LEGACY_IMAGE,
                "revision": LEGACY_SOURCE,
                "project": "boca-socios",
                "attempt": None,
                "running": True,
                "health": "healthy",
                "ports": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            }
        )

    monkeypatch.setattr(observer, "_docker", docker)
    receipt = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    assert receipt["probe"] == "PRESENT_PIN_MATCH"
    assert receipt["probe_id"] == CID
    assert receipt["probe_running"] is running
    assert receipt["seccomp"] == "ABSENT"
    assert receipt["probe_full_json_stage"] == "BELOW_CLEANUP_LIMIT"
    assert receipt["original"] == "RUNNING_HEALTHY"
    assert receipt["original_port"] == "LOOPBACK_8443"
    assert receipt["observer_writes"] == 0
    assert receipt["foreign_resources_touched"] is False
    assert receipt["cutover_authorized"] is False
    assert len(calls) == 4
    assert {call[0] for call in calls} == {"ps", "inspect"}
    assert observer.verify(observer.canonical(receipt) + b"\n", ATTEMPT, LEGACY_ID) == receipt


def test_r93_834_identity_closed_and_recovery_not_enabled() -> None:
    assert observer.KNOWN_FAILED_PROBES[ATTEMPT] == (SOURCE, BROWSER)
    assert set(observer.KNOWN_FAILED_PROBES) == {
        "42329475083",
        "42341290485",
        "42353468231",
        "42368541950",
        ATTEMPT,
    }
    with pytest.raises(observer.InspectError, match="COORDINATES"):
        observer._validate("42375050547", LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    with pytest.raises(recovery.RecoveryError, match="UNREVIEWED_TARGET"):
        recovery._known_target(
            recovery.RecoveryTarget(
                ATTEMPT, CID, SOURCE, BROWSER, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE
            )
        )


def test_r93_834_workflow_gate_cannot_dispatch_unrelated_mutation() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert (
        "uv run pytest -q tests/test_r86_exact_worker_819_observer.py tests/test_r90_exact_worker_827_observer.py tests/test_r93_exact_worker_834_observer.py"
        in workflow
    )
    case = workflow.split("            cutover-a-worker-inspect)\n", 1)[1].split(
        "              ;;", 1
    )[0]
    assert '42375050546) test "$BOCA_PROTECTED_ACTION_CONTEXT" = 42375050546' in case
    for forbidden_input in (
        'test -z "$BOCA_SOURCE_SHA_SUBMITTED"',
        'test -z "$BOCA_IMAGE_REF"',
        'test -z "$BOCA_BROWSER_IMAGE_REF"',
        'test -z "$BOCA_RELEASE_RUN_ID"',
        'test -z "$BOCA_LEGACY_RELEASE_RUN_ID"',
    ):
        assert forbidden_input in case
    assert "BOCA-R93-WORKER-834-READONLY" in workflow
    step = workflow.split(
        "      - name: Inspect one failed Boca worker probe READ_ONLY by exact identity", 1
    )[1].split("\n      - name:", 1)[0]
    assert "scripts/host_cutover_worker_inspect.py verify" in step
    for command in ("docker stop", "docker rm", "docker pull", "docker run", "docker exec"):
        assert command not in step
