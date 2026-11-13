"""Synthetic, side-effect-free postflight contracts for a Boca pair successor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as cleanup_v2
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios.host_boca_pair_upgrade import PairCoordinates
from boca_socios.host_boca_upgrade_postflight import (
    PostflightBinding,
    PostflightExpected,
    PostflightNoGo,
    PostflightSnapshot,
    PostflightStorage,
    capture_postflight,
    capture_technical_postflight,
    verify_postflight,
    verify_technical_postflight,
)

_ATTEMPT = "98765"
_SOURCE = "b" * 40
_CONTROLLER_ID = "c" * 64
_WORKER_ID = "d" * 64
_CONTROLLER_IMAGE = "sha256:" + "1" * 64
_WORKER_IMAGE = "sha256:" + "2" * 64
_CONTROLLER_REF = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "3" * 64
_WORKER_REF = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "4" * 64
_IPC = "boca-socios_boca_browser_ipc"
_SITE = "boca-socios_boca_site_config"
_PUBLIC_VOLUMES = sorted(
    (
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_telegram",
        _IPC,
        _SITE,
    )
)
_STORAGE = PostflightStorage("7" * 64, "8" * 64, "9" * 64)
_PINS = adapters.ResourcePins("76543", "5" * 64, "43217075287", "6" * 64, "43217075287", "a" * 64)


def _json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode(
        "ascii"
    )


def _pair_value() -> dict[str, Any]:
    controller_volumes = sorted(
        ("boca-socios_boca_data", "boca-socios_boca_key", "boca-socios_boca_owner", _IPC, _SITE)
    )
    worker_volumes = sorted((_IPC, _SITE))
    return {
        "schema": 1,
        "state": "OBSERVED",
        "observation_run_id": _ATTEMPT,
        "source_sha": _SOURCE,
        "attempt_id": _ATTEMPT,
        "services": [
            {
                "service": "controller",
                "container_id": _CONTROLLER_ID,
                "running": True,
                "status": "running",
                "pid": 12345,
                "exit_code": 0,
                "health": "healthy",
                "image_id": _CONTROLLER_IMAGE,
                "image_ref": _CONTROLLER_REF,
                "config_hash": "a" * 64,
                "network_name": "boca-socios_boca_private",
                "network_id": "b" * 64,
                "volumes": controller_volumes,
                "port_8443": "LOOPBACK",
            },
            {
                "service": "browser-worker",
                "container_id": _WORKER_ID,
                "running": False,
                "status": "created",
                "pid": 0,
                "exit_code": 0,
                "health": "none",
                "image_id": _WORKER_IMAGE,
                "image_ref": _WORKER_REF,
                "config_hash": "c" * 64,
                "network_name": "boca-socios_boca_browser_egress",
                "network_id": "UNATTACHED",
                "volumes": worker_volumes,
                "port_8443": "NONE",
            },
        ],
        "volumes": _PUBLIC_VOLUMES,
        "ipc_volume": "BOTH",
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "cutover_authorized": False,
    }


def _pair_bytes(value: dict[str, Any] | None = None) -> bytes:
    return b"BOCA_INSTALLED_PAIR " + _json(_pair_value() if value is None else value) + b"\n"


def _cleanup_receipt() -> bytes:
    disk = {
        "stage_bytes_free": 2_000_000,
        "stage_inodes_free": 2000,
        "docker_bytes_free": 3_000_000,
        "docker_inodes_free": 3000,
        "stage_device": 11,
        "stage_inode": 12,
        "docker_device": 13,
        "docker_inode": 14,
    }
    counts = {"containers": 2, "images": 3, "networks": 2, "volumes": 6, "global_images": 3}
    return _json(
        {
            "version": 2,
            "scope": "boca-postdeploy-counted-v2",
            "outcome": "SUCCESS",
            "attempt_id": _ATTEMPT,
            "status": "ACCEPT",
            "before": disk,
            "after": disk,
            "before_counts": counts,
            "after_counts": counts,
            "removed": [],
            "retained_uncertain": [],
            "known_residue": [],
            "retained_attested": [cleanup_v2._HISTORICAL_ENTRY],
            "protected_pair": {
                "controller": {
                    "id": _CONTROLLER_ID,
                    "image_id": _CONTROLLER_IMAGE,
                    "running": True,
                },
                "worker": {"id": _WORKER_ID, "image_id": _WORKER_IMAGE, "running": False},
            },
        }
    )


def _expected(**kwargs: Any) -> PostflightExpected:
    plan = PairCoordinates(
        attempt_id=_ATTEMPT,
        observation_run_id="87654",
        old_attempt_id="76543",
        old_source_sha="a" * 40,
        old_controller_id="e" * 64,
        old_worker_id="f" * 64,
        old_controller_image_id="sha256:" + "e" * 64,
        old_worker_image_id="sha256:" + "f" * 64,
        new_source_sha=_SOURCE,
        release_run_id="65432",
        controller_ref=_CONTROLLER_REF,
        worker_ref=_WORKER_REF,
    )
    release = adapters.ReleaseEvidence(
        _SOURCE, "65432", _CONTROLLER_REF, _WORKER_REF, "3" * 64, "4" * 64
    )
    expected = PostflightExpected(
        plan=plan,
        release=release,
        controller_id=_CONTROLLER_ID,
        worker_id=_WORKER_ID,
        controller_image_id=_CONTROLLER_IMAGE,
        worker_image_id=_WORKER_IMAGE,
        retained=_PINS,
        storage_before=_STORAGE,
        site_url_fingerprint="a" * 64,
        cleanup_receipt=_cleanup_receipt(),
    )
    return replace(expected, **kwargs)


def _snapshot(**kwargs: Any) -> PostflightSnapshot:
    snapshot = PostflightSnapshot(
        pair_receipt=_pair_bytes(),
        binding=PostflightBinding(
            installation_attempt=_ATTEMPT,
            source_sha=_SOURCE,
            controller_id=_CONTROLLER_ID,
            worker_id=_WORKER_ID,
            controller_image_ref=_CONTROLLER_REF,
            worker_image_ref=_WORKER_REF,
        ),
        rootless_uid=10001,
        rootless_gid=10001,
        storage_after=_STORAGE,
        retained=_PINS,
        site_url_saved_fingerprint="a" * 64,
        site_url_worker_mirror_fingerprint="a" * 64,
        worker_site_url_startup="READ_FRESH_FILE_AT_NEXT_START",
        monitor_source="NOT_CONNECTED",
        monitor_observation_count=0,
        panel_loopback_probe="LOGIN_HTTP_200",
        cleanup_receipt_sha256=hashlib.sha256(_cleanup_receipt()).hexdigest(),
    )
    return replace(snapshot, **kwargs)


def _capture(
    snapshot: PostflightSnapshot | None = None,
    *,
    second: PostflightSnapshot | None = None,
    expected: PostflightExpected | None = None,
) -> tuple[bytes, list[tuple[str, object]]]:
    current = expected or _expected()
    first = snapshot or _snapshot()
    reads = iter((first, second or first))
    checks: list[tuple[str, object]] = []
    lease = cleanup.BocaJobLease(_ATTEMPT, -1, -1, True)

    def verify_lease(found: cleanup.BocaJobLease, attempt_id: str) -> None:
        checks.append((attempt_id, found))
        assert attempt_id == _ATTEMPT and found is lease

    def read_snapshot(found: cleanup.BocaJobLease) -> PostflightSnapshot:
        assert found is lease
        return next(reads)

    return (
        capture_postflight(current, lease, read_snapshot=read_snapshot, verify_lease=verify_lease),
        checks,
    )


def _technical_capture(
    snapshot: PostflightSnapshot | None = None,
    *,
    second: PostflightSnapshot | None = None,
    expected: PostflightExpected | None = None,
) -> tuple[bytes, list[str]]:
    first = snapshot or _snapshot(panel_loopback_probe="HEALTH_HTTP_200")
    reads = iter((first, second or first))
    evidence: list[str] = []
    lease = cleanup.BocaJobLease(_ATTEMPT, -1, -1, True)

    def verify_lease(found: cleanup.BocaJobLease, attempt: str) -> None:
        assert found is lease and attempt == _ATTEMPT
        evidence.append("lease")

    def read_snapshot(found: cleanup.BocaJobLease) -> PostflightSnapshot:
        assert found is lease
        evidence.append("read")
        return next(reads)

    return capture_technical_postflight(
        expected or _expected(), lease, read_snapshot=read_snapshot, verify_lease=verify_lease
    ), evidence


def test_technical_postflight_proves_blank_site_url_without_fake_fingerprint() -> None:
    """A new panel can be healthy before the owner configures any destination."""
    unset = "NOT_CONFIGURED"
    expected = _expected(site_url_fingerprint=unset)
    snapshot = _snapshot(
        site_url_saved_fingerprint=unset,
        site_url_worker_mirror_fingerprint=unset,
        panel_loopback_probe="HEALTH_HTTP_200",
    )
    raw, evidence = _technical_capture(snapshot, expected=expected)
    assert evidence == ["lease", "read", "lease", "read", "lease"]
    body = json.loads(raw.split(b" ", 1)[1])
    assert body["site_url"] == {
        "state": "NOT_CONFIGURED",
        "fingerprint": None,
        "mirror": None,
        "startup": "READ_FRESH_FILE_AT_NEXT_START",
    }
    assert body["panel"]["probe"] == "HEALTH_HTTP_200"
    assert body["passkey_chrome"] == "NOT_ATTESTED"
    assert body["beta_deploy"] == "NO_GO"
    assert verify_technical_postflight(raw, expected) == raw
    with pytest.raises(PostflightNoGo):
        verify_postflight(raw, expected)
    with pytest.raises(PostflightNoGo):
        _capture(snapshot, expected=expected)
    for replacement in (
        {"state": "CONFIGURED", "fingerprint": None, "mirror": None},
        {"state": "NOT_CONFIGURED", "fingerprint": "0" * 64, "mirror": None},
        {"state": "NOT_CONFIGURED", "fingerprint": None, "mirror": "0" * 64},
        {"fingerprint": None, "mirror": None},
    ):
        forged = json.loads(raw.split(b" ", 1)[1])
        forged["site_url"].update(replacement)
        if "state" not in replacement:
            del forged["site_url"]["state"]
        with pytest.raises(PostflightNoGo):
            verify_technical_postflight(
                b"BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2 " + _json(forged) + b"\n", expected
            )


@pytest.mark.parametrize(
    "saved,mirror",
    [
        ("NOT_CONFIGURED", "a" * 64),
        ("a" * 64, "NOT_CONFIGURED"),
        ("UNVERIFIED", "NOT_CONFIGURED"),
        ("", "NOT_CONFIGURED"),
    ],
)
def test_unconfigured_technical_postflight_requires_two_exact_absent_witnesses(
    saved: str, mirror: str
) -> None:
    with pytest.raises(PostflightNoGo):
        _technical_capture(
            _snapshot(
                site_url_saved_fingerprint=saved,
                site_url_worker_mirror_fingerprint=mirror,
                panel_loopback_probe="HEALTH_HTTP_200",
            ),
            expected=_expected(site_url_fingerprint="NOT_CONFIGURED"),
        )


def test_legacy_absent_url_refuses_before_lease_or_host_snapshot_reads() -> None:
    witness_calls: list[str] = []
    lease = cleanup.BocaJobLease(_ATTEMPT, -1, -1, True)
    with pytest.raises(PostflightNoGo):
        capture_postflight(
            _expected(site_url_fingerprint="NOT_CONFIGURED"),
            lease,
            read_snapshot=lambda _: witness_calls.append("read") or _snapshot(),
            verify_lease=lambda *_: witness_calls.append("lease"),
        )
    assert witness_calls == []


def test_r252_technical_health_is_separate_versioned_non_promoting_receipt() -> None:
    raw, evidence = _technical_capture()
    assert evidence == ["lease", "read", "lease", "read", "lease"]
    assert len(raw) <= 8192
    assert raw.startswith(b"BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2 ")
    body = json.loads(raw.split(b" ", 1)[1])
    assert body["schema"] == 2
    assert body["state"] == "TECHNICAL_PROOF_ONLY"
    assert body["panel"] == {
        "origin": "http://localhost:8443",
        "probe": "HEALTH_HTTP_200",
        "scope": "LOOPBACK_HEALTH_ONLY",
    }
    assert body["monitor"] == {
        "source": "NOT_CONNECTED",
        "observations": 0,
        "provider_attested": False,
        "owner_monitor": "NOT_ATTESTED",
        "semantics": "NO_MONITOR_SESSION_OBSERVED",
    }
    assert body["passkey_chrome"] == "NOT_ATTESTED"
    assert body["beta_deploy"] == "NO_GO"
    assert body["observer_writes"] == 0 and body["foreign_resources_touched"] == 0
    assert verify_technical_postflight(raw, _expected()) == raw
    with pytest.raises(PostflightNoGo):
        verify_postflight(raw, _expected())


@pytest.mark.parametrize(
    "change",
    (
        {"panel_loopback_probe": "LOGIN_HTTP_200"},
        {"panel_loopback_probe": "HEALTH_HTTP_302"},
        {"monitor_source": "IN_MEMORY", "monitor_observation_count": 0},
        {"monitor_source": "NOT_CONNECTED", "monitor_observation_count": 2},
        {"site_url_saved_fingerprint": "f" * 64},
        {"rootless_uid": 0},
    ),
)
def test_r252_technical_refuses_login_substitution_tokens_and_other_drift(
    change: dict[str, Any],
) -> None:
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        _technical_capture(replace(_snapshot(panel_loopback_probe="HEALTH_HTTP_200"), **change))


def test_r252_technical_verifier_refuses_tamper_and_legacy_replay() -> None:
    raw, _ = _technical_capture()
    body = json.loads(raw.split(b" ", 1)[1])
    for path, replacement in (
        (("passkey_chrome",), "VERIFIED"),
        (("beta_deploy",), "GO"),
        (("monitor", "owner_monitor"), "ATTESTED"),
        (("monitor", "source"), "IN_MEMORY"),
        (("panel", "scope"), "OWNER_AUTHENTICATED"),
        (("state",), "ACCEPTED"),
        (("schema",), 1),
    ):
        forged = json.loads(json.dumps(body))
        current = forged
        for key in path[:-1]:
            current = current[key]
        current[path[-1]] = replacement
        altered = b"BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2 " + _json(forged) + b"\n"
        with pytest.raises(PostflightNoGo):
            verify_technical_postflight(altered, _expected())
    with pytest.raises(PostflightNoGo):
        verify_technical_postflight(
            raw.replace(b'"schema":2', b'"schema":2,"schema":2'), _expected()
        )
    legacy, _ = _capture()
    with pytest.raises(PostflightNoGo):
        verify_technical_postflight(legacy, _expected())


def test_r252_technical_requires_fresh_identical_witnesses_and_live_lease() -> None:
    with pytest.raises(PostflightNoGo):
        _technical_capture(
            second=_snapshot(
                panel_loopback_probe="HEALTH_HTTP_200",
                site_url_saved_fingerprint="f" * 64,
            )
        )
    lease = cleanup.BocaJobLease(_ATTEMPT, -1, -1, True)
    calls = 0

    def lost(_lease: cleanup.BocaJobLease, _attempt: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("lost lease")

    with pytest.raises(PostflightNoGo):
        capture_technical_postflight(
            _expected(),
            lease,
            read_snapshot=lambda _: _snapshot(panel_loopback_probe="HEALTH_HTTP_200"),
            verify_lease=lost,
        )


def test_postflight_technical_receipt_is_bounded_canonical_and_never_claims_physical_passkey() -> (
    None
):
    raw, checks = _capture()
    assert len(checks) >= 3
    assert len(raw) <= 8192
    assert raw.startswith(b"BOCA_PAIR_POSTFLIGHT ") and raw.endswith(b"\n")
    body = json.loads(raw.removeprefix(b"BOCA_PAIR_POSTFLIGHT "))
    assert body["state"] == "TECHNICAL_ACCEPT"
    assert body["beta_deploy"] == "NO_GO"
    assert body["passkey_chrome"] == "NOT_ATTESTED"
    assert body["site_url"]["startup"] == "READ_FRESH_FILE_AT_NEXT_START"
    assert body["monitor"]["source"] == "NOT_CONNECTED"
    assert body["monitor"]["observations"] == 0
    assert body["cleanup"]["r108"] == "RETAINED_ATTESTED"
    assert b"SITE_URL=" not in raw and b"credential" not in raw
    assert verify_postflight(raw, _expected()) == raw


def test_postflight_is_fail_closed_on_missing_capture_or_protected_lease_checker() -> None:
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        capture_postflight(
            _expected(),
            cleanup.BocaJobLease(_ATTEMPT, -1, -1, True),
            read_snapshot=None,
            verify_lease=None,
        )  # type: ignore[arg-type]


def test_postflight_detects_changed_second_snapshot_under_same_lease() -> None:
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        _capture(second=_snapshot(site_url_worker_mirror_fingerprint="b" * 64))


@pytest.mark.parametrize(
    "change",
    (
        {"rootless_uid": 0},
        {"rootless_gid": 988},
        {"panel_loopback_probe": "EXTERNALLY_BOUND"},
        {"site_url_saved_fingerprint": "b" * 64},
        {"site_url_worker_mirror_fingerprint": "b" * 64},
        {"site_url_worker_mirror_fingerprint": ""},
        {"worker_site_url_startup": "APPLIED"},
        {"monitor_source": "EXTERNAL_PROVIDER"},
        {"monitor_observation_count": 9},
        {"storage_after": replace(_STORAGE, key_inode_sha256="f" * 64)},
        {"storage_after": replace(_STORAGE, owner_session_inode_sha256="f" * 64)},
        {"storage_after": replace(_STORAGE, sqlite_inode_sha256="f" * 64)},
        {"retained": replace(_PINS, ipc_inode_sha256="f" * 64)},
        {"cleanup_receipt_sha256": "f" * 64},
        {
            "binding": replace(
                PostflightBinding(
                    _ATTEMPT, _SOURCE, _CONTROLLER_ID, _WORKER_ID, _CONTROLLER_REF, _WORKER_REF
                ),
                controller_id="f" * 64,
            )
        },
    ),
)
def test_postflight_rejects_inconsistent_or_missing_physical_witness(
    change: dict[str, Any],
) -> None:
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        _capture(_snapshot(**change))


@pytest.mark.parametrize(
    "role,changes",
    (
        (0, {"health": "unhealthy"}),
        (0, {"running": False, "status": "exited", "pid": 0}),
        (0, {"container_id": "e" * 64}),
        (0, {"image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64}),
        (0, {"image_id": "sha256:" + "e" * 64}),
        (0, {"port_8443": "NONE"}),
        (1, {"running": True, "status": "running", "pid": 1234}),
        (1, {"status": "exited", "exit_code": 1}),
        (1, {"container_id": "f" * 64}),
        (1, {"image_id": "sha256:" + "f" * 64}),
    ),
)
def test_postflight_does_not_accept_unhealthy_wrong_pair_or_exited_worker(
    role: int, changes: dict[str, Any]
) -> None:
    value = _pair_value()
    value["services"][role].update(changes)
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        _capture(_snapshot(pair_receipt=_pair_bytes(value)))


@pytest.mark.parametrize("missing", (_IPC, _SITE))
def test_postflight_requires_ipc_and_site_volumes_in_both_roles(missing: str) -> None:
    value = _pair_value()
    value["services"][1]["volumes"].remove(missing)
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        _capture(_snapshot(pair_receipt=_pair_bytes(value)))


def test_postflight_refuses_absent_or_forged_cleanup_r108_receipt() -> None:
    body = json.loads(_cleanup_receipt())
    body["retained_attested"] = []
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        _capture(expected=_expected(cleanup_receipt=_json(body)))


@pytest.mark.parametrize("status", ("NO_GO", "INDETERMINATE"))
def test_postflight_refuses_cleanup_that_never_accepted(status: str) -> None:
    body = json.loads(_cleanup_receipt())
    body["status"] = status
    body["protected_pair"] = None
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        _capture(expected=_expected(cleanup_receipt=_json(body)))


def test_postflight_verifier_rejects_tamper_extras_noncanonical_and_duplicates() -> None:
    raw, _ = _capture()
    value = json.loads(raw.removeprefix(b"BOCA_PAIR_POSTFLIGHT "))
    value["passkey_chrome"] = "VERIFIED_ON_TABLET"
    changed = b"BOCA_PAIR_POSTFLIGHT " + _json(value) + b"\n"
    for candidate in (
        changed,
        raw.replace(b'"schema":1', b'"schema":1,"schema":1', 1),
        raw.replace(b'"schema":1', b'"schema": 1', 1),
        raw.replace(b'"state":"TECHNICAL_ACCEPT"', b'"state":"GREEN"', 1),
        raw + b"\n",
    ):
        with pytest.raises(PostflightNoGo, match="NO_GO"):
            verify_postflight(candidate, _expected())


def test_postflight_verifier_rejects_a_different_release_or_inventory_baseline() -> None:
    raw, _ = _capture()
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        verify_postflight(raw, _expected(site_url_fingerprint="d" * 64))
    with pytest.raises(PostflightNoGo, match="NO_GO"):
        verify_postflight(
            raw, _expected(storage_before=replace(_STORAGE, sqlite_inode_sha256="f" * 64))
        )


def test_postflight_cannot_assert_success_from_a_report_with_unverified_lease() -> None:
    lease = cleanup.BocaJobLease(_ATTEMPT, -1, -1, True)
    seen = 0

    def verifier(_lease: cleanup.BocaJobLease, _attempt: str) -> None:
        nonlocal seen
        seen += 1
        if seen == 2:
            raise RuntimeError("lease lost")

    with pytest.raises(PostflightNoGo, match="NO_GO"):
        capture_postflight(
            _expected(), lease, read_snapshot=lambda _lease: _snapshot(), verify_lease=verifier
        )
