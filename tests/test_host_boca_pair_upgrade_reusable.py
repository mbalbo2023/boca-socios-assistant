"""Unwired reusable actor: retention is distinct from pair/release provenance."""

from __future__ import annotations

import importlib
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_stage as pair_stage
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_first_deploy as host

RUN = "44000000003"


def _module() -> Any:
    return importlib.import_module("boca_socios.host_boca_pair_upgrade_reusable")


def _plan() -> transaction.PairCoordinates:
    return transaction.PairCoordinates(
        RUN,
        "44000000001",
        "43217075287",
        "b" * 40,
        "c" * 64,
        "d" * 64,
        "sha256:" + "e" * 64,
        "sha256:" + "f" * 64,
        "a" * 40,
        "44000000002",
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64,
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64,
    )


def _pins() -> Any:
    return _module().RetainedResourcePins(
        "42806447101",
        "3" * 64,
        "43217075287",
        "4" * 64,
        "43217075287",
        "5" * 64,
    )


def _sources() -> pair_stage.PairSources:
    import hashlib

    contents = (b"base", b"overlay", b"seccomp")
    return pair_stage.PairSources(
        *contents,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(contents[0]).hexdigest(),
        overlay_sha=hashlib.sha256(contents[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(contents[2]).hexdigest(),
    )


@pytest.fixture(autouse=True)
def _lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    folder = tmp_path / "lease"
    folder.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", folder)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())


class Integrations:
    """Offline replacement for future authenticated runner/host adapters."""

    def __init__(self) -> None:
        self.current = _pins()
        self.release_calls = 0
        self.cleanup_result = "INDETERMINATE"

    def verify_release(self, plan: Any, sources: Any, lease: Any) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        self.release_calls += 1

    def retained_resources(self, plan: Any, lease: Any) -> Any:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        return self.current

    def final_cleanup(self, plan: Any, lease: Any) -> str:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        return self.cleanup_result


def _actor(integrations: Integrations | None = None) -> Any:
    return _module().ReusablePairUpgradeBackend(_sources(), _pins(), integrations)


@pytest.mark.parametrize("override_instance_capability", (False, True))
def test_unwired_actor_cannot_enter_transaction_or_write_intent(
    override_instance_capability: bool,
) -> None:
    actor = _actor(Integrations())
    if override_instance_capability:
        actor.requires_persistent_receipt = True
    effects: list[str] = []
    with pytest.raises(transaction.PairUpgradeError):
        transaction.run_pair_upgrade(
            _plan(),
            backend=actor,
            terminal_preflight=lambda *_: effects.append("intent"),
            commit_marker=lambda *_: effects.append("commit"),
            terminal_sink=lambda *_: effects.append("terminal"),
        )
    assert effects == []


def test_creator_origins_are_not_rebound_to_successor_plan_attempt_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Equality-contract checks only: neither call executes a transaction.
    actor = _actor(Integrations())
    plan = _plan()
    monkeypatch.setattr(host, "_browser_docker_ids", lambda: {"c" * 64, "d" * 64})
    with cleanup.protected_boca_job_lease(RUN) as lease:
        actor.verify_retained(plan, lease)
    later = replace(plan, attempt_id="44000000006", old_attempt_id=RUN)
    with cleanup.protected_boca_job_lease(later.attempt_id) as lease:
        actor.verify_retained(later, lease)
    assert actor.retained.ipc_creator_attempt == "42806447101"
    assert actor.retained.site_creator_attempt == "43217075287"


@pytest.mark.parametrize("field", ("ipc_inode_sha256", "site_inode_sha256", "egress_id"))
def test_retained_identity_drift_is_rejected_before_any_staging(field: str) -> None:
    integrations = Integrations()
    integrations.current = replace(integrations.current, **{field: "9" * 64})
    actor = _actor(integrations)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        with pytest.raises(_module().ReusableUpgradeNoGo):
            actor.verify_retained(_plan(), lease)


def test_missing_release_and_resource_integrations_fail_before_host_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    reads: list[str] = []
    monkeypatch.setattr(host, "_require_dedicated_identity", lambda: reads.append("identity"))
    with cleanup.protected_boca_job_lease(RUN) as lease:
        with pytest.raises(_module().ReusableUpgradeNoGo):
            actor.attest(_plan(), lease)
    assert reads == []


def test_stage_reuses_resources_without_create_relabel_or_remove(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    integrations = Integrations()
    actor = _actor(integrations)
    actor.state = "ATTESTED"
    calls: list[str] = []
    monkeypatch.setattr(actor, "_sqlite", lambda: None)
    monkeypatch.setattr(host, "_browser_docker_ids", lambda: {"c" * 64, "d" * 64})
    monkeypatch.setattr(pair_stage, "prepare", lambda *_: tmp_path)

    def model(*_args, **kwargs):
        assert kwargs["staged_overlay"] == actor.sources.overlay
        assert kwargs["overlay_sha"] == actor.sources.overlay_sha

    monkeypatch.setattr(host, "_browser_compose_model", model)
    monkeypatch.setattr(
        actor, "_compose_hash", lambda _p, role: "6" * 64 if role == "controller" else "7" * 64
    )
    monkeypatch.setattr(host, "_browser_pull_both", lambda *_: calls.append("pull_both"))
    monkeypatch.setattr(host, "_run", lambda *_a, **_k: pytest.fail("unexpected Docker mutation"))
    monkeypatch.setattr(
        host, "_cutover_create_browser_egress", lambda *_: pytest.fail("created retained egress")
    )
    monkeypatch.setattr(
        host, "_browser_create_site_config_volume", lambda *_: pytest.fail("created retained site")
    )
    with cleanup.protected_boca_job_lease(RUN) as lease:
        actor.stage(_plan(), lease)
    assert actor.state == "STAGED"
    assert calls == ["pull_both"]
    assert integrations.release_calls == 1


def test_compensation_never_deletes_retained_site_or_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor(Integrations())
    monkeypatch.setattr(
        host,
        "_cutover_compensate_site_config_volume",
        lambda *_: pytest.fail("deleted retained site"),
    )
    monkeypatch.setattr(
        host,
        "_cutover_compensate_browser_egress",
        lambda *_: pytest.fail("deleted retained network"),
    )
    actor._reclaim_stage_resources(_plan())


def test_created_old_worker_is_parkable_but_exited_historical_profile_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor(Integrations())
    actor.old = SimpleNamespace(
        pair=SimpleNamespace(controller_config_hash="6" * 64, worker_config_hash="7" * 64)
    )
    worker = {
        "Config": {"Labels": {"com.docker.compose.config-hash": "7" * 64}},
        "State": {"Running": False, "Status": "created", "Pid": 0, "ExitCode": 0},
        "HostConfig": {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
    }
    controller = {
        "Config": {"Labels": {"com.docker.compose.config-hash": "6" * 64}},
        "State": {"Running": True, "Status": "running", "Pid": 88},
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0}},
    }
    from boca_socios import host_boca_pair_upgrade_backend as historical

    monkeypatch.setattr(
        historical,
        "_full_old_record",
        lambda _p, _cid, *, role, **_k: controller if role == "controller" else worker,
    )
    actor._old_exact(_plan(), parked=False)
    worker["Config"]["Labels"]["com.docker.compose.config-hash"] = "8" * 64
    with pytest.raises(_module().ReusableUpgradeNoGo):
        actor._old_exact(_plan(), parked=False)
    worker["Config"]["Labels"]["com.docker.compose.config-hash"] = "7" * 64
    worker["State"]["Status"] = "exited"
    worker["State"]["ExitCode"] = 1
    with pytest.raises(_module().ReusableUpgradeNoGo):
        actor._old_exact(_plan(), parked=False)


def test_cleanup_cannot_change_accepted_binding_and_still_report_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boca_socios import host_on_demand_replace as binding
    from boca_socios import host_on_demand_service as service

    integrations = Integrations()
    integrations.cleanup_result = "ACCEPT"
    actor = _actor(integrations)
    actor.state = "RETIRED"
    actor.new = object()
    active = {"binding": actor.new}
    monkeypatch.setattr(actor, "_sqlite", lambda: None)
    monkeypatch.setattr(binding, "_new_pair_only", lambda _new: None)
    monkeypatch.setattr(service, "read_installed_binding", lambda _lease: active["binding"])

    def cleanup_changes_binding(_plan: Any, _lease: Any) -> str:
        active["binding"] = object()
        return "ACCEPT"

    integrations.final_cleanup = cleanup_changes_binding
    with cleanup.protected_boca_job_lease(RUN) as lease:
        result = actor.finalize(
            _plan(),
            commit_started=True,
            controller_id="1" * 64,
            worker_id="2" * 64,
            lease=lease,
        )
    assert result == "INDETERMINATE"


@pytest.mark.parametrize("result", ("INDETERMINATE", "NO_GO", "not_a_receipt", "ACCEPT"))
def test_cleanup_outcome_is_required_for_final_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    result: str,
) -> None:
    from boca_socios import host_on_demand_replace as binding
    from boca_socios import host_on_demand_service as service

    integrations = Integrations()
    integrations.cleanup_result = result
    actor = _actor(integrations)
    actor.state = "RETIRED"
    actor.new = object()
    monkeypatch.setattr(actor, "_sqlite", lambda: None)
    monkeypatch.setattr(binding, "_new_pair_only", lambda _new: None)
    monkeypatch.setattr(service, "read_installed_binding", lambda _lease: actor.new)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        found = actor.finalize(
            _plan(),
            commit_started=True,
            controller_id="1" * 64,
            worker_id="2" * 64,
            lease=lease,
        )
    assert found == (result if result in ("ACCEPT", "NO_GO") else "INDETERMINATE")


def test_release_refusal_happens_before_stage_files_or_image_pulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integrations = Integrations()
    actor = _actor(integrations)
    actor.state = "ATTESTED"

    def reject_release(*_args: Any) -> None:
        raise ValueError("unverified dual release")

    integrations.verify_release = reject_release
    monkeypatch.setattr(pair_stage, "prepare", lambda *_: pytest.fail("staged before provenance"))
    monkeypatch.setattr(
        host, "_browser_pull_both", lambda *_: pytest.fail("pulled before provenance")
    )
    with cleanup.protected_boca_job_lease(RUN) as lease:
        with pytest.raises(ValueError, match="unverified dual release"):
            actor.stage(_plan(), lease)


def test_unverifiable_final_state_preserves_resources_without_success_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integrations = Integrations()
    actor = _actor(integrations)
    calls: list[str] = []

    def success_only_cleanup(_plan: Any, _lease: Any) -> str:
        calls.append("unsafe_success_cleanup_attempt")
        return "INDETERMINATE"

    integrations.final_cleanup = success_only_cleanup
    monkeypatch.setattr(actor, "_sqlite", lambda: None)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        result = actor.finalize(
            _plan(),
            commit_started=True,
            controller_id=None,
            worker_id=None,
            lease=lease,
        )
    assert result == "INDETERMINATE"
    assert calls == []


def test_precommit_restored_old_pair_cannot_invoke_success_cleanup_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch an unsafe SUCCESS cleanup after a failed/precommit upgrade."""
    from boca_socios import host_on_demand_service as service

    integrations = Integrations()
    effects: list[str] = []

    def potentially_destructive_success_cleanup(_plan: Any, _lease: Any) -> str:
        effects.append("success_cleanup_entered")
        return "ACCEPT"

    integrations.final_cleanup = potentially_destructive_success_cleanup
    actor = _actor(integrations)
    actor.state = "RESTORED"
    actor.old = object()
    monkeypatch.setattr(actor, "_sqlite", lambda: None)
    monkeypatch.setattr(actor, "_old_exact", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "read_installed_binding", lambda _lease: actor.old)

    with cleanup.protected_boca_job_lease(RUN) as lease:
        result = actor.finalize(
            _plan(),
            commit_started=False,
            controller_id=None,
            worker_id=None,
            lease=lease,
        )
    assert result == "NO_GO"
    assert effects == []


def test_postcommit_unverified_pair_cannot_invoke_success_cleanup_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch deletes attempted while serving-pair identity is unknown."""
    from boca_socios import host_on_demand_service as service

    integrations = Integrations()
    effects: list[str] = []

    def potentially_destructive_success_cleanup(_plan: Any, _lease: Any) -> str:
        effects.append("success_cleanup_entered")
        return "ACCEPT"

    integrations.final_cleanup = potentially_destructive_success_cleanup
    actor = _actor(integrations)
    actor.state = "RETIRED"
    actor.new = object()
    monkeypatch.setattr(actor, "_sqlite", lambda: None)
    monkeypatch.setattr(service, "read_installed_binding", lambda _lease: object())

    with cleanup.protected_boca_job_lease(RUN) as lease:
        result = actor.finalize(
            _plan(),
            commit_started=True,
            controller_id="1" * 64,
            worker_id="2" * 64,
            lease=lease,
        )
    assert result == "INDETERMINATE"
    assert effects == []


def test_retained_drift_blocks_every_noninitial_effect_boundary() -> None:
    integrations = Integrations()
    actor = _actor(integrations)
    actor.state = "STAGED"
    integrations.current = replace(integrations.current, egress_id="9" * 64)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        with pytest.raises(_module().ReusableUpgradeNoGo):
            actor._guard(_plan(), lease, "STAGED")


def test_binding_completion_rechecks_retained_pins_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boca_socios import host_boca_pair_upgrade_backend as historical

    integrations = Integrations()
    actor = _actor(integrations)

    def replace_then_drift(*_args: Any) -> None:
        integrations.current = replace(integrations.current, site_inode_sha256="9" * 64)

    monkeypatch.setattr(
        historical.RootlessPairUpgradeBackend, "replace_binding", replace_then_drift
    )
    with cleanup.protected_boca_job_lease(RUN) as lease:
        with pytest.raises(_module().ReusableUpgradeNoGo):
            actor.replace_binding(_plan(), "1" * 64, "2" * 64, lease)


def test_resource_drift_cannot_reactivate_old_pair_during_compensation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boca_socios import host_boca_pair_upgrade_backend as historical

    integrations = Integrations()
    actor = _actor(integrations)
    integrations.current = replace(integrations.current, egress_id="9" * 64)
    effects: list[str] = []

    def historical_restore(*_args: Any) -> bool:
        effects.append("restore_old_controller")
        return True

    monkeypatch.setattr(historical.RootlessPairUpgradeBackend, "restore_old", historical_restore)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        assert actor.restore_old(_plan(), lease) is False
    assert effects == []
