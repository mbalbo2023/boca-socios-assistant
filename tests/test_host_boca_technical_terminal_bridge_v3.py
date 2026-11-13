"""R257 technical terminal requires genuine durable same-lease SUCCESS proof."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_durable_technical_postflight_v2 as durable
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_postflight_volume_attestor_v2 as volumes
from boca_socios import host_boca_successor_assembly_v3 as assembly
from boca_socios import host_boca_technical_terminal_bridge_v3 as terminal
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_failure_cleanup_v2 as failure_cleanup
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_postflight_runtime as runtime
from boca_socios import host_cutover_stage as stage
from test_host_boca_upgrade_postflight import _cleanup_receipt, _expected, _pair_value, _snapshot

pytest_plugins = ("test_host_boca_success_cleanup_bridge_v2",)


@pytest.fixture
def ready(monkeypatch: pytest.MonkeyPatch, tmp_path, frozen_proof):
    preflight, _ = frozen_proof
    graph = assembly.prepare_inert_same_lease(preflight)
    plan = graph.plan
    held = cleanup.BocaJobLease(plan.attempt_id, -1, -1, True)
    monkeypatch.setattr(stage, "ROOT", tmp_path)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    monkeypatch.setattr(
        cleanup,
        "verify_protected_boca_job_lease",
        lambda lease, attempt: (
            None if lease is held and attempt == plan.attempt_id else pytest.fail("foreign lease")
        ),
    )
    monkeypatch.setattr(
        cleanup,
        "protected_boca_job_lease",
        lambda *_: pytest.fail("second lease forbidden"),
    )
    graph.success.final_cleanup._verify_lease = cleanup.verify_protected_boca_job_lease

    raw_cleanup = json.loads(_cleanup_receipt())
    raw_cleanup["attempt_id"] = plan.attempt_id
    cleanup_bytes = json.dumps(raw_cleanup, sort_keys=True, separators=(",", ":")).encode()
    expected = replace(
        _expected(),
        plan=plan,
        release=preflight.inputs.release,
        retained=preflight.inputs.custody.resources,
        cleanup_receipt=cleanup_bytes,
    )
    final_cleanup = cleanup_runtime.DurableFinalCleanupReceipt(
        plan.attempt_id,
        "ACCEPT",
        cleanup_bytes,
        hashlib.sha256(cleanup_bytes).hexdigest(),
        "f" * 64,
    )
    monkeypatch.setattr(
        graph.success.final_cleanup,
        "completed_final_cleanup",
        lambda found_plan, found_lease: (
            final_cleanup
            if found_plan is plan and found_lease is held
            else pytest.fail("foreign cleanup coordinates")
        ),
    )
    pair_body = _pair_value()
    pair_body["attempt_id"] = plan.attempt_id
    pair_body["observation_run_id"] = plan.attempt_id
    pair_body["source_sha"] = plan.new_source_sha
    pair_body["services"][0]["image_ref"] = plan.controller_ref
    pair_body["services"][1]["image_ref"] = plan.worker_ref
    pair_bytes = (
        b"BOCA_INSTALLED_PAIR "
        + json.dumps(pair_body, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    binding = postflight.PostflightBinding(
        plan.attempt_id,
        plan.new_source_sha,
        expected.controller_id,
        expected.worker_id,
        plan.controller_ref,
        plan.worker_ref,
    )
    physical = replace(
        _snapshot(panel_loopback_probe="HEALTH_HTTP_200"),
        pair_receipt=pair_bytes,
        binding=binding,
        retained=expected.retained,
        cleanup_receipt_sha256=hashlib.sha256(cleanup_bytes).hexdigest(),
    )
    monkeypatch.setattr(
        runtime.ProductionPostflightSnapshotReader,
        "__call__",
        lambda reader, lease: (
            physical
            if reader.technical_only and reader.expected is expected and lease is held
            else pytest.fail("non-physical reader")
        ),
    )
    monkeypatch.setattr(volumes.ProductionBocaVolumeAttestor, "__call__", lambda _self: None)

    # Exercise real private-directory O_EXCL persistence and commit readback;
    # journal's independent R177 current-pair capture is covered separately.
    intent = b"original protected journal intent"
    graph.journal._intent = intent
    graph.journal._lease = held
    monkeypatch.setattr(
        graph.journal,
        "attest_active_intent",
        lambda found_plan, found_lease: (
            None if found_plan is plan and found_lease is held else pytest.fail("journal drift")
        ),
    )
    commit_name = f".boca-pair-upgrade-{plan.attempt_id}.commit"
    (tmp_path / commit_name).write_bytes(hashlib.sha256(intent).hexdigest().encode())
    (tmp_path / commit_name).chmod(0o600)
    witness = terminal.OneShotTechnicalTerminalBridge(graph)
    receipt = transaction.PairUpgradeReceipt(
        plan.attempt_id,
        "ACCEPTED",
        "ACCEPT",
        False,
        True,
        expected.controller_id,
        expected.worker_id,
        "NONE",
    )
    return witness, graph, held, expected, receipt, tmp_path


def test_success_two_phases_durable_commit_technical_and_terminal_keep_beta_no_go(ready):
    bridge, graph, lease, expected, receipt, root = ready
    volume = volumes.ProductionBocaVolumeAttestor(expected, lease)
    bridge.attest_technical_success(expected, volume, lease)
    bridge(graph.plan, receipt, lease)
    proof = bridge.technical_terminal
    assert proof is not None and proof.beta_deploy == "NO_GO"
    assert proof.terminal_state == "TECHNICAL_ACCEPTED_OWNER_PENDING"
    assert proof.passkey_attested is False and proof.apply_authorized is False
    assert (root / proof.filename).read_bytes() == proof.raw
    assert (root / f".boca-pair-upgrade-{graph.plan.attempt_id}.terminal").is_file()
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, receipt, lease)


def test_missing_cleanup_success_cannot_write_technical_or_terminal(ready, monkeypatch):
    bridge, graph, lease, expected, receipt, root = ready
    monkeypatch.setattr(graph.success.final_cleanup, "completed_final_cleanup", lambda *_: None)
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge.attest_technical_success(
            expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
        )
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, receipt, lease)
    assert not list(root.glob("*.terminal"))


def test_success_without_prior_technical_proof_never_accepts(ready):
    bridge, graph, lease, _expected, receipt, root = ready
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, receipt, lease)
    assert not list(root.glob("*.terminal"))


@pytest.mark.parametrize("bad", ("controller", "worker", "lease", "phase"))
def test_accept_refuses_cid_drift_foreign_lease_and_false_commit(ready, bad):
    bridge, graph, lease, expected, receipt, root = ready
    bridge.attest_technical_success(
        expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
    )
    supplied_lease = lease
    if bad == "controller":
        receipt = replace(receipt, controller_id="a" * 64)
    elif bad == "worker":
        receipt = replace(receipt, worker_id="b" * 64)
    elif bad == "lease":
        supplied_lease = cleanup.BocaJobLease(graph.plan.attempt_id, -1, -1, True)
    else:
        receipt = replace(receipt, commit_started=False)
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, receipt, supplied_lease)
    assert not list(root.glob("*.terminal"))


def test_owner_login_must_remain_not_attested_and_not_beta_go(ready):
    bridge, _graph, lease, expected, _receipt, root = ready
    altered = replace(expected, site_url_fingerprint="z" * 64)
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge.attest_technical_success(
            altered, volumes.ProductionBocaVolumeAttestor(altered, lease), lease
        )
    assert not list(root.glob("*.technical-postflight-v2"))


def test_real_owner_login_probe_cannot_substitute_technical_health(ready, monkeypatch):
    bridge, _graph, lease, expected, _receipt, root = ready
    original = runtime.ProductionPostflightSnapshotReader.__call__
    monkeypatch.setattr(
        runtime.ProductionPostflightSnapshotReader,
        "__call__",
        lambda reader, held: replace(original(reader, held), panel_loopback_probe="LOGIN_HTTP_200"),
    )
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge.attest_technical_success(
            expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
        )
    assert not list(root.glob("*.technical-postflight-v2"))


def test_missing_durable_commit_consumes_attempt_without_success_retry(ready):
    bridge, graph, lease, expected, _receipt, root = ready
    marker = root / f".boca-pair-upgrade-{graph.plan.attempt_id}.commit"
    marker.unlink()
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge.attest_technical_success(
            expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
        )
    marker.write_bytes(b"bad later commit")
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge.attest_technical_success(
            expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
        )
    assert not list(root.glob("*.terminal"))
    assert not list(root.glob("*.technical-postflight-v2"))


def test_duplicate_terminal_is_never_overwritten_or_retried(ready):
    bridge, graph, lease, expected, receipt, root = ready
    bridge.attest_technical_success(
        expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
    )
    occupied = root / f".boca-pair-upgrade-{graph.plan.attempt_id}.terminal"
    occupied.write_bytes(b"original immutable terminal")
    occupied.chmod(0o600)
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, receipt, lease)
    assert occupied.read_bytes() == b"original immutable terminal"
    occupied.unlink()
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, receipt, lease)


def test_post_success_no_go_uses_postcommit_terminal_without_failure_cleanup(ready, monkeypatch):
    bridge, graph, lease, expected, receipt, root = ready
    bridge.attest_technical_success(
        expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
    )
    monkeypatch.setattr(
        failure_cleanup,
        "execute_durable_failure_cleanup",
        lambda *_a, **_k: pytest.fail("no postcommit FAILURE cleanup or rollback"),
    )
    failed = replace(receipt, state="NO_GO", cleanup="INDETERMINATE")
    bridge(graph.plan, failed, lease)
    assert bridge.technical_terminal is None
    assert (root / f".boca-pair-upgrade-{graph.plan.attempt_id}.terminal").is_file()


def test_precommit_result_after_success_witness_is_never_accepted(ready, monkeypatch):
    bridge, graph, lease, expected, receipt, root = ready
    bridge.attest_technical_success(
        expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
    )
    monkeypatch.setattr(
        failure_cleanup,
        "execute_durable_failure_cleanup",
        lambda *_a, **_k: pytest.fail("no second cleanup after technical success"),
    )
    rejected = replace(receipt, state="NO_GO", cleanup="INDETERMINATE", commit_started=False)
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, rejected, lease)
    assert not list(root.glob("*.terminal"))


def test_precommit_failure_delegates_existing_failure_sink_once(ready, monkeypatch):
    bridge, graph, lease, _expected, _receipt, _root = ready
    actual = transaction.PairUpgradeReceipt(
        graph.plan.attempt_id, "NO_GO", "INDETERMINATE", False, False, None, None, "ATTEST"
    )
    calls = []
    monkeypatch.setattr(graph.failure, "__call__", lambda *_: pytest.fail("class magic"))
    # Existing bound sink is intentionally the only allowed FAILURE path.
    monkeypatch.setattr(type(graph.failure), "__call__", lambda _self, *args: calls.append(args))
    bridge(graph.plan, actual, lease)
    assert calls == [(graph.plan, actual, lease)]
    assert bridge.technical_terminal is None
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, actual, lease)


def test_technical_proof_removal_after_capture_refuses_terminal(ready):
    bridge, graph, lease, expected, receipt, root = ready
    bridge.attest_technical_success(
        expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
    )
    (root / f".boca-pair-upgrade-{graph.plan.attempt_id}.technical-postflight-v2").unlink()
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge(graph.plan, receipt, lease)
    assert bridge.technical_terminal is None


def test_foreign_named_technical_receipt_is_not_promotable(ready, monkeypatch):
    bridge, _graph, lease, expected, _receipt, root = ready
    original = durable.OneShotDurableTechnicalPostflightV2.persist
    monkeypatch.setattr(
        durable.OneShotDurableTechnicalPostflightV2,
        "persist",
        lambda self: replace(original(self), filename="foreign-postflight"),
    )
    with pytest.raises(terminal.TechnicalTerminalNoGo):
        bridge.attest_technical_success(
            expected, volumes.ProductionBocaVolumeAttestor(expected, lease), lease
        )
    assert len(list(root.glob("*.technical-postflight-v2"))) == 1
    assert bridge.technical_terminal is None
