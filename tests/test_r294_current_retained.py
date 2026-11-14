"""Successor custody from actual R291 ZIPs; no host, Docker or public I/O."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_retained_resources as legacy

EVIDENCE = Path(__file__).parent / "evidence" / "r294"
RUN = "43590000002"
SOURCE = "0ebecb69a6bc35b72a8c4ceda46119d601ca2dbe"
APPLY = "43534359504"
CONTROL = "8" * 64  # Future live inode witness in this offline fixture, NOT host evidence.
ZIP_SHA = {
    "release864-controller.zip": "2f522e76876d323868a36df37969ed03c52b2dbda2dc3ba9a5830ecfb32b6817",
    "release864-paired.zip": "399b164d68f2dda83f2c9dca46d2dda096d4e3f033e096528b2edd0d79874aa8",
    "retained1101.zip": "7dd70bf3fc23e5cb0c37cc6415ed9befb764bd7185148147eb09f5507ac1f20a",
    "pair1103.zip": "dc2ee54c41d78b3b18e9a3bf621748245052b75c4978339273be8543eaf9ab04",
}


def evidence(filename: str) -> bytes:
    path = EVIDENCE / filename
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ZIP_SHA[filename]
    with zipfile.ZipFile(path) as archive:
        assert len(archive.namelist()) == 1
        return archive.read(archive.namelist()[0])


def module() -> Any:
    name = "boca_socios.host_boca_current_retained"
    assert importlib.util.find_spec(name) is not None, "missing current-pair retained observer"
    return importlib.import_module(name)


def current_pair(*, run: str = RUN, stopped: bool = False) -> bytes:
    value = json.loads(evidence("pair1103.zip").removeprefix(b"BOCA_INSTALLED_PAIR "))
    value["observation_run_id"] = run
    if stopped:
        value["services"][1]["status"] = "exited"
    return pair._canonical(value)


def installation():
    from boca_socios import host_boca_binding_observe as binding
    from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

    value = json.loads(current_pair().removeprefix(pair._PREFIX))
    controller, worker = value["services"]
    return OnDemandInstallation(
        APPLY,
        SOURCE,
        controller["container_id"],
        controller["image_ref"],
        worker["container_id"],
        worker["image_ref"],
        binding.CANONICAL_DATABASE,
        ReviewedInstalledPair(APPLY, controller["config_hash"], worker["config_hash"]),
    )


def fixture_snapshot(*, stopped: bool = False) -> dict[str, object]:
    """Explicit new observation fixture; never re-label the original V1 ZIP."""
    history = json.loads(evidence("retained1101.zip").removeprefix(b"BOCA_RETAINED_RESOURCES "))
    observed = json.loads(current_pair(stopped=stopped).removeprefix(b"BOCA_INSTALLED_PAIR "))
    return {
        "schema": 2,
        "state": "READ_ONLY",
        "scope": "CURRENT_PAIR",
        "observation_run_id": RUN,
        "source_sha": SOURCE,
        "installation_attempt": APPLY,
        "pair": observed,
        "volumes": history["volumes"],
        "egress": history["egress"],
        "control_socket_directory_inode_sha256": CONTROL,
        "binding_fingerprint": "9" * 64,
        "worker_idle": {
            "state": "STOP_APPLIED" if stopped else "CREATED",
            "operation_id": "00000000-0000-4000-8000-000000000001" if stopped else None,
        },
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "successor_apply_authorized": False,
    }


def test_current_receipt_uses_actual_1102_pair_and_current_control_inode() -> None:
    value = fixture_snapshot()
    raw = module().observe(RUN, snapshot_reader=lambda _run: value)
    parsed = module().verify(raw, RUN)
    assert parsed["source_sha"] == SOURCE
    assert parsed["installation_attempt"] == APPLY
    assert parsed["control_socket_directory_inode_sha256"] == CONTROL
    assert parsed["volumes"][0]["creator_attempt"] == "42806447101"
    assert parsed["volumes"][1]["creator_attempt"] == "43217075287"
    assert parsed["egress"]["creator_attempt"] == "43217075287"
    with pytest.raises(legacy.ResourceNoGo):
        legacy.verify(raw, RUN)
    assert legacy.verify(evidence("retained1101.zip"), "43504739633")


@pytest.mark.parametrize(
    "damage", ("legacy_source", "wrong_cid", "creator", "active_peer", "stop_missing")
)
def test_current_custody_rejects_five_cross_generation_failures(damage: str) -> None:
    value = fixture_snapshot(stopped=True)
    if damage == "legacy_source":
        value["source_sha"] = "b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72"
    elif damage == "wrong_cid":
        value["pair"]["services"][1]["container_id"] = "f" * 64
        value["pair"]["services"][0]["container_id"] = "f" * 64
    elif damage == "creator":
        value["volumes"][1]["creator_attempt"] = APPLY
    elif damage == "active_peer":
        value["egress"]["peer_ids"] = ["f" * 64]
    else:
        value["worker_idle"]["operation_id"] = None
    with pytest.raises(module().CurrentRetainedNoGo):
        module().observe(RUN, snapshot_reader=lambda _run: value)


def test_current_inode_drift_between_reads_fails_closed() -> None:
    first, second = fixture_snapshot(), fixture_snapshot()
    second["control_socket_directory_inode_sha256"] = "7" * 64
    values = iter((first, second))
    with pytest.raises(module().CurrentRetainedNoGo):
        module().observe(RUN, snapshot_reader=lambda _run: next(values))


def test_exited_zero_requires_current_applied_stop_and_exact_binding() -> None:
    m = module()
    from boca_socios.host_on_demand_lifecycle import PanelStatus

    proof = m.idle_evidence(
        {"status": "exited", "running": False, "pid": 0, "exit_code": 0},
        PanelStatus(
            "00000000-0000-4000-8000-000000000001", "stop", "APPLIED", "NONE", None, None, None
        ),
    )
    assert proof["state"] == "STOP_APPLIED"
    for status in (
        None,
        PanelStatus(proof["operation_id"], "stop", "REQUESTED", "NONE", None, None, None),
    ):
        with pytest.raises(m.CurrentRetainedNoGo):
            m.idle_evidence(
                {"status": "exited", "running": False, "pid": 0, "exit_code": 0}, status
            )


def test_shared_custody_parser_keeps_current_binding_and_legacy_origins_separate() -> None:
    from boca_socios import host_boca_upgrade_adapters as adapters

    raw = module().observe(RUN, snapshot_reader=lambda _run: fixture_snapshot())
    custody = adapters.parse_custody_integrity(raw, observation_run_id=RUN)
    assert custody.installation_attempt == APPLY
    assert custody.installed_source_sha == SOURCE
    assert custody.control_directory_inode_sha256 == CONTROL
    assert custody.current_receipt == raw
    historical = adapters.parse_custody_integrity(
        evidence("retained1101.zip"), observation_run_id="43504739633"
    )
    assert historical.current_receipt is None
    assert historical.installation_attempt == "43217075287"


def test_legacy_transport_envelope_remains_byte_compatible() -> None:
    from test_host_boca_upgrade_retained_bridge import _auth

    proof, _, _, _ = _auth()
    assert b"current_receipt" not in proof


def test_stopped_state_is_allowed_only_for_receipted_original_worker() -> None:
    m = module()
    assert callable(getattr(m, "require_worker", None)), "missing exact-worker idle policy"
    value = fixture_snapshot(stopped=True)
    raw = m.observe(RUN, snapshot_reader=lambda _run: value)
    worker = value["pair"]["services"][1]
    m.require_worker(worker, worker["container_id"], raw)
    for cid, receipt in (("f" * 64, raw), (worker["container_id"], None)):
        with pytest.raises(m.CurrentRetainedNoGo):
            m.require_worker(worker, cid, receipt)
    for damage in ({"pid": 1}, {"exit_code": 1}, {"running": True}, {"status": "dead"}):
        with pytest.raises(m.CurrentRetainedNoGo):
            m.require_worker({**worker, **damage}, worker["container_id"], raw)


def test_runner_pair_projection_requires_current_stop_receipt_for_exited_worker() -> None:
    from boca_socios import host_boca_upgrade_observation_bridge as bridge

    raw = module().observe(RUN, snapshot_reader=lambda _run: fixture_snapshot(stopped=True))
    observed = current_pair(run="43590000001", stopped=True)
    with pytest.raises(bridge.UpgradeObservationNoGo):
        bridge._pair_projection(observed, "43590000001", "f" * 40)
    proof = bridge._pair_projection(observed, "43590000001", "f" * 40, current_retained=raw)
    assert proof["old_attempt_id"] == APPLY
