"""R179 guarded host actor tests: fake Boca-only IO, no Docker/systemd/socket."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_stage as stage_pair
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_backend as backend
from boca_socios import host_cutover_stage as stage
from boca_socios import host_first_deploy as host

RUN = "43080012345"


def _plan() -> transaction.PairCoordinates:
    return transaction.PairCoordinates(
        attempt_id=RUN,
        observation_run_id="43066120206",
        old_attempt_id="42806447101",
        old_source_sha="03df9a14bdd78cf768386a865876fed9d5656911",
        old_controller_id="c" * 64,
        old_worker_id="d" * 64,
        old_controller_image_id="sha256:" + "e" * 64,
        old_worker_image_id="sha256:" + "f" * 64,
        new_source_sha="a" * 40,
        release_run_id="43090012345",
        controller_ref="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64,
        worker_ref="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64,
    )


def _sources() -> stage_pair.PairSources:
    values = (b"base", b"overlay", b"seccomp")
    return stage_pair.PairSources(
        *values,
        original_compose_sha=hashlib.sha256(b"legacy compose").hexdigest(),
        base_sha=hashlib.sha256(values[0]).hexdigest(),
        overlay_sha=hashlib.sha256(values[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(values[2]).hexdigest(),
    )


@pytest.fixture(autouse=True)
def _rootless_test_io(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lease_dir = tmp_path / "lease"
    lease_dir.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", lease_dir)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    data_root = tmp_path / "stage"
    data_root.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", data_root)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())


def test_journal_persists_exact_intent_commit_terminal_once() -> None:
    record = backend.PairUpgradeJournal()
    plan = _plan()
    with cleanup.protected_boca_job_lease(RUN) as lease:
        record.intent(plan, lease)
        record.commit(plan, lease)
        receipt = transaction.PairUpgradeReceipt(
            attempt_id=RUN,
            state="NO_GO",
            cleanup="INDETERMINATE",
            old_restored=False,
            commit_started=True,
            controller_id=None,
            worker_id=None,
            failed_phase="RETIRE_OLD",
        )
        record.terminal(plan, receipt, lease)
        root = stage.ROOT
        assert (root / f".boca-pair-upgrade-{RUN}.intent").stat().st_mode & 0o777 == 0o600
        assert (root / f".boca-pair-upgrade-{RUN}.commit").read_text().strip() == hashlib.sha256(
            (root / f".boca-pair-upgrade-{RUN}.intent").read_bytes()
        ).hexdigest()
        assert (
            (root / f".boca-pair-upgrade-{RUN}.terminal")
            .read_bytes()
            .startswith(b"BOCA_PAIR_UPGRADE ")
        )
        with pytest.raises(stage.StageError):
            record.terminal(plan, receipt, lease)


def test_second_or_replayed_journal_cannot_overwrite_previous_attempt() -> None:
    plan = _plan()
    with cleanup.protected_boca_job_lease(RUN) as lease:
        first, second = backend.PairUpgradeJournal(), backend.PairUpgradeJournal()
        first.intent(plan, lease)
        with pytest.raises(stage.StageError):
            second.intent(plan, lease)
        assert not (stage.ROOT / f".boca-pair-upgrade-{RUN}.commit").exists()


def test_old_container_guard_rejects_wrong_role_and_image_no_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: commands.append(args))
    monkeypatch.setattr(
        host,
        "_browser_inspect_record",
        lambda _cid: {
            "Id": plan.old_controller_id,
            "Image": plan.old_controller_image_id,
            "Name": "/boca-socios-controller-1",
            "Config": {"Labels": {"com.docker.compose.service": "wrong"}},
            "State": {"Running": True},
        },
    )
    with pytest.raises(backend.PairHostNoGo):
        backend._full_old_record(
            plan, plan.old_controller_id, role="controller", name="boca-socios-controller-1"
        )
    assert commands == []


def test_park_never_starts_exited_old_worker_or_removes_any_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

    plan = _plan()
    actor = backend.RootlessPairUpgradeBackend(_sources())
    actor.state = "STAGED"
    actor.stage_dir = stage.ROOT / "cutover-a-43080012345"
    actor.old = OnDemandInstallation(
        plan.old_attempt_id,
        plan.old_source_sha,
        plan.old_controller_id,
        plan.controller_ref,
        plan.old_worker_id,
        plan.worker_ref,
        Path(
            "/home/boca-deploy/.local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3"
        ),
        ReviewedInstalledPair(plan.old_attempt_id, "7" * 64, "8" * 64),
    )
    monkeypatch.setattr(actor, "_sqlite", lambda: None)
    monkeypatch.setattr(actor, "_old_exact", lambda *args, **kwargs: None)
    from boca_socios import host_on_demand_replace as binding

    monkeypatch.setattr(binding, "park_binding", lambda *args: None)
    monkeypatch.setattr(
        host, "_browser_docker_ids", lambda: {plan.old_controller_id, plan.old_worker_id}
    )
    commands: list[tuple[str, ...]] = []

    def docker(*argv: str, **kwargs: object) -> str:
        commands.append(argv)
        return (
            plan.old_controller_id if argv[:2] in (("docker", "stop"), ("docker", "update")) else ""
        )

    monkeypatch.setattr(host, "_run", docker)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        actor.park(plan, lease)
    assert actor.state == "PARKED"
    assert commands == [
        ("docker", "update", "--restart=no", plan.old_controller_id),
        ("docker", "stop", "-t", "8", plan.old_controller_id),
        ("docker", "rename", plan.old_worker_id, f"boca-socios-browser-worker-legacy-{RUN}"),
        ("docker", "rename", plan.old_controller_id, f"boca-socios-controller-legacy-{RUN}"),
    ]
    assert not any("rm" in command or "start" in command for command in commands)


def test_retirement_only_two_original_cids_after_bound_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from boca_socios import host_on_demand_replace as binding

    plan = _plan()
    actor = backend.RootlessPairUpgradeBackend(_sources())
    actor.state = "BOUND"
    actor.old = object()  # type: ignore[assignment] - phase fake, not a production binding
    actor.new = object()  # type: ignore[assignment]
    actor.worker_id = "3" * 64
    actor.controller_id = "4" * 64
    monkeypatch.setattr(actor, "_old_exact", lambda *args, **kwargs: None)
    monkeypatch.setattr(actor, "_candidate_cold", lambda *args, **kwargs: None)
    monkeypatch.setattr(binding, "commit_binding", lambda *args: None)
    identities = {plan.old_controller_id, plan.old_worker_id, "3" * 64, "4" * 64}
    monkeypatch.setattr(host, "_browser_docker_ids", lambda: identities.copy())
    commands: list[tuple[str, ...]] = []

    def docker(*args: str, **_kwargs: object) -> str:
        commands.append(args)
        if args[:2] == ("docker", "rm"):
            identities.remove(args[2])
            return args[2]
        raise AssertionError("unapproved command")

    monkeypatch.setattr(host, "_run", docker)
    with cleanup.protected_boca_job_lease(RUN) as lease:
        actor.retire_old(plan, "4" * 64, "3" * 64, lease)
    assert actor.state == "RETIRED"
    assert commands == [
        ("docker", "rm", plan.old_worker_id),
        ("docker", "rm", plan.old_controller_id),
    ]
