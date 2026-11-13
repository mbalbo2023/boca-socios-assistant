"""R259: one physical-lease adapter cannot promote a synthetic technical ACK."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_guarded_successor_backend_v4 as guarded
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_cli as cli
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_postflight_volume_attestor_v2 as volumes
from boca_socios import host_boca_prepark_expected_v2 as prepark
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_successor_assembly_v3 as assembly
from boca_socios import host_boca_successor_integrations as integration
from boca_socios import host_boca_technical_terminal_bridge_v3 as terminal
from test_host_boca_upgrade_postflight import _expected

pytest_plugins = ("test_host_boca_success_cleanup_bridge_v2",)


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch, frozen_proof):
    preflight, _ = frozen_proof
    graph = assembly.prepare_inert_same_lease(preflight)
    lease = cleanup.BocaJobLease(graph.plan.attempt_id, -1, os.getpid(), True)
    checks: list[str] = []

    def verify(found: cleanup.BocaJobLease, attempt: str) -> None:
        assert found is lease and attempt == graph.plan.attempt_id
        checks.append("lease")

    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", verify)
    graph.success.final_cleanup._verify_lease = cleanup.verify_protected_boca_job_lease
    monkeypatch.setattr(
        graph.journal,
        "attest_active_intent",
        lambda plan, held: (
            checks.append("intent")
            if plan is graph.plan and held is lease
            else pytest.fail("intent drift")
        ),
    )
    witness = terminal.OneShotTechnicalTerminalBridge(graph)
    return graph, lease, witness, checks


def physical_seed(graph, lease):
    plan = graph.plan
    old = journal.FreshPairWitness(
        plan.observation_run_id,
        plan.old_attempt_id,
        plan.old_source_sha,
        plan.old_controller_id,
        plan.old_worker_id,
        plan.old_controller_image_id,
        plan.old_worker_image_id,
        graph.preflight.inputs.custody.resources,
        "f" * 64,
    )
    return prepark.PreParkExpectedSeed(
        graph.preflight.inputs,
        lease,
        _expected().storage_before,
        "ATTESTED",
        _expected().site_url_fingerprint,
        old,
    )


def test_constructor_is_inert_but_checks_exact_graph_and_held_lease(context, monkeypatch):
    graph, lease, witness, checks = context
    monkeypatch.setattr(cleanup, "_docker", lambda *_: pytest.fail("unexpected Docker"))
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    assert type(backend).requires_persistent_receipt is True
    assert backend.terminal is witness
    assert backend.graph is graph
    assert backend.technical_accept_authorized is False
    assert checks == ["lease"]
    wrong_lease = cleanup.BocaJobLease(graph.plan.attempt_id, -1, os.getpid(), True)
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        guarded.GuardedTechnicalSuccessorBackend(graph, witness, wrong_lease)
    other = assembly.prepare_inert_same_lease(graph.preflight)
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        guarded.GuardedTechnicalSuccessorBackend(other, witness, lease)


def test_attest_captures_prepark_identity_on_original_lease_before_stage(context, monkeypatch):
    graph, lease, witness, checks = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    original = graph.success.backend
    monkeypatch.setattr(original, "attest", lambda plan, held: checks.append("actor_attest"))
    seed = physical_seed(graph, lease)
    monkeypatch.setattr(
        prepark,
        "capture_prepark_expected_seed",
        lambda inputs, held: checks.append("double_prepark") or seed,
    )
    monkeypatch.setattr(original, "stage", lambda *_: checks.append("stage"))
    backend.attest(graph.plan, lease)
    backend.stage(graph.plan, lease)
    assert (
        checks.index("intent")
        < checks.index("actor_attest")
        < checks.index("double_prepark")
        < checks.index("stage")
    )
    assert backend.prepark_seed is seed


@pytest.mark.parametrize("invalid", ("seed_type", "foreign_lease", "changed_plan"))
def test_prepark_boundary_refuses_untrusted_seed_before_stage(context, monkeypatch, invalid):
    graph, lease, witness, _ = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(graph.success.backend, "attest", lambda *_: None)
    monkeypatch.setattr(graph.success.backend, "stage", lambda *_: pytest.fail("unsafe stage"))
    seed = physical_seed(graph, lease)
    if invalid == "seed_type":
        produced = object()
    elif invalid == "foreign_lease":
        produced = replace(seed, lease=cleanup.BocaJobLease(graph.plan.attempt_id, -1, -1, True))
    else:
        produced = replace(
            seed,
            inputs=replace(
                graph.preflight.inputs, plan=replace(graph.plan, attempt_id="1234567890")
            ),
        )
    monkeypatch.setattr(prepark, "capture_prepark_expected_seed", lambda *_: produced)
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        backend.attest(graph.plan, lease)
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        backend.stage(graph.plan, lease)


@pytest.mark.parametrize(
    "operation,args",
    (
        ("park", ()),
        ("create_worker", ()),
        ("create_controller", ("a" * 64,)),
        ("accept", ("a" * 64, "b" * 64)),
        ("replace_binding", ("a" * 64, "b" * 64)),
        ("retire_old", ("a" * 64, "b" * 64)),
    ),
)
def test_no_effectful_phase_without_genuine_prepark_seed(context, monkeypatch, operation, args):
    graph, lease, witness, _ = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(
        graph.success.backend,
        operation,
        lambda *_: pytest.fail("untrusted phase reached effectful actor"),
    )
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        getattr(backend, operation)(graph.plan, *args, lease)


def test_failed_prepark_cannot_restore_unmodified_old_pair_or_mutate(context, monkeypatch):
    graph, lease, witness, _ = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(
        graph.success.backend,
        "restore_old",
        lambda *_: pytest.fail("no restoration effects without prior stage"),
    )
    assert backend.restore_old(graph.plan, lease) is False


def test_typed_but_unproduced_prepark_seed_cannot_start_an_effect(context, monkeypatch):
    graph, lease, witness, _ = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    # An arbitrary caller can instantiate this public dataclass.  Its type
    # and plan equality do not prove that `backend.attest` captured anything.
    backend.prepark_seed = physical_seed(graph, lease)
    monkeypatch.setattr(
        graph.success.backend,
        "stage",
        lambda *_: pytest.fail("unproduced physical seed reached STAGE"),
    )
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        backend.stage(graph.plan, lease)


def test_prepark_attest_may_not_be_replayed_after_first_probe(context, monkeypatch):
    graph, lease, witness, checks = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(graph.success.backend, "attest", lambda *_: checks.append("attest"))
    monkeypatch.setattr(
        prepark,
        "capture_prepark_expected_seed",
        lambda *_: physical_seed(graph, lease),
    )
    backend.attest(graph.plan, lease)
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        backend.attest(graph.plan, lease)
    assert checks.count("attest") == 1


def test_precommit_site_mirror_is_read_only_attested_after_binding_before_marker(
    context, monkeypatch
):
    graph, lease, witness, checks = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(graph.success.backend, "attest", lambda *_: None)
    monkeypatch.setattr(
        prepark, "capture_prepark_expected_seed", lambda *_: physical_seed(graph, lease)
    )
    backend.attest(graph.plan, lease)
    monkeypatch.setattr(
        graph.success.backend,
        "replace_binding",
        lambda *_: checks.append("candidate_bound_and_restarted"),
    )
    monkeypatch.setattr(
        prepark,
        "attest_precommit_candidate_site_state",
        lambda plan, controller, worker, held, seed: (
            checks.append("precommit_double_site")
            if plan is graph.plan
            and held is lease
            and seed is backend.prepark_seed
            and controller == "a" * 64
            and worker == "b" * 64
            else pytest.fail("untrusted candidate site source")
        ),
        raising=False,
    )

    def storage_reader(checked_plan, candidate_controller_id, candidate_worker_id, held_lease):
        assert checked_plan is graph.plan and held_lease is lease
        assert candidate_controller_id == "a" * 64 and candidate_worker_id == "b" * 64
        checks.append("precommit_storage")
        return backend.prepark_seed.storage_before

    monkeypatch.setattr(prepark, "_candidate_storage", storage_reader, raising=False)
    backend.replace_binding(graph.plan, "a" * 64, "b" * 64, lease)
    assert (
        checks.index("candidate_bound_and_restarted")
        < checks.index("precommit_double_site")
        < checks.index("precommit_storage")
    )
    assert checks.count("precommit_storage") == 2


def test_precommit_site_veto_prevents_engine_commit_marker(context, monkeypatch):
    graph, lease, witness, _ = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(graph.success.backend, "attest", lambda *_: None)
    monkeypatch.setattr(
        prepark, "capture_prepark_expected_seed", lambda *_: physical_seed(graph, lease)
    )
    backend.attest(graph.plan, lease)
    monkeypatch.setattr(graph.success.backend, "replace_binding", lambda *_: None)
    monkeypatch.setattr(
        prepark,
        "attest_precommit_candidate_site_state",
        lambda *_: (_ for _ in ()).throw(prepark.PreParkExpectedNoGo("unverified mirror")),
        raising=False,
    )
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        backend.replace_binding(graph.plan, "a" * 64, "b" * 64, lease)


@pytest.mark.parametrize("drift", ("changed_inode", "second_capture", "unavailable"))
def test_precommit_storage_drift_is_no_go_before_irreversible_marker(context, monkeypatch, drift):
    graph, lease, witness, checks = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(graph.success.backend, "attest", lambda *_: None)
    monkeypatch.setattr(
        prepark, "capture_prepark_expected_seed", lambda *_: physical_seed(graph, lease)
    )
    backend.attest(graph.plan, lease)
    monkeypatch.setattr(
        graph.success.backend, "replace_binding", lambda *_: checks.append("new_pair_bound")
    )
    monkeypatch.setattr(
        prepark,
        "attest_precommit_candidate_site_state",
        lambda *_: checks.append("site_verified"),
    )
    storage = backend.prepark_seed.storage_before
    captures = [0]

    def storage_reader(checked_plan, candidate_controller_id, candidate_worker_id, held_lease):
        assert checked_plan is graph.plan and held_lease is lease
        assert candidate_controller_id == "a" * 64 and candidate_worker_id == "b" * 64
        captures[0] += 1
        checks.append("structural_storage")
        if drift == "unavailable":
            raise prepark.PreParkExpectedNoGo("unmapped rootless inode")
        if drift == "changed_inode" or captures[0] == 2:
            return replace(storage, key_inode_sha256="0" * 64)
        return storage

    monkeypatch.setattr(prepark, "_candidate_storage", storage_reader, raising=False)
    monkeypatch.setattr(
        graph.journal,
        "commit",
        lambda *_: pytest.fail("unverified storage crossed COMMIT_MARKER"),
    )
    with pytest.raises(guarded.GuardedSuccessorNoGo):
        backend.replace_binding(graph.plan, "a" * 64, "b" * 64, lease)
    assert checks.index("new_pair_bound") < checks.index("site_verified")
    assert captures[0] <= 2


def test_reviewed_helper_rejects_accepted_without_durable_success_terminal(
    frozen_proof, monkeypatch
):
    preflight, _ = frozen_proof
    monkeypatch.setattr(
        transaction,
        "run_pair_upgrade",
        lambda plan, **_kw: transaction.PairUpgradeReceipt(
            plan.attempt_id,
            "ACCEPTED",
            "ACCEPT",
            False,
            True,
            "a" * 64,
            "b" * 64,
            "NONE",
        ),
    )
    with pytest.raises(cli.SuccessorPreflightIneligible):
        cli._execute_reviewed_successor(preflight)


def test_finalization_accepts_only_genuine_cleanup_then_technical_terminal(context, monkeypatch):
    graph, lease, witness, checks = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    expected = replace(
        _expected(),
        plan=graph.plan,
        release=graph.preflight.inputs.release,
        retained=graph.preflight.inputs.custody.resources,
    )
    seed = physical_seed(graph, lease)
    monkeypatch.setattr(graph.success.backend, "attest", lambda *_: None)
    monkeypatch.setattr(prepark, "capture_prepark_expected_seed", lambda *_: seed)
    backend.attest(graph.plan, lease)
    monkeypatch.setattr(
        reusable.ReusablePairUpgradeBackend,
        "finalize",
        lambda _actor, _plan, **_kwargs: checks.append("official_cleanup") or "ACCEPT",
    )
    monkeypatch.setattr(
        prepark.PreParkExpectedSeed,
        "expected_after_cleanup",
        lambda _seed, _final, held: checks.append("expected") or expected,
    )
    monkeypatch.setattr(
        witness,
        "attest_technical_success",
        lambda physical, volume, held: (
            checks.append("durable_technical")
            if physical is expected
            and type(volume) is volumes.ProductionBocaVolumeAttestor
            and volume.expected is expected
            and volume.lease is held
            and held is lease
            else pytest.fail("technical proof not source-bound")
        ),
    )
    assert (
        backend.finalize(
            graph.plan,
            commit_started=True,
            controller_id=expected.controller_id,
            worker_id=expected.worker_id,
            lease=lease,
        )
        == "ACCEPT"
    )
    assert (
        checks.index("official_cleanup")
        < checks.index("expected")
        < checks.index("durable_technical")
    )
    assert backend.technical_accept_authorized is False


@pytest.mark.parametrize("cleanup", ("NO_GO", "INDETERMINATE"))
def test_nonaccept_cleanup_cannot_enter_technical_postflight(context, monkeypatch, cleanup):
    graph, lease, witness, _ = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    monkeypatch.setattr(
        reusable.ReusablePairUpgradeBackend,
        "finalize",
        lambda *_a, **_k: cleanup,
    )
    monkeypatch.setattr(
        witness,
        "attest_technical_success",
        lambda *_: pytest.fail("false technical acceptance"),
    )
    assert (
        backend.finalize(
            graph.plan,
            commit_started=True,
            controller_id="a" * 64,
            worker_id="b" * 64,
            lease=lease,
        )
        == cleanup
    )


def test_wrong_cid_after_cleanup_is_indeterminate_and_finalization_one_shot(context, monkeypatch):
    graph, lease, witness, checks = context
    backend = guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)
    expected = replace(
        _expected(),
        plan=graph.plan,
        release=graph.preflight.inputs.release,
        retained=graph.preflight.inputs.custody.resources,
    )
    seed = physical_seed(graph, lease)
    monkeypatch.setattr(graph.success.backend, "attest", lambda *_: None)
    monkeypatch.setattr(prepark, "capture_prepark_expected_seed", lambda *_: seed)
    backend.attest(graph.plan, lease)
    monkeypatch.setattr(
        reusable.ReusablePairUpgradeBackend,
        "finalize",
        lambda *_a, **_k: checks.append("official_cleanup") or "ACCEPT",
    )
    monkeypatch.setattr(prepark.PreParkExpectedSeed, "expected_after_cleanup", lambda *_: expected)
    monkeypatch.setattr(witness, "attest_technical_success", lambda *_: pytest.fail("CID drift"))
    assert (
        backend.finalize(
            graph.plan,
            commit_started=True,
            controller_id="f" * 64,
            worker_id=expected.worker_id,
            lease=lease,
        )
        == "INDETERMINATE"
    )
    assert checks.count("official_cleanup") == 1
    assert (
        backend.finalize(
            graph.plan,
            commit_started=True,
            controller_id=expected.controller_id,
            worker_id=expected.worker_id,
            lease=lease,
        )
        == "INDETERMINATE"
    )
    assert checks.count("official_cleanup") == 1


def test_reviewed_cli_graph_is_factory_created_only_after_durable_same_lease_intent(
    frozen_proof, monkeypatch
):
    preflight, _ = frozen_proof
    held = cleanup.BocaJobLease(preflight.inputs.plan.attempt_id, -1, os.getpid(), True)
    calls: list[str] = []
    monkeypatch.setattr(
        cleanup,
        "verify_protected_boca_job_lease",
        lambda lease, attempt: (
            calls.append("lease")
            if lease is held and attempt == preflight.inputs.plan.attempt_id
            else pytest.fail("untrusted lease")
        ),
    )
    monkeypatch.setattr(
        integration.CurrentBaseOnlyStageCustody,
        "intent",
        lambda _self, plan, lease: (
            calls.append("durable_intent")
            if plan is preflight.inputs.plan and lease is held
            else pytest.fail("foreign intent")
        ),
    )
    monkeypatch.setattr(
        cleanup,
        "protected_boca_job_lease",
        lambda *_: pytest.fail("real host lease cannot run in unit test"),
    )

    def fake_engine(plan, *, backend_factory, terminal_preflight, commit_marker, terminal_sink):
        assert plan is preflight.inputs.plan
        assert terminal_sink._actors.plan is plan
        assert type(terminal_sink) is terminal.OneShotTechnicalTerminalBridge
        assert commit_marker.__self__ is terminal_sink._actors.journal
        assert calls == []
        terminal_preflight(plan, held)
        assert calls == ["durable_intent"]
        candidate = backend_factory(plan, held)
        assert type(candidate) is guarded.GuardedTechnicalSuccessorBackend
        assert candidate.terminal is terminal_sink
        assert candidate.graph is terminal_sink._actors
        assert candidate.lease is held
        assert calls == ["durable_intent", "lease"]
        with pytest.raises(cli.SuccessorPreflightIneligible):
            backend_factory(plan, held)
        calls.append("no_host_effect")
        return transaction.PairUpgradeReceipt(
            plan.attempt_id,
            "NO_GO",
            "INDETERMINATE",
            False,
            False,
            None,
            None,
            "ATTEST",
        )

    monkeypatch.setattr(transaction, "run_pair_upgrade", fake_engine)
    actual = cli._execute_reviewed_successor(preflight)
    assert actual.state == "NO_GO"
    assert calls[-1] == "no_host_effect"


def test_reviewed_cli_helper_refuses_untyped_unauthenticated_preflight_without_engine(
    monkeypatch,
):
    monkeypatch.setattr(
        transaction,
        "run_pair_upgrade",
        lambda *_a, **_kw: pytest.fail("untrusted source reached deploy engine"),
    )
    with pytest.raises(cli.SuccessorPreflightIneligible):
        cli._execute_reviewed_successor(object())
