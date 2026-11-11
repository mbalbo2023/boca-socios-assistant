"""R178 pure upgrade PLAN: no host effect and never Cutover authorization."""

from __future__ import annotations

import json
from importlib import import_module

import pytest

from boca_socios import host_boca_pair_observe as observer

RUN = "43066120206"
OLD_SHA = "03df9a14bdd78cf768386a865876fed9d5656911"
NEW_SHA = "bd6c1212f129454f10e5d4a25585c3f4eeb8edea"
OLD_ATTEMPT = "42806447101"
CONTROLLER_ID = "cc489d7010b2ddd1307086422bf28553f06348939bc33d0344a84dbb4c3d63c4"
WORKER_ID = "a3293c4e48c4ee11b52749fdd64a33e50fa2ac0805cbf64ce7e6028d86520033"
NETWORKS = ("c" * 64, "d" * 64)


def _planner():
    return import_module("boca_socios.host_boca_pair_upgrade_plan")


def _receipt():
    volumes = [
        "boca-socios_boca_browser_ipc",
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
    ]
    return observer._canonical(
        {
            "schema": 1,
            "state": "OBSERVED",
            "source_sha": OLD_SHA,
            "attempt_id": OLD_ATTEMPT,
            "services": [
                {
                    "service": "controller",
                    "container_id": CONTROLLER_ID,
                    "running": True,
                    "status": "running",
                    "pid": 1133025,
                    "exit_code": 0,
                    "health": "healthy",
                    "image_id": "sha256:" + "1" * 64,
                    "image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
                    "fcb150f720d1100a09a255a569e9e56b3a2c8b24ecdecc4b7783f696a50b9d3d",
                    "config_hash": "3" * 64,
                    "network_name": "boca-socios_boca_private",
                    "network_id": NETWORKS[0],
                    "volumes": volumes,
                    "port_8443": "LOOPBACK",
                },
                {
                    "service": "browser-worker",
                    "container_id": WORKER_ID,
                    "running": False,
                    "status": "exited",
                    "pid": 0,
                    "exit_code": 1,
                    "health": "unhealthy",
                    "image_id": "sha256:" + "4" * 64,
                    "image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
                    "6abc00be6407e4bef508bb6f97587ce80186b0391f1d9c5ae909bf1de1d13b73",
                    "config_hash": "6" * 64,
                    "network_name": "none",
                    "network_id": "UNATTACHED",
                    "volumes": ["boca-socios_boca_browser_ipc"],
                    "port_8443": "NONE",
                },
            ],
            "volumes": volumes,
            "ipc_volume": "BOTH",
            "observation_run_id": RUN,
            "observer_writes": 0,
            "foreign_resources_touched": 0,
            "cutover_authorized": False,
        }
    )


def _release(**overrides):
    data = {
        "source_sha": NEW_SHA,
        "release_run_id": "43057984253",
        "controller_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "7" * 64,
        "worker_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "8" * 64,
    }
    data.update(overrides)
    return _planner().CandidateRelease(**data)


def _plan(*, receipt=None, release=None, attempt="43099988877"):
    return _planner().prepare(
        _receipt() if receipt is None else receipt,
        observation_run_id=RUN,
        attempt_id=attempt,
        release=_release() if release is None else release,
    )


