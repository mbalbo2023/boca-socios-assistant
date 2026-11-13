"""R253: durable technical proof is read-only, one-shot and never BETA GO."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_durable_technical_postflight_v2 as durable
from boca_socios import host_boca_postflight_sources_v2 as sources_v2
from boca_socios import host_boca_postflight_volume_attestor_v2 as volume_v2
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_postflight_runtime as runtime
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios import host_cutover_stage as stage
from test_host_boca_upgrade_postflight import _expected, _snapshot


@pytest.fixture
def proof(monkeypatch: pytest.MonkeyPatch, tmp_path):
    expected = _expected()
    plan = expected.plan
    lease = cleanup.BocaJobLease(plan.attempt_id, -1, -1, True)
    final = successor.OneShotFinalCleanupBridge(
        None, read_cleanup_coordinates=None, verify_lease=None
    )
    cleanup_receipt = cleanup_runtime.DurableFinalCleanupReceipt(
        plan.attempt_id,
        "ACCEPT",
        expected.cleanup_receipt,
        hashlib.sha256(expected.cleanup_receipt).hexdigest(),
        "f" * 64,
    )
    cleanup_checks: list[tuple[object, object]] = []
    monkeypatch.setattr(
        final,
        "completed_final_cleanup",
        lambda found_plan, found_lease: (
            cleanup_checks.append((found_plan, found_lease)) or cleanup_receipt
        ),
    )
    lease_checks: list[tuple[object, str]] = []

    def attest(found_lease, attempt):
        lease_checks.append((found_lease, attempt))
        assert found_lease is lease and attempt == plan.attempt_id

    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", attest)
    monkeypatch.setattr(
        cleanup,
        "protected_boca_job_lease",
        lambda *_: pytest.fail("unexpected second lease"),
    )
    private = tmp_path / "boca-private"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", private)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    observations = []

    def snapshot(reader, found_lease):
        assert reader.technical_only is True
        assert reader.expected is expected
        assert reader.sources.panel_login_reader is None
        assert reader.sources.monitor_reader is None
        assert found_lease is lease
        observations.append("physical-reader")
        return _snapshot(panel_loopback_probe="HEALTH_HTTP_200")

    monkeypatch.setattr(runtime.ProductionPostflightSnapshotReader, "__call__", snapshot)
    monkeypatch.setattr(volume_v2.ProductionBocaVolumeAttestor, "__call__", lambda _self: None)
    return expected, lease, final, cleanup_checks, lease_checks, observations, private


def _volume(expected, lease):
    return volume_v2.ProductionBocaVolumeAttestor(expected, lease)


def test_exact_success_proof_is_durable_with_double_read_and_no_promotion(proof):
    expected, lease, final, completed, checks, observations, directory = proof
    operation = durable.OneShotDurableTechnicalPostflightV2(
        expected.plan, expected, lease, final, volume_attestor=_volume(expected, lease)
    )
    saved = operation.persist()
    assert saved.attempt_id == expected.plan.attempt_id
    assert saved.version == "BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2"
    assert (
        saved.filename == f".boca-pair-upgrade-{expected.plan.attempt_id}.technical-postflight-v2"
    )
    assert (directory / saved.filename).read_bytes() == saved.raw
    assert hashlib.sha256(saved.raw).hexdigest() == saved.sha256
    assert (directory / saved.filename).stat().st_mode & 0o777 == 0o600
    assert saved.apply_authorized is False
    assert saved.terminal_accept_authorized is False
    assert saved.beta_deploy == "NO_GO"
    assert observations == ["physical-reader", "physical-reader"]
    assert completed and all(pair is expected.plan and held is lease for pair, held in completed)
    assert len(checks) >= 6 and all(held is lease for held, _ in checks)
    with pytest.raises(durable.DurableTechnicalPostflightNoGo, match="NO_GO"):
        operation.persist()


def test_missing_volume_attestor_fails_closed_before_any_write(proof):
    expected, lease, final, _, _, observations, directory = proof
    operation = durable.OneShotDurableTechnicalPostflightV2(
        expected.plan, expected, lease, final, volume_attestor=None
    )
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        operation.persist()


def test_unreviewed_noop_volume_callback_cannot_certify_storage(proof):
    expected, lease, final, _, _, observations, directory = proof
    operation = durable.OneShotDurableTechnicalPostflightV2(
        expected.plan, expected, lease, final, volume_attestor=lambda: None
    )
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        operation.persist()
    assert observations == []
    assert list(directory.iterdir()) == []
    assert observations == []
    assert list(directory.iterdir()) == []
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        operation.persist()


def test_foreign_lease_and_expected_plan_fail_before_write(proof):
    expected, lease, final, _, _, _, directory = proof
    foreign = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        durable.OneShotDurableTechnicalPostflightV2(
            expected.plan, expected, foreign, final, volume_attestor=_volume(expected, lease)
        ).persist()
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        durable.OneShotDurableTechnicalPostflightV2(
            replace(expected.plan), expected, lease, final, volume_attestor=_volume(expected, lease)
        ).persist()
    assert list(directory.iterdir()) == []


def test_cleanup_receipt_mismatch_refused_before_capture(proof, monkeypatch):
    expected, lease, final, _, _, observations, directory = proof
    mutated = replace(expected, cleanup_receipt=expected.cleanup_receipt + b"tamper")
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        durable.OneShotDurableTechnicalPostflightV2(
            mutated.plan, mutated, lease, final, volume_attestor=_volume(expected, lease)
        ).persist()
    assert observations == []
    assert list(directory.iterdir()) == []


def test_failed_exclusive_write_cannot_retry_or_overwrite(proof):
    expected, lease, final, _, _, _, directory = proof
    filename = f".boca-pair-upgrade-{expected.plan.attempt_id}.technical-postflight-v2"
    occupied = directory / filename
    occupied.write_bytes(b"occupied")
    operation = durable.OneShotDurableTechnicalPostflightV2(
        expected.plan, expected, lease, final, volume_attestor=_volume(expected, lease)
    )
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        operation.persist()
    assert occupied.read_bytes() == b"occupied"
    occupied.unlink()
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        operation.persist()


@pytest.mark.parametrize("failure", ("lease_after_read", "readback_tamper"))
def test_post_write_failure_remains_quarantined(proof, monkeypatch, failure):
    expected, lease, final, _, checks, _, directory = proof
    if failure == "lease_after_read":
        original = cleanup.verify_protected_boca_job_lease
        original_write = stage._create_exclusive
        written = [False]

        def write_then_mark(*args, **kwargs):
            original_write(*args, **kwargs)
            written[0] = True

        monkeypatch.setattr(stage, "_create_exclusive", write_then_mark)

        def fail_late(held, attempt):
            if written[0]:
                raise ValueError("lease gone")
            original(held, attempt)

        monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", fail_late)
    else:
        original_read = stage._read_file

        def wrong_read(*args, **kwargs):
            data, identity = original_read(*args, **kwargs)
            return data + b"tamper", identity

        monkeypatch.setattr(stage, "_read_file", wrong_read)
    operation = durable.OneShotDurableTechnicalPostflightV2(
        expected.plan, expected, lease, final, volume_attestor=_volume(expected, lease)
    )
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        operation.persist()
    assert len(list(directory.iterdir())) == 1
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        operation.persist()


def test_production_source_builder_is_used_not_injected_owner_monitor(proof, monkeypatch):
    expected, lease, final, _, _, _, _ = proof
    original = sources_v2.build_protected_postflight_sources
    calls = []

    def authentic_builder(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(sources_v2, "build_protected_postflight_sources", authentic_builder)
    durable.OneShotDurableTechnicalPostflightV2(
        expected.plan, expected, lease, final, volume_attestor=_volume(expected, lease)
    ).persist()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:2] == (expected, lease)
    assert kwargs["receipt_directory"] == stage.ROOT
    assert "owner_acceptance" not in kwargs
    assert "monitor_metadata" not in kwargs


def test_named_receipt_inode_swap_after_readback_fails_closed(proof, monkeypatch):
    expected, lease, final, _, _, _, directory = proof
    original = stage._read_file

    def replaced_after_read(directory_fd, name, checksum, *, limit):
        result = original(directory_fd, name, checksum, limit=limit)
        replacement = directory / "replacement.tmp"
        replacement.write_bytes(result[0])
        replacement.chmod(0o600)
        os.replace(replacement, directory / name)
        return result

    monkeypatch.setattr(stage, "_read_file", replaced_after_read)
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        durable.OneShotDurableTechnicalPostflightV2(
            expected.plan, expected, lease, final, volume_attestor=_volume(expected, lease)
        ).persist()
    assert len(list(directory.iterdir())) == 1


@pytest.mark.parametrize("invalid_observation", ("unhealthy", "drifted_second", "fake_login"))
def test_snapshot_failure_never_writes_technical_proof(proof, monkeypatch, invalid_observation):
    expected, lease, final, _, _, _, directory = proof
    readings = [0]

    def invalid_reader(reader, found_lease):
        assert reader.technical_only is True and found_lease is lease
        readings[0] += 1
        if invalid_observation == "unhealthy":
            return _snapshot(panel_loopback_probe="HEALTH_HTTP_503")
        if invalid_observation == "fake_login":
            return _snapshot(panel_loopback_probe="LOGIN_HTTP_200")
        if readings[0] == 2:
            return _snapshot(
                panel_loopback_probe="HEALTH_HTTP_200", site_url_saved_fingerprint="0" * 64
            )
        return _snapshot(panel_loopback_probe="HEALTH_HTTP_200")

    monkeypatch.setattr(runtime.ProductionPostflightSnapshotReader, "__call__", invalid_reader)
    with pytest.raises(durable.DurableTechnicalPostflightNoGo):
        durable.OneShotDurableTechnicalPostflightV2(
            expected.plan, expected, lease, final, volume_attestor=_volume(expected, lease)
        ).persist()
    assert list(directory.iterdir()) == []
