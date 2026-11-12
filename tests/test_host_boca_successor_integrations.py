"""R247: only an authenticated, bound successor can reach the inert actor.

The release and GitHub observation fixtures are synthetic. No Docker,
workflow, member session or real ticket endpoint is touched.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_successor_integrations as successor
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_observation_bridge as observation
from boca_socios.host_boca_pair_stage import PairSources
from test_host_boca_current_pair_v2 import HISTORICAL_SEED, _authenticate, _inputs


def _canonical(value: dict[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _inputs_with_proofs(step: int = 1) -> dict[str, object]:
    plan, _old_release, pair_raw, _github = _inputs(step=step)
    controller_manifest = _canonical(
        {
            "image_ref": plan.controller_ref,
            "source_sha": plan.new_source_sha,
            "release_run_id": plan.release_run_id,
        }
    )
    paired_manifest = _canonical(
        {
            "browser_digest": plan.worker_ref,
            "controller_digest": plan.controller_ref,
            "source_sha": plan.new_source_sha,
            "run_id": plan.release_run_id,
        }
    )
    release_proof = _canonical(
        {
            "schema": 1,
            "source_sha": plan.new_source_sha,
            "release_run_id": plan.release_run_id,
            "controller_ref": plan.controller_ref,
            "worker_ref": plan.worker_ref,
            "controller_manifest_sha256": hashlib.sha256(controller_manifest).hexdigest(),
            "paired_manifest_sha256": hashlib.sha256(paired_manifest).hexdigest(),
        }
    )
    observation_proof = observation._pair_projection(
        pair_raw, plan.observation_run_id, plan.new_source_sha
    )
    observation_proof.update(
        {"apply_attempt_id": plan.attempt_id, "release_run_id": plan.release_run_id}
    )
    return {
        "attempt_id": plan.attempt_id,
        "source_sha": plan.new_source_sha,
        "controller_ref": plan.controller_ref,
        "worker_ref": plan.worker_ref,
        "release_run_id": plan.release_run_id,
        "observation_run_id": plan.observation_run_id,
        "release_proof": release_proof,
        "controller_manifest": controller_manifest,
        "paired_manifest": paired_manifest,
        "observation_proof": _canonical(observation_proof),
        "observation_receipt": pair_raw,
        "retained_receipt": HISTORICAL_SEED,
        "current_pair_v2": _authenticate(step=step),
    }


@pytest.mark.parametrize("step", (1, 2))
def test_successor_binds_dynamic_previous_pair_to_original_r188_resource_creators(
    step: int,
) -> None:
    result = successor.verify_runner_bound_host_inputs(**_inputs_with_proofs(step=step))
    assert result.plan.old_attempt_id == ("44100000011" if step == 1 else "44300000011")
    assert result.plan.new_source_sha == ("c" * 40 if step == 1 else "d" * 40)
    assert result.retained.ipc_creator_attempt == result.custody.resources.ipc_creator_attempt
    assert result.retained.site_creator_attempt == result.custody.resources.site_creator_attempt
    assert result.retained.egress_creator_attempt == result.custody.resources.egress_creator_attempt
    assert result.apply_authorized is False


@pytest.mark.parametrize("mutation", ("missing_v2", "old_v2", "wrong_observation", "wrong_r188"))
def test_successor_rejects_missing_or_cross_run_physical_provenance(mutation: str) -> None:
    payload = _inputs_with_proofs(step=2)
    if mutation == "missing_v2":
        payload["current_pair_v2"] = b""
    elif mutation == "old_v2":
        payload["current_pair_v2"] = _authenticate(step=1)
    elif mutation == "wrong_observation":
        payload["observation_receipt"] = _inputs(step=1)[2]
    else:
        payload["retained_receipt"] = payload["retained_receipt"] + b" "
    with pytest.raises(successor.SuccessorIntegrationNoGo):
        successor.verify_runner_bound_host_inputs(**payload)


def test_successor_bundle_integrity_does_not_grant_effectful_authority() -> None:
    inputs = successor.verify_runner_bound_host_inputs(**_inputs_with_proofs())
    with pytest.raises(successor.SuccessorIntegrationNoGo):
        successor.prepare_effectful_successor(inputs)


def test_successor_rejects_arbitrary_forged_release_coordinates() -> None:
    payload = _inputs_with_proofs()
    payload["worker_ref"] = payload["controller_ref"]
    with pytest.raises(successor.SuccessorIntegrationNoGo):
        successor.verify_runner_bound_host_inputs(**payload)


def test_successor_uses_existing_one_lease_engine_and_refuses_before_host_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def prohibited_lease(_attempt: str) -> None:
        pytest.fail("interlocked successor acquired a host lease or touched Docker")

    monkeypatch.setattr(transaction, "protected_boca_job_lease", prohibited_lease)
    contents = (b"base", b"overlay", b"seccomp")
    sources = PairSources(
        *contents,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(contents[0]).hexdigest(),
        overlay_sha=hashlib.sha256(contents[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(contents[2]).hexdigest(),
    )
    bound = successor.verify_runner_bound_host_inputs(**_inputs_with_proofs())
    prepared = successor.prepare_effectful_successor(bound, sources=sources)
    assert prepared.backend.requires_persistent_receipt is False
    assert isinstance(prepared.journal.capture, physical.SuccessorCurrentPairCapture)
    assert isinstance(prepared.backend.integrations, physical.PhysicalSuccessorIntegrations)
    assert prepared.backend.integrations.backend is prepared.backend
    with pytest.raises(transaction.PairUpgradeError, match="protected terminal"):
        prepared.execute()
