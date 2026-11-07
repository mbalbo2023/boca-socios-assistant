"""R90: extend the existing READ_ONLY observer to one failed #827 probe."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_recovery as recovery  # noqa: E402

ATTEMPT = "42368541950"
SOURCE = "8a69d155354362e0712dab1229f7d7e4b3e24dd6"
BROWSER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "902276a94bbec0ed0be30432baf97b5bd1298fc15e21eda750ccb785fa76bde0"
)
LEGACY_ID = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
LEGACY_SOURCE = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
LEGACY_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59"
)
CID = "a1" * 32


@pytest.mark.parametrize("running", [False, True])
def test_r90_827_inspects_exact_probe_without_writes(
    monkeypatch: pytest.MonkeyPatch, running: bool
) -> None:
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    monkeypatch.setattr(
        observer,
        "_runtime_stat",
        lambda name: "PRESENT_OWNED" if name == "docker.sock" else "ABSENT",
    )
    observed: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        observed.append(args)
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
    assert len(observed) == 4
    assert {cmd[0] for cmd in observed} == {"ps", "inspect"}
    assert observer.verify(observer.canonical(receipt) + b"\n", ATTEMPT, LEGACY_ID) == receipt


def test_r90_827_identity_closed_and_recovery_not_authorized() -> None:
    assert observer.KNOWN_FAILED_PROBES[ATTEMPT] == (SOURCE, BROWSER)
    assert set(observer.KNOWN_FAILED_PROBES) == {
        "42329475083",
        "42341290485",
        "42353468231",
        ATTEMPT,
    }
    with pytest.raises(observer.InspectError, match="COORDINATES"):
        observer._validate("42368541951", LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE)
    with pytest.raises(recovery.RecoveryError, match="UNREVIEWED_TARGET"):
        recovery._known_target(
            recovery.RecoveryTarget(
                ATTEMPT, CID, SOURCE, BROWSER, LEGACY_ID, LEGACY_SOURCE, LEGACY_IMAGE
            )
        )


def test_r90_827_workflow_is_exact_and_readonly() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    case = workflow.split("            cutover-a-worker-inspect)\n", 1)[1].split(
        "              ;;", 1
    )[0]
    assert '42368541950) test "$BOCA_PROTECTED_ACTION_CONTEXT" = 42368541950' in case
    assert 'test -z "$BOCA_SOURCE_SHA_SUBMITTED"' in case
    assert 'test -z "$BOCA_IMAGE_REF"' in case
    assert 'test -z "$BOCA_BROWSER_IMAGE_REF"' in case
    assert 'test -z "$BOCA_RELEASE_RUN_ID"' in case
    assert 'test -z "$BOCA_LEGACY_RELEASE_RUN_ID"' in case
    assert "BOCA-R90-WORKER-827-READONLY" in workflow
    step = workflow.split(
        "      - name: Inspect one failed Boca worker probe READ_ONLY by exact identity", 1
    )[1].split("\n      - name:", 1)[0]
    assert "scripts/host_cutover_worker_inspect.py verify" in step
    assert "umask 077" in step and "ulimit -f 4" in step
    for forbidden in ("docker stop", "docker rm", "docker pull", "docker run", "docker exec"):
        assert forbidden not in step
