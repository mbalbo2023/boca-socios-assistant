"""Offline regression for incident #386; no real Docker, host, or network."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import host_cutover_postapply_reconcile as reconcile

RUN = "42096941815"
PREPARE = "42091200929"
LEGACY_ID = "a" * 64
TARGET_SHA = "c" * 40


def _intent() -> bytes:
    return reconcile._canonical(
        {
            "version": "boca-cutover-a-intent-v1",
            "attempt_id": RUN,
            "legacy_id": LEGACY_ID,
            "legacy_source_sha": "b" * 40,
            "legacy_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
            "legacy_compose_sha": "e" * 64,
            "target_source_sha": TARGET_SHA,
            "target_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64,
            "browser_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "0" * 64,
            "target_compose_sha": "e" * 64,
            "overlay_sha": "1" * 64,
            "seccomp_sha": "2" * 64,
            "owner_subject_sha256": "3" * 64,
            "origin": "http://localhost:8443",
        }
    )


def _result() -> bytes:
    return reconcile._canonical(
        {
            "version": "boca-cutover-a-terminal-v1",
            "attempt_id": RUN,
            "legacy_id": LEGACY_ID,
            "legacy_source_sha": "b" * 40,
            "target_source_sha": TARGET_SHA,
            "intent_sha256": hashlib.sha256(_intent()).hexdigest(),
            "state": "NO_GO",
            "cleanup": "INDETERMINATE",
            "original_restored": False,
            "irreversible_commit_started": False,
            "candidate_id": None,
            "worker_id": None,
        }
    )


def _container(ident: str, *, service: str, revision: str, name: str, running: bool):
    return {
        "id": ident,
        "name": name,
        "running": running,
        "health": "healthy" if running else None,
        "image_id": "sha256:" + "d" * 64,
        "revision": revision,
        "service": service,
        "attempt": RUN,
        "port_binding": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
        if service == "controller" else {},
    }


@pytest.mark.parametrize("kind,raw", [("intent", _intent()), ("result", _result())])
def test_exact_canonical_markers(kind: str, raw: bytes) -> None:
    assert reconcile._record(raw, RUN, kind=kind)["attempt_id"] == RUN
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(raw, "42096941816", kind=kind)
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(raw + b"\n", RUN, kind=kind)


def test_duplicate_marker_keys_rejected() -> None:
    malformed = _intent().replace(b'"attempt_id":"42096941815"', b'"attempt_id":"42096941815","attempt_id":"42096941815"')
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(malformed, RUN, kind="intent")


def test_postapply_runtime_only_read_from_boca_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    files = {
        f"boca-cutover-a-intent-{RUN}.json": _intent(),
        f"boca-cutover-a-result-{RUN}.json": _result(),
    }
    monkeypatch.setattr(reconcile.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(reconcile.os, "getegid", lambda: 10001)
    monkeypatch.setattr(reconcile, "_private_home", lambda: Path("/home/fixture-boca-owner"))
    monkeypatch.setattr(reconcile.Path, "is_dir", lambda self: self.name == reconcile.RECEIPT_DIR)
    monkeypatch.setattr(reconcile.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(reconcile, "_read_private", lambda name, *, directory: files.get(name))
    original = _container(
        LEGACY_ID, service="controller", revision="b" * 40,
        name="/boca-socios-controller-legacy-" + RUN, running=False,
    )
    candidate = _container(
        "f" * 64, service="controller", revision=TARGET_SHA,
        name="/boca-socios-controller-1", running=True,
    )
    worker = _container(
        "9" * 64, service="browser-worker", revision=TARGET_SHA,
        name="/boca-socios-browser-worker-1", running=True,
    )
    monkeypatch.setattr(reconcile, "_docker_snapshot", lambda: [original, candidate, worker])
    monkeypatch.setattr(reconcile, "_marker", lambda marker: "PRESENT_VERIFIED")
    monkeypatch.setattr(
        reconcile, "_staged_attempt",
        lambda attempt: {"stage": "PRESENT", "promotion_intent": "ABSENT", "promotion_result": "ABSENT"},
    )
    output = reconcile._host(RUN, PREPARE)
    assert output["original"]["running"] is False
    assert output["candidate_controllers"][0]["running"] is True
    assert output["browser_workers"][0]["running"] is True
    assert output["port_8443"] == "BOCA_CONTROLLER_DOCKER_BOUND"
    assert output["result"] == "PRESENT"
    assert output["go_for_retry"] is False
    assert output["foreign_resources_touched"] is False
    assert reconcile.verify_runner(reconcile._canonical(output) + b"\n", RUN, PREPARE) == output


def test_no_docker_write_or_foreign_inspect_command() -> None:
    for command in (
        ("exec", "container", "python"),
        ("rm", "container"),
        ("ps", "-q"),
        ("volume", "rm", "boca-socios_boca_data"),
        ("compose", "down"),
        ("system", "prune"),
    ):
        with pytest.raises(reconcile.ReconcileError, match="DOCKER_COMMAND"):
            reconcile._docker(*command)


def test_runner_rejects_forged_accept_and_noncanonical_payload() -> None:
    payload = {"version": "boca-postapply-reconcile-v1", "incident_run_id": RUN,
               "prepare_run_id": PREPARE, "go_for_retry": True,
               "runtime_attested": False, "foreign_resources_touched": False}
    with pytest.raises(reconcile.ReconcileError):
        reconcile.verify_runner(reconcile._canonical(payload) + b"\n", RUN, PREPARE)
    payload["go_for_retry"] = False
    with pytest.raises(reconcile.ReconcileError):
        reconcile.verify_runner(reconcile._canonical(payload) + b" \n", RUN, PREPARE)


def test_readonly_code_scope_and_no_blackbox_import() -> None:
    source = Path(reconcile.__file__).read_text(encoding="utf-8")
    assert "src/boca_socios/browser" not in source
    assert "subprocess.run" in source
    assert "DOCKER_HOST" in source
