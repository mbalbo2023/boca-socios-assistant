"""R294 activates only the exact reviewed overlay, never an observed Env alternative."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios.deploy_contract import ContractError, validate_beta_browser_contract
from test_beta_browser_deploy_contract import BROWSER_IMAGE, ORIGIN, OWNER, SECCOMP, on_demand_model
from test_deploy_contract import IMAGE
from test_host_browser_ipc_install import (
    ATTEMPT,
    CONTROLLER_ID,
    SECCOMP_SHA,
    SOURCE,
    WORKER_ID,
    controller_record,
    worker_record,
)

ROOT = Path(__file__).resolve().parents[1]
AUTO_ENV = (
    b'      BOCA_BROWSER_EXECUTOR: automatic-observation\n      BOCA_BROWSER_OBSERVE_MODE: "off"\n'
)


def overlay():
    raw = (ROOT / "compose.beta.browser.yaml").read_bytes()
    return {"staged_overlay": raw, "overlay_sha": hashlib.sha256(raw).hexdigest()}


def test_overlay_activates_only_worker_and_keeps_historical_public_observer_stopped():
    raw = overlay()["staged_overlay"]
    assert AUTO_ENV in raw
    assert (
        hashlib.sha256((ROOT / "compose.beta.yaml").read_bytes()).hexdigest()
        == "b9e9465d6ec8e484b615d7bd65aab5a3c150d34a9893ad181167d2099893d811"
    )
    assert host._browser_worker_profile(**overlay()) == "automatic-observation"
    old = raw.replace(AUTO_ENV, b"")
    assert (
        host._browser_worker_profile(
            staged_overlay=old, overlay_sha=hashlib.sha256(old).hexdigest()
        )
        == "off"
    )
    legacy = host._cutover_worker_create_argv(BROWSER_IMAGE, SOURCE, ATTEMPT, "c" * 64)
    assert "BOCA_BROWSER_EXECUTOR=automatic-observation" not in legacy
    new = host._cutover_worker_create_argv(
        BROWSER_IMAGE, SOURCE, ATTEMPT, "c" * 64, on_demand=True, **overlay()
    )
    assert "BOCA_BROWSER_EXECUTOR=automatic-observation" in new
    assert "BOCA_BROWSER_OBSERVE_MODE=off" in new
    assert "BOCA_OBSERVER_STOP=1" in new and "BOCA_OBSERVER_STOP=0" not in new


@pytest.mark.parametrize("change", ["missing_bytes", "missing_hash", "wrong_hash", "changed_bytes"])
def test_worker_profile_requires_exact_overlay_proof(change):
    proof = overlay()
    if change == "missing_bytes":
        proof["staged_overlay"] = None
    elif change == "missing_hash":
        proof["overlay_sha"] = None
    elif change == "wrong_hash":
        proof["overlay_sha"] = "0" * 64
    else:
        proof["staged_overlay"] += b"# unreviewed\n"
        proof["overlay_sha"] = hashlib.sha256(proof["staged_overlay"]).hexdigest()
    with pytest.raises(host.PreflightError):
        host._cutover_worker_create_argv(
            BROWSER_IMAGE, SOURCE, ATTEMPT, "c" * 64, on_demand=True, **proof
        )


def test_new_worker_cannot_start_outside_on_demand_profile():
    with pytest.raises(host.PreflightError):
        host._cutover_worker_create_argv(BROWSER_IMAGE, SOURCE, ATTEMPT, "c" * 64, **overlay())


@pytest.mark.parametrize("running", [False, True])
def test_worker_postflight_uses_reviewed_profile_for_running_and_stopped_workers(
    monkeypatch, running
):
    record = worker_record()
    record["State"]["Running"] = running
    record["NetworkSettings"]["Networks"][host.BROWSER_EGRESS_BRIDGE]["IPAddress"] = (
        "172.27.0.2" if running else ""
    )
    record["Config"]["Env"] += [
        "BOCA_BROWSER_EXECUTOR=automatic-observation",
        "BOCA_BROWSER_OBSERVE_MODE=off",
    ]
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(host, "_browser_effective_seccomp_options", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(host, "_browser_worker_probe", lambda _: None)
    with pytest.raises(host.PreflightError):
        host._browser_worker_postflight(
            WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA, running=running
        )
    host._browser_worker_postflight(
        WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA, running=running, **overlay()
    )
    record["Config"]["Env"].remove("BOCA_BROWSER_EXECUTOR=automatic-observation")
    with pytest.raises(host.PreflightError):
        host._browser_worker_postflight(
            WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA, running=running, **overlay()
        )


def test_compose_contract_selects_automatic_expectation_from_overlay_not_environment():
    model = on_demand_model()
    model["services"]["browser-worker"]["environment"].update(
        BOCA_BROWSER_EXECUTOR="automatic-observation", BOCA_BROWSER_OBSERVE_MODE="off"
    )
    args = (model, IMAGE, BROWSER_IMAGE, ORIGIN, OWNER, SECCOMP, "123456")
    with pytest.raises(ContractError):
        validate_beta_browser_contract(*args)
    validate_beta_browser_contract(*args, **overlay())
    model["services"]["browser-worker"]["environment"]["BOCA_BROWSER_EXECUTOR"] = "off"
    with pytest.raises(ContractError):
        validate_beta_browser_contract(*args, **overlay())


def test_new_candidate_argv_receives_authenticated_source_without_base_compose_change():
    command = host._cutover_candidate_create_argv(IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER, "c" * 64)
    assert f"BOCA_SOURCE_SHA={SOURCE}" in command


def test_controller_source_is_required_by_new_profile_and_never_accepts_mismatch(monkeypatch):
    record = controller_record()
    values = dict(entry.split("=", 1) for entry in record["Config"]["Env"])
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(host, "_validate_boca_network", lambda *_args, **_kwargs: None)
    args = (
        CONTROLLER_ID,
        record["Config"]["Image"],
        SOURCE,
        ATTEMPT,
        values["BOCA_PANEL_ORIGIN"],
        values["BOCA_OWNER_SUBJECT"],
    )
    host._browser_controller_postflight(*args, verify_runtime=False)
    with pytest.raises(host.PreflightError, match="source environment"):
        host._browser_controller_postflight(*args, verify_runtime=False, **overlay())
    record["Config"]["Env"].append(f"BOCA_SOURCE_SHA={SOURCE}")
    host._browser_controller_postflight(*args, verify_runtime=False, **overlay())
    record["Config"]["Env"][-1] = "BOCA_SOURCE_SHA=" + "f" * 40
    for proof in ({}, overlay()):
        with pytest.raises(host.PreflightError, match="source environment"):
            host._browser_controller_postflight(*args, verify_runtime=False, **proof)
