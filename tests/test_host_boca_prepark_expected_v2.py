"""R255 host-read-only pre-PARK seed and later exact pair expectation.

All external rootless observations are synthetic fixtures. No Docker,
controller, privileged Actions or browser is actually contacted here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_postflight_sources_v2 as sources_v2
from boca_socios import host_boca_prepark_expected_v2 as prepark
from boca_socios import host_boca_successor_integrations as integrations
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_postflight_runtime as runtime
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_repeatable_journal import FreshPairWitness
from boca_socios.host_boca_upgrade_cleanup_runtime import DurableFinalCleanupReceipt
from test_host_boca_successor_integrations import _inputs_with_proofs
from test_host_boca_upgrade_postflight import _expected, _pair_bytes
from test_host_boca_upgrade_postflight_runtime import _installed_binding


@pytest.fixture
def context(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]]:
    reference = _expected()
    genuine = integrations.verify_runner_bound_host_inputs(**_inputs_with_proofs())
    bound = replace(genuine, plan=reference.plan, release=reference.release)
    lease = cleanup.BocaJobLease(bound.plan.attempt_id, -1, os.getpid(), True)
    operations: list[str] = []

    def held(found: cleanup.BocaJobLease, attempt: str) -> None:
        assert found is lease and attempt == bound.plan.attempt_id
        operations.append("lease")

    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", held)
    witness = FreshPairWitness(
        bound.plan.observation_run_id,
        bound.plan.old_attempt_id,
        bound.plan.old_source_sha,
        bound.plan.old_controller_id,
        bound.plan.old_worker_id,
        bound.plan.old_controller_image_id,
        bound.plan.old_worker_image_id,
        bound.custody.resources,
        "f" * 64,
    )

    def current_capture(self: physical.SuccessorCurrentPairCapture, *_: object) -> FreshPairWitness:
        operations.append("old_pair")
        return witness

    monkeypatch.setattr(physical.SuccessorCurrentPairCapture, "__call__", current_capture)
    monkeypatch.setattr(
        runtime, "_read_rootless_identity", lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID)
    )
    monkeypatch.setattr(host, "_checked_docker_storage_dir", lambda: runtime._ROOT)
    for name in ("_validate_data_volume", "_validate_key_volume", "_validate_owner_volume"):
        monkeypatch.setattr(host, name, lambda n=name: operations.append(n))
    monkeypatch.setattr(
        sources_v2,
        "capture_structural_storage_fingerprints",
        lambda: operations.append("storage") or reference.storage_before,
    )
    monkeypatch.setattr(
        runtime,
        "capture_storage_fingerprints",
        lambda: pytest.fail("legacy size/mtime-sensitive V1 storage must not be used"),
    )

    def rootless_docker(*args: str) -> str:
        assert args[:3] == ("exec", "--user", "10001:10001")
        assert args[3] == bound.plan.old_controller_id
        assert args[-2] == "-c" and "SiteUrlSettingsStore" in args[-1]
        operations.append("site")
        return "BOCA_SITE_URL_SHA256 " + reference.site_url_fingerprint + "\n"

    monkeypatch.setattr(cleanup, "_docker", rootless_docker)
    return bound, lease, operations


def test_prepark_real_reader_paths_are_double_attested_before_any_park(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
) -> None:
    bound, lease, operations = context
    seed = prepark.capture_prepark_expected_seed(bound, lease)
    assert seed.plan is bound.plan
    assert seed.lease is lease
    assert seed.storage_before == _expected().storage_before
    assert seed.site_url_fingerprint == _expected().site_url_fingerprint
    assert seed.site_url_state == "ATTESTED"
    assert seed.apply_authorized is False
    assert seed.terminal_accept_authorized is False
    assert operations.count("old_pair") == 2
    assert operations.count("storage") == 2
    assert operations.count("site") == 2
    assert operations.count("_validate_data_volume") == 2
    assert operations.count("_validate_key_volume") == 2
    assert operations.count("_validate_owner_volume") == 2
    assert operations.index("old_pair") < operations.index("site")
    assert operations[-1] == "lease"


@pytest.mark.parametrize("fault", ("unsafe_url_output", "storage_drift", "old_pair_drift"))
def test_prepark_refuses_missing_or_changed_physical_evidence(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    bound, lease, _ = context
    if fault == "unsafe_url_output":
        monkeypatch.setattr(cleanup, "_docker", lambda *_: "BOCA_SITE_URL_INVALID\n")
    elif fault == "storage_drift":
        snapshots = iter(
            (
                _expected().storage_before,
                replace(_expected().storage_before, key_inode_sha256="0" * 64),
            )
        )
        monkeypatch.setattr(
            sources_v2, "capture_structural_storage_fingerprints", lambda: next(snapshots)
        )
    else:
        actual = bound.custody.resources
        witness = FreshPairWitness(
            bound.plan.observation_run_id,
            bound.plan.old_attempt_id,
            bound.plan.old_source_sha,
            bound.plan.old_controller_id,
            bound.plan.old_worker_id,
            bound.plan.old_controller_image_id,
            bound.plan.old_worker_image_id,
            actual,
            "f" * 64,
        )
        swapped = replace(witness, controller_id="8" * 64)
        iterator = iter((witness, swapped))
        monkeypatch.setattr(
            physical.SuccessorCurrentPairCapture, "__call__", lambda *_: next(iterator)
        )
    with pytest.raises(prepark.PreParkExpectedNoGo, match="NO_GO"):
        prepark.capture_prepark_expected_seed(bound, lease)


def test_missing_saved_url_is_distinct_and_does_not_block_prepark_readonly_custody(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, lease, events = context
    monkeypatch.setattr(cleanup, "_docker", lambda *_: "BOCA_SITE_URL_UNVERIFIED\n")
    seed = prepark.capture_prepark_expected_seed(bound, lease)
    assert seed.site_url_state == "NOT_CONFIGURED"
    assert seed.site_url_fingerprint is None
    assert seed.apply_authorized is False
    assert seed.terminal_accept_authorized is False
    assert events.count("old_pair") == 2
    assert events.count("storage") == 2
    # An absent SITE_URL cannot be turned into a digest-dependent BETA proof.
    with pytest.raises(prepark.PreParkExpectedNoGo):
        seed.expected_after_cleanup(object.__new__(successor.OneShotFinalCleanupBridge), lease)


def test_prepark_rejects_site_state_drift_between_two_readonly_snapshots(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, lease, _ = context
    replies = iter(("BOCA_SITE_URL_UNVERIFIED\n", "BOCA_SITE_URL_SHA256 " + "a" * 64 + "\n"))
    monkeypatch.setattr(cleanup, "_docker", lambda *_: next(replies))
    with pytest.raises(prepark.PreParkExpectedNoGo):
        prepark.capture_prepark_expected_seed(bound, lease)


def test_finish_expected_derives_new_cids_and_image_ids_from_live_pair_only(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, lease, _ = context
    seed = prepark.capture_prepark_expected_seed(bound, lease)
    genuine = _expected()
    raw = genuine.cleanup_receipt
    proof = DurableFinalCleanupReceipt(
        bound.plan.attempt_id, "ACCEPT", raw, hashlib.sha256(raw).hexdigest(), "a" * 64
    )
    monkeypatch.setattr(
        successor.OneShotFinalCleanupBridge, "completed_final_cleanup", lambda *_: proof
    )
    monkeypatch.setattr(pair, "observe", lambda *_: _pair_bytes())
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed_binding(genuine))
    final_bridge = object.__new__(successor.OneShotFinalCleanupBridge)
    expected = seed.expected_after_cleanup(final_bridge, lease)
    assert expected.plan is bound.plan
    assert expected.controller_id == genuine.controller_id
    assert expected.worker_id == genuine.worker_id
    assert expected.controller_image_id == genuine.controller_image_id
    assert expected.worker_image_id == genuine.worker_image_id
    assert expected.storage_before == seed.storage_before
    assert expected.site_url_fingerprint == seed.site_url_fingerprint


def test_finish_expected_preserves_genuinely_missing_old_site_url_without_fabricating_digest(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, lease, _ = context
    monkeypatch.setattr(cleanup, "_docker", lambda *_: "BOCA_SITE_URL_UNVERIFIED\n")
    seed = prepark.capture_prepark_expected_seed(bound, lease)
    assert seed.site_url_state == "NOT_CONFIGURED"
    assert seed.site_url_fingerprint is None
    genuine = _expected()
    raw = genuine.cleanup_receipt
    proof = DurableFinalCleanupReceipt(
        bound.plan.attempt_id, "ACCEPT", raw, hashlib.sha256(raw).hexdigest(), "a" * 64
    )
    monkeypatch.setattr(
        successor.OneShotFinalCleanupBridge, "completed_final_cleanup", lambda *_: proof
    )
    monkeypatch.setattr(pair, "observe", lambda *_: _pair_bytes())
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: _installed_binding(genuine))
    expected = seed.expected_after_cleanup(
        object.__new__(successor.OneShotFinalCleanupBridge), lease
    )
    assert expected.plan is bound.plan
    assert expected.site_url_fingerprint is None
    assert expected.storage_before == seed.storage_before


@pytest.mark.parametrize("missing", [False, True])
def test_precommit_candidate_site_requires_stable_real_saved_and_mirror_probes(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    missing: bool,
) -> None:
    bound, lease, events = context
    genuine = _expected()
    if missing:
        monkeypatch.setattr(cleanup, "_docker", lambda *_: "BOCA_SITE_URL_UNVERIFIED\n")
    seed = prepark.capture_prepark_expected_seed(bound, lease)
    observed: list[str] = []

    def candidate_docker(*args: str) -> str:
        assert args[:4] == ("exec", "--user", "10001:10001", genuine.controller_id)
        assert args[-2] == "-c"
        observed.append("saved" if "SiteUrlSettingsStore" in args[-1] else "mirror")
        return (
            "BOCA_SITE_URL_UNVERIFIED\n"
            if missing
            else "BOCA_SITE_URL_SHA256 " + genuine.site_url_fingerprint + "\n"
        )

    monkeypatch.setattr(cleanup, "_docker", candidate_docker)
    monkeypatch.setattr(
        cleanup,
        "_ids",
        lambda *_: [
            bound.plan.old_controller_id,
            bound.plan.old_worker_id,
            genuine.controller_id,
            genuine.worker_id,
        ],
    )
    monkeypatch.setattr(
        service,
        "read_installed_binding",
        lambda _: events.append("new_binding") or _installed_binding(genuine),
    )
    assert (
        prepark.attest_precommit_candidate_site_state(
            bound.plan, genuine.controller_id, genuine.worker_id, lease, seed
        )
        is None
    )
    assert observed == ["saved", "mirror", "saved", "mirror"]
    assert events.count("new_binding") >= 4


@pytest.mark.parametrize(
    "fault", ["different_mirror", "drift", "wrong_binding", "wrong_lease", "fifth_cid"]
)
def test_precommit_candidate_site_fails_closed_before_marker_on_ambiguity(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    bound, lease, _ = context
    seed = prepark.capture_prepark_expected_seed(bound, lease)
    genuine = _expected()
    outputs = ["BOCA_SITE_URL_SHA256 " + genuine.site_url_fingerprint + "\n"] * 4
    if fault == "different_mirror":
        outputs[1] = "BOCA_SITE_URL_UNVERIFIED\n"
    elif fault == "drift":
        outputs[3] = "BOCA_SITE_URL_SHA256 " + "f" * 64 + "\n"
    replies = iter(outputs)
    monkeypatch.setattr(cleanup, "_docker", lambda *_: next(replies))
    monkeypatch.setattr(
        cleanup,
        "_ids",
        lambda *_: [
            bound.plan.old_controller_id,
            bound.plan.old_worker_id,
            genuine.controller_id,
            genuine.worker_id,
            *(["a" * 64] if fault == "fifth_cid" else []),
        ],
    )
    binding = _installed_binding(genuine)
    if fault == "wrong_binding":
        binding = replace(binding, controller_id="f" * 64)
    monkeypatch.setattr(service, "read_installed_binding", lambda *_: binding)
    selected_lease = (
        cleanup.BocaJobLease(lease.attempt_id, -1, os.getpid(), True)
        if fault == "wrong_lease"
        else lease
    )
    with pytest.raises(prepark.PreParkExpectedNoGo):
        prepark.attest_precommit_candidate_site_state(
            bound.plan, genuine.controller_id, genuine.worker_id, selected_lease, seed
        )


def test_finish_expected_rejects_wrong_lease_and_changed_current_pair(
    context: tuple[integrations.BoundSuccessorInputs, cleanup.BocaJobLease, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound, lease, _ = context
    seed = prepark.capture_prepark_expected_seed(bound, lease)
    wrong_lease = cleanup.BocaJobLease(lease.attempt_id, -1, os.getpid(), True)
    with pytest.raises(prepark.PreParkExpectedNoGo):
        seed.expected_after_cleanup(
            object.__new__(successor.OneShotFinalCleanupBridge), wrong_lease
        )

    monkeypatch.setattr(pair, "observe", lambda *_: _pair_bytes())
    monkeypatch.setattr(
        service, "read_installed_binding", lambda *_: _installed_binding(_expected())
    )
    changed = json.loads(_expected().cleanup_receipt)
    changed["protected_pair"]["controller"]["id"] = "1" * 64
    raw = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
    proof = DurableFinalCleanupReceipt(
        lease.attempt_id, "ACCEPT", raw, hashlib.sha256(raw).hexdigest(), "a" * 64
    )
    monkeypatch.setattr(
        successor.OneShotFinalCleanupBridge, "completed_final_cleanup", lambda *_: proof
    )
    # If the official cleanup is tied to a different pair, it is NO_GO.
    with pytest.raises(prepark.PreParkExpectedNoGo):
        seed.expected_after_cleanup(object.__new__(successor.OneShotFinalCleanupBridge), lease)