def test_upgrade_plan_binds_exact_existing_pair_and_new_digest_without_go():
    raw = _plan()
    assert _planner().verify(raw, "43099988877") == raw
    value = json.loads(raw.removeprefix(b"BOCA_DUAL_UPGRADE_PLAN "))
    assert value == {
        "schema": 1,
        "state": "CODE_ONLY_HOST_PROOF_PENDING",
        "planning_attempt_id": "43099988877",
        "observed_run_id": RUN,
        "old_attempt_id": OLD_ATTEMPT,
        "old_source_sha": OLD_SHA,
        "old_controller_id": CONTROLLER_ID,
        "old_worker_id": WORKER_ID,
        "old_controller_image_id": "sha256:" + "1" * 64,
        "old_worker_image_id": "sha256:" + "4" * 64,
        "old_worker_status": "exited",
        "old_worker_exit_code": 1,
        "old_worker_network": "NONE",
        "new_source_sha": NEW_SHA,
        "new_release_run_id": "43057984253",
        "new_controller_image_ref": _release().controller_image_ref,
        "new_worker_image_ref": _release().worker_image_ref,
        "controller_healthy": True,
        "worker_stopped": True,
        "worker_pid0": "OBSERVED_HISTORICAL",
        "ipc_shared": True,
        "ipc_socket_handshake": "UNVERIFIED",
        "port_8443": "LOOPBACK_ONLY",
        "panel_live_http": "UNVERIFIED",
        "target_egress_bridge": "UNVERIFIED",
        "preserve_volumes": [
            "boca-socios_boca_browser_ipc",
            "boca-socios_boca_data",
            "boca-socios_boca_key",
            "boca-socios_boca_owner",
        ],
        "host_binding": "UNVERIFIED",
        "database_inode": "UNVERIFIED",
        "release_provenance": "RUNNER_VERIFICATION_REQUIRED",
        "candidate_cids": "UNCREATED",
        "observer_writes": 0,
        "docker_writes": 0,
        "apply_authorized": False,
    }


@pytest.mark.parametrize(
    ("mutator", "name"),
    [
        (lambda data: data["services"][0].update(running=False), "controller stopped"),
        (lambda data: data["services"][0].update(health="unhealthy"), "controller sick"),
        (lambda data: data["services"][1].update(running=True), "worker started"),
        (lambda data: data["services"][1].update(exit_code=0), "historical exit code changed"),
        (lambda data: data["services"][1].update(pid=4), "historical worker still has PID"),
        (lambda data: data.update(ipc_volume="CONTROLLER_ONLY"), "IPC detached"),
        (
            lambda data: data["services"][0].update(network_id=data["services"][1]["network_id"]),
            "network shared",
        ),
        (lambda data: data["volumes"].remove("boca-socios_boca_data"), "data absent"),
    ],
)
def test_upgrade_plan_rejects_unhealthy_ambiguous_or_unprotected_pair(mutator, name):
    pair = json.loads(_receipt().removeprefix(b"BOCA_INSTALLED_PAIR "))
    mutator(pair)
    modified = observer._canonical(pair)
    with pytest.raises((observer.PairNoGo, _planner().UpgradeNoGo)):
        _plan(receipt=modified)


@pytest.mark.parametrize(
    "bad_release",
    [
        {"source_sha": OLD_SHA},
        {"controller_image_ref": "ubuntu:latest"},
        {"worker_image_ref": "ghcr.io/foreign/worker@sha256:" + "8" * 64},
        {"release_run_id": "0"},
    ],
)
def test_upgrade_plan_rejects_identical_source_or_invalid_release_coordinates(bad_release):
    with pytest.raises(_planner().UpgradeNoGo):
        _plan(release=_release(**bad_release))


def test_upgrade_plan_rejects_replayed_historical_attempt_and_invalid_receipt():
    with pytest.raises(_planner().UpgradeNoGo):
        _plan(attempt=OLD_ATTEMPT)
    with pytest.raises((observer.PairNoGo, _planner().UpgradeNoGo)):
        _plan(receipt=_receipt().replace(b'"observer_writes":0', b'"observer_writes":1'))


def test_upgrade_plan_has_no_effectful_module_imports(monkeypatch):
    from boca_socios import host_boca_cleanup as cleanup

    monkeypatch.setattr(cleanup, "_docker", lambda *_: pytest.fail("Docker forbidden"))
    monkeypatch.setattr(
        cleanup, "protected_boca_job_lease", lambda *_: pytest.fail("host lease forbidden")
    )
    assert _planner().verify(_plan(), "43099988877").startswith(b"BOCA_DUAL_UPGRADE_PLAN ")


def test_upgrade_plan_strict_receipt_schema_never_promotes_to_go():
    original = _plan()
    assert b'"apply_authorized":false' in original
    with pytest.raises(_planner().UpgradeNoGo):
        _planner().verify(
            original.replace(b'"apply_authorized":false', b'"apply_authorized":true'), "43099988877"
        )
    with pytest.raises(_planner().UpgradeNoGo):
        _planner().verify(
            original.replace(b'"docker_writes":0', b'"docker_writes":1'), "43099988877"
        )
