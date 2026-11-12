"""R244 production postflight evidence: no secret reads or fake host receipts."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_postflight_runtime as runtime
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
from test_host_boca_upgrade_postflight import _expected, _pair_bytes


def _storage_tree(root: Path) -> None:
    for volume, filename in (
        ("boca-socios_boca_data", "boca.sqlite3"),
        ("boca-socios_boca_key", "boca_master_key"),
        ("boca-socios_boca_owner", "boca_owner_session.sqlite3"),
    ):
        directory = root / "volumes" / volume / "_data"
        directory.mkdir(parents=True, mode=0o700)
        file = directory / filename
        file.write_bytes(b"private test fixture only")
        file.chmod(0o600)


def test_storage_capture_uses_inode_metadata_without_opening_file_contents(tmp_path: Path) -> None:
    _storage_tree(tmp_path)
    first = runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    assert len(first.sqlite_inode_sha256) == 64
    assert len(first.key_inode_sha256) == 64
    assert len(first.owner_session_inode_sha256) == 64
    assert (
        len({first.sqlite_inode_sha256, first.key_inode_sha256, first.owner_session_inode_sha256})
        == 3
    )
    assert first == runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)


def test_storage_capture_rejects_symlink_hardlink_and_missing_file(tmp_path: Path) -> None:
    _storage_tree(tmp_path)
    filename = tmp_path / "volumes/boca-socios_boca_key/_data/boca_master_key"
    original = tmp_path / "original-key"
    filename.rename(original)
    filename.symlink_to(original)
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    filename.unlink()
    os.link(original, filename)
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    filename.unlink()
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)


def test_storage_capture_rejects_untrusted_root_and_ancestor_redirect(tmp_path: Path) -> None:
    _storage_tree(tmp_path)
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path / "other")
    moved = tmp_path / "volumes-real"
    (tmp_path / "volumes").rename(moved)
    (tmp_path / "volumes").symlink_to(moved)
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)


def test_storage_capture_detects_identity_replacement_without_reading_bytes(tmp_path: Path) -> None:
    _storage_tree(tmp_path)
    before = runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    filename = tmp_path / "volumes/boca-socios_boca_owner/_data/boca_owner_session.sqlite3"
    filename.rename(filename.with_suffix(".old"))
    filename.write_bytes(b"synthetic replacement")
    filename.chmod(0o600)
    after = runtime.capture_storage_fingerprints(tmp_path, trusted_root=tmp_path)
    assert before.sqlite_inode_sha256 == after.sqlite_inode_sha256
    assert before.key_inode_sha256 == after.key_inode_sha256
    assert before.owner_session_inode_sha256 != after.owner_session_inode_sha256


def test_production_storage_reader_requires_a_proven_boca_volume_boundary() -> None:
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.ProductionPrivateStorageReader()()


def _sources(
    expected: postflight.PostflightExpected, events: list[str]
) -> runtime.PostflightReadSources:
    return runtime.PostflightReadSources(
        pair_reader=lambda attempt: events.append("pair") or _pair_bytes(),
        binding_reader=lambda lease: events.append("binding") or _installed_binding(expected),
        retained_reader=lambda pins, graph, attempt, lease: events.append("retained") or pins,
        storage_reader=lambda: events.append("storage") or expected.storage_before,
        rootless_identity_reader=lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID),
        site_saved_reader=lambda: events.append("site_saved") or expected.site_url_fingerprint,
        site_mirror_reader=lambda: events.append("site_mirror") or expected.site_url_fingerprint,
        worker_startup_reader=lambda: events.append("startup") or "READ_FRESH_FILE_AT_NEXT_START",
        monitor_reader=lambda: events.append("monitor") or ("NOT_CONNECTED", 0),
        panel_login_reader=lambda: events.append("panel") or "LOGIN_HTTP_200",
        cleanup_readback=lambda: events.append("cleanup") or expected.cleanup_receipt,
    )


def _installed_binding(expected: postflight.PostflightExpected) -> OnDemandInstallation:
    pair_value = postflight._pair_payload(expected, _pair_bytes())
    controller, worker = pair_value["services"]
    return OnDemandInstallation(
        expected.plan.attempt_id,
        expected.plan.new_source_sha,
        expected.controller_id,
        expected.plan.controller_ref,
        expected.worker_id,
        expected.plan.worker_ref,
        runtime.binding.CANONICAL_DATABASE,
        ReviewedInstalledPair(
            original_browser_attempt=expected.plan.attempt_id,
            controller_config_hash=controller["config_hash"],
            worker_config_hash=worker["config_hash"],
        ),
    )


def _reader(
    expected: postflight.PostflightExpected,
    sources: runtime.PostflightReadSources,
    events: list[str],
) -> runtime.ProductionPostflightSnapshotReader:
    return runtime.ProductionPostflightSnapshotReader(
        expected,
        sources,
        verify_lease=lambda lease, attempt: events.append("lease"),
    )


def test_live_reader_reuses_existing_pair_binding_and_resource_graph_under_lease() -> None:
    expected = _expected()
    events: list[str] = []
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    found = _reader(expected, _sources(expected, events), events)(lease)
    assert found.pair_receipt == _pair_bytes()
    assert found.retained == expected.retained
    assert found.binding.controller_id == expected.controller_id
    assert found.rootless_uid == cleanup.EXPECTED_UID
    assert found.cleanup_receipt_sha256
    assert events == [
        "lease",
        "cleanup",
        "pair",
        "binding",
        "retained",
        "storage",
        "site_saved",
        "site_mirror",
        "startup",
        "panel",
        "monitor",
        "lease",
    ]


@pytest.mark.parametrize(
    "missing",
    [
        "panel_login_reader",
        "monitor_reader",
        "cleanup_readback",
        "site_mirror_reader",
        "worker_startup_reader",
    ],
)
def test_missing_physical_source_is_nogo_before_host_reads(missing: str) -> None:
    expected = _expected()
    events: list[str] = []
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    sources = replace(_sources(expected, events), **{missing: None})
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        _reader(expected, sources, events)(lease)
    assert events == []


def test_modified_cleanup_receipt_is_nogo_before_any_pair_read() -> None:
    expected = _expected()
    events: list[str] = []
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    sources = replace(_sources(expected, events), cleanup_readback=lambda: b"different")
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        _reader(expected, sources, events)(lease)
    assert events == ["lease"]


def test_live_reader_rejects_site_mirror_drift() -> None:
    expected = _expected()
    events: list[str] = []
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, -1, True)
    sources = replace(_sources(expected, events), site_mirror_reader=lambda: "f" * 64)
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        _reader(expected, sources, events)(lease)


def test_production_site_url_witness_reads_only_hashes_from_pinned_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _expected()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(pair, "observe", lambda _: _pair_bytes())
    monkeypatch.setattr(
        runtime.service, "read_installed_binding", lambda _: _installed_binding(expected)
    )

    def docker(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("inspect", "--format"):
            return '["python","-m","boca_socios.browser.ipc_server"]\n'
        assert args[:4] == ("exec", "--user", "10001:10001", expected.controller_id)
        return "BOCA_SITE_URL_SHA256 " + expected.site_url_fingerprint + "\n"

    monkeypatch.setattr(cleanup, "_docker", docker)
    witness = runtime.ProductionSiteUrlWitness(expected, lease)
    assert witness.saved_fingerprint() == expected.site_url_fingerprint
    assert witness.mirror_fingerprint() == expected.site_url_fingerprint
    assert witness.worker_startup() == "READ_FRESH_FILE_AT_NEXT_START"
    assert len(calls) == 3
    assert all("https://" not in " ".join(cmd) for cmd in calls)
    assert all("--network" not in cmd for cmd in calls)


def test_production_site_url_witness_rejects_bad_worker_command_and_leaked_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _expected()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(pair, "observe", lambda _: _pair_bytes())
    monkeypatch.setattr(
        runtime.service, "read_installed_binding", lambda _: _installed_binding(expected)
    )
    witness = runtime.ProductionSiteUrlWitness(expected, lease)
    monkeypatch.setattr(cleanup, "_docker", lambda *_: "BOCA_SITE_URL_SHA256 " + "f" * 64 + "\n")
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        witness.saved_fingerprint()
    monkeypatch.setattr(cleanup, "_docker", lambda *_: '["python","-m","foreign.module"]\n')
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        witness.worker_startup()


def test_private_8443_readonly_health_probe_is_not_a_passkey_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _expected()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    called: list[object] = []
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(pair, "observe", lambda _: _pair_bytes())
    monkeypatch.setattr(
        runtime.service, "read_installed_binding", lambda _: _installed_binding(expected)
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
            called.append((host, port, timeout))

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            called.append((method, path, headers))

        def getresponse(self) -> Reply:
            return Reply()

        def close(self) -> None:
            called.append("close")

    monkeypatch.setattr(runtime.http.client, "HTTPConnection", Connection)
    assert runtime.ProductionPrivatePanelHealthWitness(expected, lease)() == "HEALTH_HTTP_200"
    assert called == [
        ("127.0.0.1", 8443, 2.0),
        ("GET", "/healthz", {"Host": "localhost:8443", "Connection": "close"}),
        "close",
    ]
    assert "LOGIN_HTTP_200" not in called


def test_panel_health_probe_rejects_redirect_or_unexpected_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _expected()
    lease = cleanup.BocaJobLease(expected.plan.attempt_id, -1, os.getpid(), True)
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(pair, "observe", lambda _: _pair_bytes())
    monkeypatch.setattr(
        runtime.service, "read_installed_binding", lambda _: _installed_binding(expected)
    )

    class Connection:
        def __init__(self, *_: object, **__: object) -> None: ...
        def request(self, *_: object, **__: object) -> None: ...
        def getresponse(self) -> object:
            return type(
                "Redirect",
                (),
                {
                    "status": 302,
                    "getheader": lambda *_: "15",
                    "read": lambda *_: b"BOCA_BETA_READY",
                },
            )()

        def close(self) -> None: ...

    monkeypatch.setattr(runtime.http.client, "HTTPConnection", Connection)
    with pytest.raises(runtime.PostflightRuntimeNoGo):
        runtime.ProductionPrivatePanelHealthWitness(expected, lease)()
