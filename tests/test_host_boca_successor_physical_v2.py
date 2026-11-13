"""R248 successor: dynamic current pair versus immutable R188 resource creators.

All captures are in-memory/offline, using the real lease contract in a private
temporary directory. No Docker daemon, site or owner credentials are accessed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_successor_integrations as bound_bridge
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_same_lease as old_bridge
from boca_socios import host_boca_upgrade_successor_runtime as successor_runtime
from boca_socios import host_cutover_stage as stage
from boca_socios.host_boca_pair_stage import PairSources
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
from test_host_boca_successor_integrations import _inputs_with_proofs
from test_host_boca_upgrade_adapters import EGRESS, IPC, SITE, RetainedIO

_BOUND = bound_bridge.verify_runner_bound_host_inputs(**_inputs_with_proofs(step=2))


@pytest.fixture
def held_lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    directory = tmp_path / "lease"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", directory)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    attempt = _BOUND.plan.attempt_id
    with cleanup.protected_boca_job_lease(attempt) as lease:
        yield lease


def _bound() -> bound_bridge.BoundSuccessorInputs:
    return _BOUND


def _current_pair(plan: transaction.PairCoordinates, *, observation: str) -> bytes:
    original = json.loads(_BOUND.original_pair_receipt.removeprefix(pair._PREFIX))
    original["observation_run_id"] = observation
    return pair._canonical(original)


def _installed(plan: transaction.PairCoordinates) -> OnDemandInstallation:
    old = json.loads(_BOUND.original_pair_receipt.removeprefix(pair._PREFIX))
    ctl, worker = old["services"]
    from boca_socios import host_boca_binding_observe as binding

    return OnDemandInstallation(
        plan.old_attempt_id,
        plan.old_source_sha,
        plan.old_controller_id,
        ctl["image_ref"],
        plan.old_worker_id,
        worker["image_ref"],
        binding.CANONICAL_DATABASE,
        ReviewedInstalledPair(plan.old_attempt_id, ctl["config_hash"], worker["config_hash"]),
    )


def _io_for_graph(
    graph: adapters.GraphExpectation,
    plan: transaction.PairCoordinates,
    *,
    running_old: bool,
) -> RetainedIO:
    """Make an exact synthetic graph while retaining R188 creator labels."""
    io = RetainedIO()
    template = io.value
    io.expected = graph
    containers: list[cleanup.Container] = []
    images: list[cleanup.Image] = []
    for service in graph.services:
        is_old = service.ident in (plan.old_controller_id, plan.old_worker_id)
        if service.ident == plan.old_controller_id:
            image_id = plan.old_controller_image_id
        elif service.ident == plan.old_worker_id:
            image_id = plan.old_worker_image_id
        else:
            image_id = "sha256:" + ("8" if service.role == "controller" else "9") * 64
        is_running = service.role == "controller" and (running_old if is_old else not running_old)
        volumes = (
            ("boca-socios_boca_data", "boca-socios_boca_key", "boca-socios_boca_owner", IPC, SITE)
            if service.role == "controller"
            else (IPC, SITE)
        )
        labels = (
            ("com.docker.compose.project", "boca-socios"),
            ("com.docker.compose.service", service.role),
            ("org.opencontainers.image.revision", service.source_sha),
            ("boca.socios.browser-ipc-attempt", service.installation_attempt),
        )
        containers.append(
            cleanup.Container(
                service.ident,
                "/boca-socios-" + service.role + "-synthetic",
                image_id,
                is_running,
                labels,
                tuple(sorted(volumes)),
                ("boca-socios_boca_private",) if is_running else (),
            )
        )
        images.append(cleanup.Image(image_id, (service.image_ref,), cleanup.BOCA_SOURCE))
    private = next(n for n in template.networks if n.name != EGRESS)
    private = replace(
        private,
        attached_ids=tuple(container.ident for container in containers if container.running),
    )
    egress = next(n for n in template.networks if n.name == EGRESS)
    io.value = replace(
        template,
        containers=tuple(containers),
        images=tuple(images),
        networks=(egress, private),
        global_image_ids=frozenset(image.ident for image in images),
    )
    io.identities[IPC] = _bound().custody.resources.ipc_inode_sha256
    io.identities[SITE] = _bound().custody.resources.site_inode_sha256
    return io


def _read_capturer(
    bound: bound_bridge.BoundSuccessorInputs,
    *,
    physical_pair: bytes | None = None,
    control_inode: str | None = None,
) -> physical.SuccessorCurrentPairCapture:
    return physical.SuccessorCurrentPairCapture(
        historical_custody=bound.custody,
        current_pair_observation=bound.original_pair_receipt,
        retained_io=_io_for_graph(
            physical.expected_transition_graph(
                bound.plan, "NEW", previous_observation=bound.original_pair_receipt
            ),
            bound.plan,
            running_old=True,
        ),
        pair_reader=lambda _run: (
            _current_pair(bound.plan, observation=bound.plan.attempt_id)
            if physical_pair is None
            else physical_pair
        ),
        binding_reader=lambda _lease: _installed(bound.plan),
        control_identity_reader=lambda _name: (
            bound.custody.control_directory_inode_sha256 if control_inode is None else control_inode
        ),
    )


def test_successor_current_pair_accepts_b_to_c_without_falsifying_original_r188_seed(
    held_lease: cleanup.BocaJobLease,
) -> None:
    bound = _bound()
    assert bound.plan.old_source_sha != bound.custody.installed_source_sha
    assert bound.plan.old_attempt_id != bound.custody.installation_attempt
    old = old_bridge.ProductionSameLeaseCapture(
        observation_receipt=bound.original_pair_receipt,
        custody=bound.custody,
    )
    with pytest.raises(old_bridge.SameLeaseCaptureNoGo):
        old(bound.plan, held_lease)
    witness = _read_capturer(bound)(bound.plan, held_lease)
    assert witness.old_attempt_id == bound.plan.old_attempt_id
    assert witness.old_source_sha == bound.plan.old_source_sha
    assert witness.retained == bound.custody.resources
    assert witness.observation_run_id == bound.plan.observation_run_id


@pytest.mark.parametrize(
    "phase,expected_count",
    (
        ("NEW", 2),
        ("PARKED", 2),
        ("WORKER", 3),
        ("CONTROLLER", 4),
        ("BOUND", 4),
        ("RETIRED", 2),
        ("RESTORED", 2),
    ),
)
def test_transition_graph_uses_exact_old_and_new_ids_and_history_remains_separate(
    held_lease: cleanup.BocaJobLease, phase: str, expected_count: int
) -> None:
    bound = _bound()
    plan = bound.plan
    worker = "e" * 64
    controller = "f" * 64
    graph = physical.expected_transition_graph(
        plan,
        phase,
        worker_id=worker if phase in ("WORKER", "CONTROLLER", "BOUND", "RETIRED") else None,
        controller_id=controller if phase in ("CONTROLLER", "BOUND", "RETIRED") else None,
        previous_observation=bound.original_pair_receipt,
    )
    assert len(graph.services) == expected_count
    assert all(s.installation_attempt != bound.custody.installation_attempt for s in graph.services)
    io = _io_for_graph(graph, plan, running_old=phase in ("NEW", "RESTORED"))
    assert (
        physical.observe_transition_resources(
            plan, bound.custody, held_lease, graph=graph, retained_io=io
        )
        == bound.custody.resources
    )


@pytest.mark.parametrize(
    "change",
    (
        "foreign",
        "missing",
        "image",
        "source",
        "creator",
        "network",
        "worker-active",
        "pair-drift",
        "control-drift",
    ),
)
def test_transition_rejects_foreign_or_changed_resource_graph_without_host_effects(
    held_lease: cleanup.BocaJobLease, change: str
) -> None:
    bound = _bound()
    plan = bound.plan
    graph = physical.expected_transition_graph(
        plan,
        "CONTROLLER",
        worker_id="e" * 64,
        controller_id="f" * 64,
        previous_observation=bound.original_pair_receipt,
    )
    io = _io_for_graph(graph, plan, running_old=False)
    if change == "foreign":
        io.value = replace(
            io.value,
            containers=(*io.value.containers, replace(io.value.containers[0], ident="1" * 64)),
        )
    elif change == "missing":
        io.value = replace(io.value, containers=io.value.containers[:-1])
    elif change == "image":
        io.value = replace(
            io.value,
            containers=(
                replace(io.value.containers[0], image_id="sha256:" + "f" * 64),
                *io.value.containers[1:],
            ),
        )
    elif change == "source":
        ctl = io.value.containers[0]
        io.value = replace(
            io.value,
            containers=(
                replace(
                    ctl,
                    labels=tuple(
                        (k, "0" * 40 if k == "org.opencontainers.image.revision" else v)
                        for k, v in ctl.labels
                    ),
                ),
                *io.value.containers[1:],
            ),
        )
    elif change == "creator":
        first = io.value.volumes[0]
        io.value = replace(
            io.value,
            volumes=(
                replace(
                    first,
                    labels=first.labels[:-1]
                    + (("boca.socios.browser-ipc-attempt", plan.attempt_id),),
                ),
                *io.value.volumes[1:],
            ),
        )
    elif change == "network":
        first = io.value.networks[0]
        io.value = replace(
            io.value, networks=(replace(first, attached_ids=("0" * 64,)), *io.value.networks[1:])
        )
    elif change == "worker-active":
        io.worker["Pid"] = 42
    elif change == "control-drift":
        with pytest.raises(physical.SuccessorPhysicalNoGo):
            _read_capturer(bound, control_inode="0" * 64)(plan, held_lease)
        return
    else:
        altered = copy.deepcopy(
            json.loads(_current_pair(plan, observation=plan.attempt_id).removeprefix(pair._PREFIX))
        )
        altered["services"][0]["container_id"] = "0" * 64
        with pytest.raises(physical.SuccessorPhysicalNoGo):
            _read_capturer(bound, physical_pair=pair._canonical(altered))(plan, held_lease)
        return
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        physical.observe_transition_resources(
            plan, bound.custody, held_lease, graph=graph, retained_io=io
        )


@pytest.mark.parametrize(
    "missing", ("old-worker", "new-controller", "new-worker", "unknown-phase", "same-id")
)
def test_invalid_phase_or_unproven_candidate_id_never_lowers_graph_cardinality(
    missing: str,
) -> None:
    bound = _bound()
    current = bound.plan
    kwargs: dict[str, object] = {"previous_observation": bound.original_pair_receipt}
    phase = "CONTROLLER"
    if missing == "old-worker":
        raw = json.loads(bound.original_pair_receipt.removeprefix(pair._PREFIX))
        raw["services"][1]["container_id"] = "0" * 64
        kwargs["previous_observation"] = pair._canonical(raw)
    elif missing == "new-controller":
        kwargs["worker_id"] = "e" * 64
    elif missing == "new-worker":
        kwargs["controller_id"] = "f" * 64
    elif missing == "unknown-phase":
        phase = "UNEXPECTED"
    else:
        kwargs["worker_id"] = current.old_worker_id
        kwargs["controller_id"] = "f" * 64
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        physical.expected_transition_graph(current, phase, **kwargs)


def test_unwired_successor_actor_stays_no_go_even_with_a_valid_transition_graph() -> None:
    bound = _bound()
    graph = physical.expected_transition_graph(
        bound.plan, "NEW", previous_observation=bound.original_pair_receipt
    )
    assert len(graph.services) == 2
    assert bound.apply_authorized is False


def test_restored_old_pair_must_discard_candidate_ids_only_after_physical_absence(
    held_lease: cleanup.BocaJobLease,
) -> None:
    bound = _bound()
    graph = physical.expected_transition_graph(
        bound.plan, "RESTORED", previous_observation=bound.original_pair_receipt
    )
    sources = (b"base", b"overlay", b"seccomp")
    validated_sources = PairSources(
        *sources,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(sources[0]).hexdigest(),
        overlay_sha=hashlib.sha256(sources[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(sources[2]).hexdigest(),
    )
    io = _io_for_graph(graph, bound.plan, running_old=True)
    live = physical.PhysicalSuccessorIntegrations(
        bound.plan,
        bound.release,
        bound.custody,
        bound.original_pair_receipt,
        retained_io=io,
        control_identity_reader=lambda _name: bound.custody.control_directory_inode_sha256,
    )
    backend = successor_runtime.PostflightGatedSuccessorBackend(
        validated_sources, bound.retained, integrations=live, gate=None
    )
    live.bind_backend(backend)
    backend.state = "RESTORED"
    # R179 does not erase these two recorded IDs after removing its exact
    # candidate containers; preserving them is necessary for the audit trail.
    backend.worker_id = "e" * 64
    backend.controller_id = "f" * 64
    assert live.retained_resources(bound.plan, held_lease) == bound.retained
    assert backend.requires_persistent_receipt is False
    # If a removed candidate survives, the exact two-CID census must reject.
    io.value = replace(
        io.value,
        containers=(*io.value.containers, replace(io.value.containers[1], ident="e" * 64)),
    )
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        live.retained_resources(bound.plan, held_lease)


@pytest.mark.parametrize("phase", ("NEW", "PARKED", "WORKER", "CONTROLLER", "BOUND", "RETIRED"))
def test_integrations_follow_reused_backend_phase_without_discovering_unknown_names(
    held_lease: cleanup.BocaJobLease, phase: str
) -> None:
    bound = _bound()
    worker_id = "e" * 64 if phase in ("WORKER", "CONTROLLER", "BOUND", "RETIRED") else None
    controller_id = "f" * 64 if phase in ("CONTROLLER", "BOUND", "RETIRED") else None
    graph = physical.expected_transition_graph(
        bound.plan,
        phase,
        worker_id=worker_id,
        controller_id=controller_id,
        previous_observation=bound.original_pair_receipt,
    )
    io = _io_for_graph(graph, bound.plan, running_old=phase == "NEW")
    source = (b"base", b"overlay", b"seccomp")
    pair_sources = PairSources(
        *source,
        original_compose_sha="f" * 64,
        base_sha=hashlib.sha256(source[0]).hexdigest(),
        overlay_sha=hashlib.sha256(source[1]).hexdigest(),
        seccomp_sha=hashlib.sha256(source[2]).hexdigest(),
    )
    integrator = physical.PhysicalSuccessorIntegrations(
        bound.plan,
        bound.release,
        bound.custody,
        bound.original_pair_receipt,
        retained_io=io,
        control_identity_reader=lambda _name: bound.custody.control_directory_inode_sha256,
    )
    backend = successor_runtime.PostflightGatedSuccessorBackend(
        pair_sources, bound.retained, integrations=integrator, gate=None
    )
    integrator.bind_backend(backend)
    backend.state = phase
    backend.worker_id = worker_id
    backend.controller_id = controller_id
    assert integrator.retained_resources(bound.plan, held_lease) == bound.retained
    integrator.verify_release(bound.plan, pair_sources, held_lease)
    with pytest.raises(physical.SuccessorPhysicalNoGo):
        integrator.final_cleanup(bound.plan, held_lease)
    assert backend.requires_persistent_receipt is False


def test_new_current_pair_witness_is_immutable_in_the_existing_one_lease_journal(
    held_lease: cleanup.BocaJobLease, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bound = _bound()
    directory = tmp_path / "journal"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", directory)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    reads: list[str] = []
    capturer = _read_capturer(bound)

    def twice(plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease):
        reads.append(plan.attempt_id)
        return capturer(plan, lease)

    actual = journal.SuccessorPairJournal(bound.release, bound.custody.resources, twice)
    actual.intent(bound.plan, held_lease)
    evidence_file = directory / f".boca-pair-upgrade-{bound.plan.attempt_id}.evidence"
    intent_file = directory / f".boca-pair-upgrade-{bound.plan.attempt_id}.intent"
    body = json.loads(evidence_file.read_bytes())
    assert len(reads) == 2
    assert body["plan"]["old_source_sha"] == bound.plan.old_source_sha
    assert body["witness"]["old_source_sha"] == bound.plan.old_source_sha
    assert body["witness"]["old_attempt_id"] != bound.custody.installation_attempt
    assert body["witness"]["retained"]["site_creator_attempt"] == (
        bound.custody.resources.site_creator_attempt
    )
    assert evidence_file.stat().st_mode & 0o777 == 0o600
    assert intent_file.stat().st_mode & 0o777 == 0o600
    first_evidence = evidence_file.read_bytes()
    with pytest.raises(stage.StageError, match="quarantine attempt"):
        actual.intent(bound.plan, held_lease)
    assert evidence_file.read_bytes() == first_evidence


def test_current_observer_drift_aborts_before_creating_a_journal(
    held_lease: cleanup.BocaJobLease, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bound = _bound()
    directory = tmp_path / "journal"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", directory)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    fresh = _current_pair(bound.plan, observation=bound.plan.attempt_id)
    tainted = json.loads(fresh.removeprefix(pair._PREFIX))
    tainted["services"][0]["container_id"] = "0" * 64
    changed = pair._canonical(tainted)
    reads = 0

    def unstable(_run: str) -> bytes:
        nonlocal reads
        reads += 1
        return fresh if reads <= 2 else changed

    base = _read_capturer(bound)
    capture = replace(base, pair_reader=unstable)
    record = journal.SuccessorPairJournal(bound.release, bound.custody.resources, capture)
    with pytest.raises(journal.SuccessorJournalNoGo):
        record.intent(bound.plan, held_lease)
    assert list(directory.iterdir()) == []
