"""R252: strict current-base-only Boca Compose custody within one job lease.

All paths, source evidence and rootless identities are disposable synthetic
fixtures. These tests never enter an effectful pair-upgrade or contact Docker.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade_cli as cli
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_successor_integrations as integration
from boca_socios import host_cutover_stage as stage
from test_host_boca_successor_integrations import _inputs_with_proofs

BASE = b"services:\n  controller: {}\n"
OVERLAY = b"services:\n  browser-worker: {}\n"
SECCOMP = b'{"defaultAction":"SCMP_ACT_ERRNO"}\n'


def _prepared() -> tuple[cli.BoundSuccessorPreflight, journal.SuccessorPairJournal]:
    # Existing signed-pair synthetic receipt fixtures are intentionally
    # generated as UID10001; the subsequent disposable lease uses test UID.
    with patch.object(cleanup, "EXPECTED_UID", 10001):
        inputs = integration.verify_runner_bound_host_inputs(**_inputs_with_proofs())
    proof = cli.BoundSuccessorPreflight(
        inputs,
        BASE,
        OVERLAY,
        SECCOMP,
        hashlib.sha256(BASE).hexdigest(),
        hashlib.sha256(OVERLAY).hexdigest(),
        hashlib.sha256(SECCOMP).hexdigest(),
    )
    plan = inputs.plan
    witness = journal.FreshPairWitness(
        plan.observation_run_id,
        plan.old_attempt_id,
        plan.old_source_sha,
        plan.old_controller_id,
        plan.old_worker_id,
        plan.old_controller_image_id,
        plan.old_worker_image_id,
        inputs.custody.resources,
        inputs.custody.control_directory_inode_sha256,
    )
    durable = journal.SuccessorPairJournal(
        inputs.release, inputs.custody.resources, lambda _plan, _lease: witness
    )
    return proof, durable


@pytest.fixture
def owned_stage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "boca-stage"
    root.mkdir(mode=0o700)
    (root / "compose.beta.yaml").write_bytes(BASE)
    (root / "compose.beta.yaml").chmod(0o600)
    lease_dir = tmp_path / "boca-lease"
    lease_dir.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", root)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", lease_dir)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    return root


def test_unchanged_base_source_custody_uses_one_lease_before_journal(owned_stage: Path) -> None:
    proof, durable = _prepared()
    custody = integration.CurrentBaseOnlyStageCustody(proof, durable)
    sources = custody.sources()
    sources.validate()
    assert sources.original_compose_sha == proof.base_sha
    assert (sources.base, sources.overlay, sources.seccomp) == (BASE, OVERLAY, SECCOMP)
    assert not list(owned_stage.glob(".boca-pair-upgrade-*"))

    with cleanup.protected_boca_job_lease(proof.inputs.plan.attempt_id) as lease:
        custody.intent(proof.inputs.plan, lease)

    assert (owned_stage / f".boca-pair-upgrade-{proof.inputs.plan.attempt_id}.intent").is_file()
    assert (owned_stage / f".boca-pair-upgrade-{proof.inputs.plan.attempt_id}.evidence").is_file()


@pytest.mark.parametrize(
    "mutation", ("wrong_bytes", "symlink", "hardlink", "wrong_mode", "missing")
)
def test_current_base_mismatch_refuses_before_creating_journal(
    owned_stage: Path, mutation: str
) -> None:
    original = owned_stage / "compose.beta.yaml"
    if mutation == "wrong_bytes":
        original.write_bytes(b"different composed source\n")
    elif mutation == "symlink":
        original.rename(owned_stage / "original-safe")
        original.symlink_to(owned_stage / "original-safe")
    elif mutation == "hardlink":
        os.link(original, owned_stage / "unexpected-extra-link")
    elif mutation == "wrong_mode":
        original.chmod(0o666)
    else:
        original.unlink()
    proof, durable = _prepared()
    custody = integration.CurrentBaseOnlyStageCustody(proof, durable)
    with cleanup.protected_boca_job_lease(proof.inputs.plan.attempt_id) as lease:
        with pytest.raises(integration.SuccessorIntegrationNoGo):
            custody.intent(proof.inputs.plan, lease)
    assert not list(owned_stage.glob(".boca-pair-upgrade-*"))


def test_original_compose_changes_between_the_two_reads_never_creates_intent(
    monkeypatch: pytest.MonkeyPatch, owned_stage: Path
) -> None:
    proof, durable = _prepared()
    custody = integration.CurrentBaseOnlyStageCustody(proof, durable)
    original = stage._read_file
    count = 0

    def changed_between_reads(*args: object, **kwargs: object) -> object:
        nonlocal count
        value = original(*args, **kwargs)  # type: ignore[arg-type]
        count += 1
        if count == 1:
            (owned_stage / "compose.beta.yaml").write_bytes(b"changed after first read\n")
        return value

    monkeypatch.setattr(stage, "_read_file", changed_between_reads)
    with cleanup.protected_boca_job_lease(proof.inputs.plan.attempt_id) as lease:
        with pytest.raises(integration.SuccessorIntegrationNoGo):
            custody.intent(proof.inputs.plan, lease)
    assert count == 1
    assert not list(owned_stage.glob(".boca-pair-upgrade-*"))


def test_same_bytes_but_replaced_inode_between_reads_is_not_stable(
    monkeypatch: pytest.MonkeyPatch, owned_stage: Path
) -> None:
    proof, durable = _prepared()
    custody = integration.CurrentBaseOnlyStageCustody(proof, durable)
    original = stage._read_file
    count = 0

    def changed_inode(*args: object, **kwargs: object) -> object:
        nonlocal count
        value = original(*args, **kwargs)  # type: ignore[arg-type]
        count += 1
        if count == 1:
            replacement = owned_stage / "staged-replacement"
            replacement.write_bytes(BASE)
            replacement.chmod(0o600)
            os.replace(replacement, owned_stage / "compose.beta.yaml")
        return value

    monkeypatch.setattr(stage, "_read_file", changed_inode)
    with cleanup.protected_boca_job_lease(proof.inputs.plan.attempt_id) as lease:
        with pytest.raises(integration.SuccessorIntegrationNoGo):
            custody.intent(proof.inputs.plan, lease)
    assert count == 2
    assert not list(owned_stage.glob(".boca-pair-upgrade-*"))


def test_wrong_plan_cannot_touch_stage_or_create_journal(
    monkeypatch: pytest.MonkeyPatch, owned_stage: Path
) -> None:
    from dataclasses import replace

    proof, durable = _prepared()
    custody = integration.CurrentBaseOnlyStageCustody(proof, durable)
    monkeypatch.setattr(stage, "_root_fd", lambda: pytest.fail("wrong plan touched stage"))
    with cleanup.protected_boca_job_lease(proof.inputs.plan.attempt_id) as lease:
        with pytest.raises(integration.SuccessorIntegrationNoGo):
            custody.intent(replace(proof.inputs.plan, old_controller_id="9" * 64), lease)
    assert not list(owned_stage.glob(".boca-pair-upgrade-*"))


def test_same_attempt_cannot_recreate_intent(owned_stage: Path) -> None:
    proof, durable = _prepared()
    custody = integration.CurrentBaseOnlyStageCustody(proof, durable)
    with cleanup.protected_boca_job_lease(proof.inputs.plan.attempt_id) as lease:
        custody.intent(proof.inputs.plan, lease)
    with cleanup.protected_boca_job_lease(proof.inputs.plan.attempt_id) as lease:
        with pytest.raises((integration.SuccessorIntegrationNoGo, journal.SuccessorJournalNoGo)):
            custody.intent(proof.inputs.plan, lease)
