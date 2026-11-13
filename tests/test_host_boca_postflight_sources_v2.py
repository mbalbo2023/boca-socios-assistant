"""R247 physical postflight source assembly: fail closed without owner proof."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_postflight_sources_v2 as sources_v2
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_postflight_runtime as runtime
from boca_socios.host_boca_upgrade_cleanup_runtime import (
    RECEIPT_FILENAME,
    DurableFinalCleanupReceipt,
)
from test_host_boca_upgrade_postflight import _expected, _pair_bytes
from test_host_boca_upgrade_postflight_runtime import _installed_binding, _storage_tree


def _cleanup_receipt() -> DurableFinalCleanupReceipt:
    expected = _expected()
    return DurableFinalCleanupReceipt(
        expected.plan.attempt_id,
        "ACCEPT",
        expected.cleanup_receipt,
        hashlib.sha256(expected.cleanup_receipt).hexdigest(),
        "a" * 64,
    )


def _receipt_dir(path: Path, receipt: DurableFinalCleanupReceipt) -> Path:
    directory = path / "private-boca"
    directory.mkdir(mode=0o700)
    filename = directory / RECEIPT_FILENAME
    filename.write_bytes(receipt.raw)
    filename.chmod(0o600)
    return directory


def _build(path: Path, *, volume_attestor=None) -> runtime.PostflightReadSources:
    expected, receipt = _expected(), _cleanup_receipt()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    return sources_v2.build_protected_postflight_sources(
        expected,
        lease,
        receipt,
        receipt_directory=_receipt_dir(path, receipt),
        volume_attestor=volume_attestor,
    )


def test_builder_supplies_exact_real_source_adapters_but_never_fakes_owner_login(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path, volume_attestor=lambda: None)
    assert type(result) is runtime.PostflightReadSources
    assert result.pair_reader is not None
    assert result.binding_reader is not None
    assert result.retained_reader is not None
    assert callable(result.storage_reader)
    assert callable(result.site_saved_reader)
    assert callable(result.site_mirror_reader)
    assert callable(result.worker_startup_reader)
    assert callable(result.cleanup_readback)
    assert callable(result.panel_health_reader)
    assert result.panel_login_reader is None
    assert result.monitor_reader is None


def test_full_postflight_refuses_missing_actual_chrome_login_before_reading_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If no independently authenticated owner acceptance exists, even a
    # complete-looking pair/storage/SITE bundle must not reach TECHNICAL_ACCEPT.
    monkeypatch.setattr(
        runtime,
        "_attest_live_pair",
        lambda *_: pytest.fail("builder must remain lazy, no host IO"),
    )
    expected = _expected()
    result = _build(tmp_path, volume_attestor=lambda: None)
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.ProductionPostflightSnapshotReader(expected, result)(lease)


def test_r252_technical_builder_and_reader_capture_only_health_without_owner_or_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, receipt = _expected(), _cleanup_receipt()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    events: list[object] = []
    monkeypatch.setattr(runtime, "_attest_live_pair", lambda *_: events.append("pair"))
    monkeypatch.setattr(
        cleanup, "verify_protected_boca_job_lease", lambda *_: events.append("lease")
    )
    monkeypatch.setattr(
        runtime, "_read_rootless_identity", lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID)
    )

    class Reply:
        status = 200

        def getheader(self, name: str) -> str | None:
            return {"Content-Length": "15", "Content-Type": "text/plain; charset=utf-8"}.get(name)

        def read(self, limit: int) -> bytes:
            assert limit == 65
            return b"BOCA_BETA_READY"

    class Connection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            events.append((host, port, timeout))

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            events.append((method, path, headers))

        def getresponse(self) -> Reply:
            return Reply()

        def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(runtime.http.client, "HTTPConnection", Connection)
    source = sources_v2.build_protected_postflight_sources(
        expected,
        lease,
        receipt,
        receipt_directory=_receipt_dir(tmp_path, receipt),
        volume_attestor=lambda: None,
    )
    source = replace(
        source,
        pair_reader=lambda _: _pair_bytes(),
        binding_reader=lambda _: _installed_binding(expected),
        retained_reader=lambda pins, *_: pins,
        storage_reader=lambda: expected.storage_before,
        rootless_identity_reader=lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID),
        site_saved_reader=lambda: expected.site_url_fingerprint,
        site_mirror_reader=lambda: expected.site_url_fingerprint,
        worker_startup_reader=lambda: "READ_FRESH_FILE_AT_NEXT_START",
    )
    reader = runtime.ProductionPostflightSnapshotReader(
        expected,
        source,
        verify_lease=cleanup.verify_protected_boca_job_lease,
        technical_only=True,
    )
    raw = postflight.capture_technical_postflight(
        expected,
        lease,
        read_snapshot=reader,
        verify_lease=cleanup.verify_protected_boca_job_lease,
    )
    assert postflight.verify_technical_postflight(raw, expected) == raw
    methods_and_paths = [event[:2] for event in events if isinstance(event, tuple)]
    assert methods_and_paths.count(("GET", "/healthz")) == 2
    assert not any(path in ("/ingresar", "/monitor/tokens.json") for _, path in methods_and_paths)
    assert source.panel_login_reader is None and source.monitor_reader is None


def test_actual_durable_cleanup_readback_has_nofollow_mode_and_same_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        runtime,
        "_attest_live_pair",
        lambda *_: events.append("pair"),
    )
    monkeypatch.setattr(
        cleanup,
        "verify_protected_boca_job_lease",
        lambda *_: events.append("lease"),
    )
    monkeypatch.setattr(
        runtime,
        "_read_rootless_identity",
        lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID),
    )
    receipt = _cleanup_receipt()
    directory = _receipt_dir(tmp_path, receipt)
    expected = _expected()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    result = sources_v2.build_protected_postflight_sources(
        expected,
        lease,
        receipt,
        receipt_directory=directory,
        volume_attestor=lambda: None,
    )
    assert result.cleanup_readback is not None
    assert result.cleanup_readback() == receipt.raw
    assert events == ["pair", "lease", "lease", "pair"]

    target = directory / RECEIPT_FILENAME
    target.rename(directory / "old-receipt")
    target.symlink_to(directory / "old-receipt")
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        result.cleanup_readback()


def test_storage_source_requires_exact_rootless_and_double_boundary_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _expected()
    events: list[str] = []
    monkeypatch.setattr(runtime, "_attest_live_pair", lambda *_: events.append("pair"))
    monkeypatch.setattr(
        runtime,
        "_read_rootless_identity",
        lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID),
    )
    monkeypatch.setattr(
        sources_v2,
        "capture_structural_storage_fingerprints",
        lambda: events.append("storage") or expected.storage_before,
    )
    result = _build(tmp_path, volume_attestor=lambda: events.append("volume"))
    assert result.storage_reader is not None
    assert result.storage_reader() == expected.storage_before
    assert events == ["pair", "volume", "storage", "volume", "pair"]

    monkeypatch.setattr(runtime, "_read_rootless_identity", lambda: (0, 0))
    events.clear()
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        result.storage_reader()
    assert events == ["pair"]


def test_no_storage_attestor_never_fabricates_fingerprint(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result.storage_reader is None
    assert result.panel_login_reader is None
    assert result.monitor_reader is None


def test_builder_rejects_mismatched_durable_cleanup_receipt(tmp_path: Path) -> None:
    expected, receipt = _expected(), _cleanup_receipt()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    directory = _receipt_dir(tmp_path, receipt)
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.build_protected_postflight_sources(
            expected,
            lease,
            replace(receipt, sha256="f" * 64),
            receipt_directory=directory,
        )


def test_owner_login_and_monitor_optimistic_callbacks_are_rejected(tmp_path: Path) -> None:
    expected, receipt = _expected(), _cleanup_receipt()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    directory = _receipt_dir(tmp_path, receipt)
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.build_protected_postflight_sources(
            expected,
            lease,
            receipt,
            receipt_directory=directory,
            volume_attestor=lambda: None,
            owner_acceptance=lambda: "LOGIN_HTTP_200",
        )
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.build_protected_postflight_sources(
            expected,
            lease,
            receipt,
            receipt_directory=directory,
            volume_attestor=lambda: None,
            monitor_metadata=lambda: b'{"source":"IN_MEMORY","observations":2}',
        )


def test_cleanup_wrong_receipt_identity_or_mode_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "_attest_live_pair", lambda *_: None)
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(
        runtime,
        "_read_rootless_identity",
        lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID),
    )
    result = _build(tmp_path, volume_attestor=lambda: None)
    assert result.cleanup_readback is not None
    file = tmp_path / "private-boca" / RECEIPT_FILENAME
    file.chmod(0o644)
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        result.cleanup_readback()
    file.chmod(0o600)
    file.write_bytes(b"forged")
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        result.cleanup_readback()


def test_sqlite_and_owner_session_normal_writes_preserve_structural_identity(
    tmp_path: Path,
) -> None:
    _storage_tree(tmp_path)
    before = sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    legacy_before = runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    sqlite = tmp_path / "volumes/boca-socios_boca_data/_data/boca.sqlite3"
    session = tmp_path / "volumes/boca-socios_boca_owner/_data/boca_owner_session.sqlite3"
    for index, target in enumerate((sqlite, session)):
        with target.open("ab") as file:
            file.write(b"legitimate private sqlite update")
        timestamp = 1_700_000_000_000_000_000 + index
        os.utime(target, ns=(timestamp, timestamp))
    after = sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    assert after == before
    # R245's wider fingerprint unnecessarily changes on database writes.
    legacy_after = runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    assert legacy_after.sqlite_inode_sha256 != legacy_before.sqlite_inode_sha256
    assert legacy_after.owner_session_inode_sha256 != legacy_before.owner_session_inode_sha256


def test_structural_identity_detects_inode_replacement_symlink_and_foreign_root(
    tmp_path: Path,
) -> None:
    _storage_tree(tmp_path)
    before = sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    sqlite = tmp_path / "volumes/boca-socios_boca_data/_data/boca.sqlite3"
    sqlite.rename(sqlite.with_suffix(".retained"))
    sqlite.write_bytes(b"replacement sqlite even if same data bytes")
    sqlite.chmod(0o600)
    replaced = sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    assert replaced.sqlite_inode_sha256 != before.sqlite_inode_sha256
    assert replaced.owner_session_inode_sha256 == before.owner_session_inode_sha256
    assert replaced.key_inode_sha256 == before.key_inode_sha256
    sqlite.unlink()
    sqlite.symlink_to(sqlite.with_suffix(".retained"))
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path / "x")


def test_structural_identity_keeps_key_mtime_custody_guard(tmp_path: Path) -> None:
    _storage_tree(tmp_path)
    before = sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    key = tmp_path / "volumes/boca-socios_boca_key/_data/boca_master_key"
    with key.open("ab") as file:
        file.write(b"unreviewed key mutation")
    after = sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    assert after.key_inode_sha256 != before.key_inode_sha256
    assert after.sqlite_inode_sha256 == before.sqlite_inode_sha256
    assert after.owner_session_inode_sha256 == before.owner_session_inode_sha256


def test_structural_identity_refuses_hardlink_permission_and_mount_redirect(
    tmp_path: Path,
) -> None:
    _storage_tree(tmp_path)
    session = tmp_path / "volumes/boca-socios_boca_owner/_data/boca_owner_session.sqlite3"
    duplicate = session.with_name("duplicate-owner-session")
    os.link(session, duplicate)
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    duplicate.unlink()
    session.chmod(0o644)
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    session.chmod(0o600)
    (tmp_path / "volumes").rename(tmp_path / "volumes-real")
    (tmp_path / "volumes").symlink_to(tmp_path / "volumes-real")
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)


def test_structural_identity_refuses_wrong_effective_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _storage_tree(tmp_path)
    actual_uid = os.geteuid()
    monkeypatch.setattr(sources_v2.os, "geteuid", lambda: actual_uid + 1)
    with pytest.raises(sources_v2.PostflightSourcesNoGo):
        sources_v2.capture_structural_storage_fingerprints(tmp_path, trusted_root=tmp_path)
