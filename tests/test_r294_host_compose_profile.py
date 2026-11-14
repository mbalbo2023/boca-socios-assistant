"""Actual host Compose validator must consume the authenticated stage profile."""

import json
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from test_beta_browser_deploy_contract import ATTEMPT, BROWSER_IMAGE, ORIGIN, OWNER, on_demand_model
from test_deploy_contract import IMAGE
from test_r294_automatic_worker_profile import overlay


def call(monkeypatch, *, automatic, proof):
    stage = host.ROOT / f"cutover-a-{ATTEMPT}"
    model = on_demand_model()
    worker = model["services"]["browser-worker"]
    worker["security_opt"][1] = f"seccomp={stage / host.BROWSER_SECCOMP.name}"
    if automatic:
        worker["environment"].update(
            BOCA_BROWSER_EXECUTOR="automatic-observation", BOCA_BROWSER_OBSERVE_MODE="off"
        )
    raw = json.dumps(model)
    monkeypatch.setattr(host, "_run", lambda *_args, **_kwargs: raw)
    return host._browser_compose_model(
        IMAGE,
        ORIGIN,
        OWNER,
        BROWSER_IMAGE,
        ATTEMPT,
        base_file=stage / host.BETA_COMPOSE.name,
        overlay_file=stage / host.BROWSER_COMPOSE.name,
        seccomp_file=stage / host.BROWSER_SECCOMP.name,
        control_directory=Path("/home/boca-deploy/.boca-on-demand/socket"),
        **proof,
    )


def test_host_resolved_automatic_model_accepts_only_the_authenticated_overlay(monkeypatch):
    assert call(monkeypatch, automatic=True, proof=overlay())
    assert call(monkeypatch, automatic=False, proof={})


@pytest.mark.parametrize("automatic,proof", ((True, {}), (False, "new"), (True, "wrong")))
def test_host_does_not_infer_profile_from_observed_worker_environment(
    monkeypatch, automatic, proof
):
    if proof == "new":
        proof = overlay()
    elif proof == "wrong":
        proof = {**overlay(), "overlay_sha": "f" * 64}
    with pytest.raises(host.PreflightError):
        call(monkeypatch, automatic=automatic, proof=proof)
