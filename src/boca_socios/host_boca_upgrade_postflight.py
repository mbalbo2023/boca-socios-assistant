"""Pure post-cleanup attestation for a *successor* Boca dual-pair upgrade.

The caller obtains the already-finalized cleanup V2 receipt and independent
read-only host snapshots *after* cleanup, under the SAME still-held Boca job
lease. No production reader, lease acquisition, Docker, browser, SQLite read,
network request, secret access, journal write, or deploy entrypoint lives here.

Neither legacy `TECHNICAL_ACCEPT` nor the isolated R252 schema-2
`TECHNICAL_PROOF_ONLY` is owner/passkey acceptance: the worker must remain
CREATED/PID0/Exit0, so its URL mirror is armed for its NEXT explicit start,
not proven consumed. Real Chrome passkey verification and live monitor producer
connectivity cannot be inferred from either receipt; BETA remains NO_GO.

Trust boundaries: `release` must come from the authenticated dual R242 runner;
`read_snapshot` must reuse the existing Boca-only R177/R188/SQLite/control
attestors rather than constructing fields from a workflow form; `verify_lease`
must be `host_boca_cleanup.verify_protected_boca_job_lease` in the protected
host runner. Host must persist/read back these returned canonical bytes via
O_EXCL/fsync before releasing that same lease. Merely calling this function or
constructing its dataclasses never authorizes a deploy or proves a physical
host operation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as cleanup_v2
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios.host_boca_pair_upgrade import PairCoordinates

_PREFIX = b"BOCA_PAIR_POSTFLIGHT "
_TECHNICAL_PREFIX = b"BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2 "
_BOUND = 8192
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_PAIR_PREFIX = b"BOCA_INSTALLED_PAIR "
_SAFE_MONITOR = frozenset(("NOT_CONNECTED", "IN_MEMORY"))
_STARTUP = "READ_FRESH_FILE_AT_NEXT_START"
_PANEL = "LOGIN_HTTP_200"
_TECHNICAL_PANEL = "HEALTH_HTTP_200"
_R108 = "RETAINED_ATTESTED"
_SITE_UNCONFIGURED = "NOT_CONFIGURED"


class PostflightNoGo(ValueError):
    """Fixed refusal: NO_GO/INDETERMINATE, no untrusted host text or PII."""

    state = "NO_GO"
    cleanup = "INDETERMINATE"


def _fail() -> PostflightNoGo:
    return PostflightNoGo("BOCA_POSTFLIGHT state=NO_GO cleanup=INDETERMINATE")


@dataclass(frozen=True, slots=True)
class PostflightStorage:
    """Hashes of device/inode/ownership metadata; NEVER DB/key/session data."""

    sqlite_inode_sha256: str
    key_inode_sha256: str
    owner_session_inode_sha256: str

    def validate(self) -> None:
        if any(
            type(value) is not str or _HEX.fullmatch(value) is None
            for value in (
                self.sqlite_inode_sha256,
                self.key_inode_sha256,
                self.owner_session_inode_sha256,
            )
        ):
            raise _fail()


@dataclass(frozen=True, slots=True)
class PostflightBinding:
    """Restricted projection of `read_installed_binding` and systemd custody."""

    installation_attempt: str
    source_sha: str
    controller_id: str
    worker_id: str
    controller_image_ref: str
    worker_image_ref: str


@dataclass(frozen=True, slots=True)
class PostflightExpected:
    """Authenticated target coordinates and PRE-UPGRADE permanent file inodes.

    `cleanup_receipt` must be created by the FINAL cleanup V2 operation, not a
    precommit prediction or a receipt from an earlier workflow attempt.
    """

    plan: PairCoordinates
    release: adapters.ReleaseEvidence
    controller_id: str
    worker_id: str
    controller_image_id: str
    worker_image_id: str
    retained: adapters.ResourcePins
    storage_before: PostflightStorage
    site_url_fingerprint: str
    cleanup_receipt: bytes


@dataclass(frozen=True, slots=True)
class PostflightSnapshot:
    """Injectable post-cleanup host witness; never raw URLs, secrets, or PII.

    A protected producer must check owner/rootless, exact binding & mounts,
    read only inode metadata and SITE_URL fingerprints, then give R177's strict
    already-verified pair receipt and the durable cleanup-file readback digest.
    """

    pair_receipt: bytes
    binding: PostflightBinding
    rootless_uid: int
    rootless_gid: int
    storage_after: PostflightStorage
    retained: adapters.ResourcePins
    site_url_saved_fingerprint: str
    site_url_worker_mirror_fingerprint: str
    worker_site_url_startup: str
    monitor_source: str
    monitor_observation_count: int
    panel_loopback_probe: str
    cleanup_receipt_sha256: str


SnapshotReader = Callable[[cleanup.BocaJobLease], PostflightSnapshot]
LeaseVerifier = Callable[[cleanup.BocaJobLease, str], None]


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _canonical(value: object, *, prefix: bytes = _PREFIX) -> bytes:
    return (
        prefix
        + json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
        + b"\n"
    )


def _cleanup(expected: PostflightExpected) -> None:
    body = cleanup_v2.verify_cleanup_v2_receipt(expected.cleanup_receipt, expected.plan.attempt_id)
    if (
        body["retained_attested"] != [cleanup_v2._HISTORICAL_ENTRY]
        or body["outcome"] != "SUCCESS"
        or body["status"] != "ACCEPT"
        or body["protected_pair"]
        != {
            "controller": {
                "id": expected.controller_id,
                "image_id": expected.controller_image_id,
                "running": True,
            },
            "worker": {
                "id": expected.worker_id,
                "image_id": expected.worker_image_id,
                "running": False,
            },
        }
    ):
        raise _fail()


def _validate_expected(expected: PostflightExpected) -> None:
    if (
        type(expected) is not PostflightExpected
        or type(expected.plan) is not PairCoordinates
        or type(expected.release) is not adapters.ReleaseEvidence
        or type(expected.retained) is not adapters.ResourcePins
        or type(expected.storage_before) is not PostflightStorage
    ):
        raise _fail()
    expected.plan.validate()
    expected.retained.validate()
    expected.storage_before.validate()
    if (
        (
            expected.release.source_sha,
            expected.release.release_run_id,
            expected.release.controller_ref,
            expected.release.worker_ref,
        )
        != (
            expected.plan.new_source_sha,
            expected.plan.release_run_id,
            expected.plan.controller_ref,
            expected.plan.worker_ref,
        )
        or any(
            type(value) is not str or _HEX.fullmatch(value) is None
            for value in (
                expected.controller_id,
                expected.worker_id,
                expected.release.controller_manifest_sha256,
                expected.release.paired_manifest_sha256,
            )
        )
        or type(expected.site_url_fingerprint) is not str
        or (
            expected.site_url_fingerprint != _SITE_UNCONFIGURED
            and _HEX.fullmatch(expected.site_url_fingerprint) is None
        )
        or any(
            type(value) is not str or _IMAGE.fullmatch(value) is None
            for value in (expected.controller_image_id, expected.worker_image_id)
        )
        or len(
            {
                expected.plan.old_controller_id,
                expected.plan.old_worker_id,
                expected.controller_id,
                expected.worker_id,
            }
        )
        != 4
        or expected.controller_image_id == expected.worker_image_id
        or type(expected.cleanup_receipt) is not bytes
    ):
        raise _fail()
    _cleanup(expected)


def _pair_payload(expected: PostflightExpected, raw: bytes) -> dict[str, object]:
    pair.verify(raw, expected.plan.attempt_id)
    value = json.loads(raw[len(_PAIR_PREFIX) :])
    if not isinstance(value, dict):
        raise _fail()
    services = value["services"]
    controller, worker = services
    if (
        value["source_sha"] != expected.plan.new_source_sha
        or value["attempt_id"] != expected.plan.attempt_id
        or value["ipc_volume"] != "BOTH"
        or (
            controller["container_id"],
            controller["image_id"],
            controller["image_ref"],
        )
        != (expected.controller_id, expected.controller_image_id, expected.plan.controller_ref)
        or (
            worker["container_id"],
            worker["image_id"],
            worker["image_ref"],
        )
        != (expected.worker_id, expected.worker_image_id, expected.plan.worker_ref)
        or controller["running"] is not True
        or controller["status"] != "running"
        or controller["health"] != "healthy"
        or controller["port_8443"] != "LOOPBACK"
        or worker["running"] is not False
        or worker["status"] != "created"
        or worker["pid"] != 0
        or worker["exit_code"] != 0
        or worker["health"] != "none"
        or worker["port_8443"] != "NONE"
        or "boca-socios_boca_browser_ipc" not in worker["volumes"]
        or "boca-socios_boca_site_config" not in worker["volumes"]
    ):
        raise _fail()
    return value


def _validate_snapshot(
    expected: PostflightExpected,
    snapshot: PostflightSnapshot,
    *,
    technical_only: bool = False,
) -> dict[str, object]:
    if (
        type(technical_only) is not bool
        or type(snapshot) is not PostflightSnapshot
        or type(snapshot.binding) is not PostflightBinding
        or type(snapshot.storage_after) is not PostflightStorage
        or type(snapshot.retained) is not adapters.ResourcePins
    ):
        raise _fail()
    snapshot.storage_after.validate()
    snapshot.retained.validate()
    pair_data = _pair_payload(expected, snapshot.pair_receipt)
    if (
        snapshot.binding
        != PostflightBinding(
            expected.plan.attempt_id,
            expected.plan.new_source_sha,
            expected.controller_id,
            expected.worker_id,
            expected.plan.controller_ref,
            expected.plan.worker_ref,
        )
        or type(snapshot.rootless_uid) is not int
        or snapshot.rootless_uid != cleanup.EXPECTED_UID
        or type(snapshot.rootless_gid) is not int
        or snapshot.rootless_gid != cleanup.EXPECTED_GID
        or snapshot.storage_after != expected.storage_before
        or snapshot.retained != expected.retained
        or snapshot.site_url_saved_fingerprint != expected.site_url_fingerprint
        or snapshot.site_url_worker_mirror_fingerprint != expected.site_url_fingerprint
        or not technical_only
        and expected.site_url_fingerprint == _SITE_UNCONFIGURED
        or snapshot.worker_site_url_startup != _STARTUP
        or snapshot.monitor_source not in _SAFE_MONITOR
        or type(snapshot.monitor_observation_count) is not int
        or not 0 <= snapshot.monitor_observation_count <= 100_000
        or snapshot.monitor_source == "NOT_CONNECTED"
        and snapshot.monitor_observation_count != 0
        or technical_only
        and (snapshot.monitor_source != "NOT_CONNECTED" or snapshot.monitor_observation_count != 0)
        or snapshot.panel_loopback_probe != (_TECHNICAL_PANEL if technical_only else _PANEL)
        or snapshot.cleanup_receipt_sha256 != hashlib.sha256(expected.cleanup_receipt).hexdigest()
    ):
        raise _fail()
    return pair_data


def _receipt(
    expected: PostflightExpected,
    snapshot: PostflightSnapshot,
    *,
    technical_only: bool = False,
) -> bytes:
    pair_data = _validate_snapshot(expected, snapshot, technical_only=technical_only)
    panel_info = {"origin": "http://localhost:8443", "probe": snapshot.panel_loopback_probe}
    monitor_info: dict[str, object] = {
        "source": snapshot.monitor_source,
        "observations": snapshot.monitor_observation_count,
        "provider_attested": False,
    }
    site_info: dict[str, object] = {
        "fingerprint": snapshot.site_url_saved_fingerprint,
        "mirror": snapshot.site_url_worker_mirror_fingerprint,
        "startup": snapshot.worker_site_url_startup,
    }
    if technical_only and expected.site_url_fingerprint == _SITE_UNCONFIGURED:
        # Only two independently verified absent files qualify. Never create
        # a synthetic SHA-256 for a URL the owner has not supplied.
        site_info.update(state=_SITE_UNCONFIGURED, fingerprint=None, mirror=None)
    body = {
        "schema": 2 if technical_only else 1,
        "state": "TECHNICAL_PROOF_ONLY" if technical_only else "TECHNICAL_ACCEPT",
        "attempt_id": expected.plan.attempt_id,
        "source_sha": expected.plan.new_source_sha,
        "release_run_id": expected.plan.release_run_id,
        "controller_manifest_sha256": expected.release.controller_manifest_sha256,
        "paired_manifest_sha256": expected.release.paired_manifest_sha256,
        "pair": pair_data,
        "binding": asdict(snapshot.binding),
        "storage": asdict(snapshot.storage_after),
        "retained": asdict(snapshot.retained),
        "rootless_uid": snapshot.rootless_uid,
        "rootless_gid": snapshot.rootless_gid,
        "panel": panel_info,
        "site_url": site_info,
        "monitor": monitor_info,
        "cleanup": {
            "status": "ACCEPT",
            "sha256": snapshot.cleanup_receipt_sha256,
            "r108": _R108,
        },
        "passkey_chrome": "NOT_ATTESTED",
        "beta_deploy": "NO_GO",
        "observer_writes": 0,
        "foreign_resources_touched": 0,
    }
    if technical_only:
        # These fields do not claim a monitored token count. Zero observations
        # means this observer deliberately never opened an owner session.
        panel_info["scope"] = "LOOPBACK_HEALTH_ONLY"
        monitor_info["owner_monitor"] = "NOT_ATTESTED"
        monitor_info["semantics"] = "NO_MONITOR_SESSION_OBSERVED"
    return _canonical(body, prefix=_TECHNICAL_PREFIX if technical_only else _PREFIX)


def capture_postflight(
    expected: PostflightExpected,
    lease: cleanup.BocaJobLease,
    *,
    read_snapshot: SnapshotReader | None,
    verify_lease: LeaseVerifier | None,
) -> bytes:
    """Double-capture post-CLEANUP state under the SAME externally held lease.

    Only the protected run may inject the actual lease verifier and read-only
    observer. No callbacks default to host commands. This function does not
    persist; the protected caller must durable-fsync/readback returned bytes.
    """
    return _capture_postflight(
        expected,
        lease,
        read_snapshot=read_snapshot,
        verify_lease=verify_lease,
        technical_only=False,
    )


def capture_technical_postflight(
    expected: PostflightExpected,
    lease: cleanup.BocaJobLease,
    *,
    read_snapshot: SnapshotReader | None,
    verify_lease: LeaseVerifier | None,
) -> bytes:
    """Versioned technical health proof; never owner/BETA acceptance.

    The read-only producer must supply true loopback /healthz evidence and
    intentionally must not open a monitor or owner authentication session.
    Protected caller remains responsible for durable, same-lease persistence.
    """
    return _capture_postflight(
        expected,
        lease,
        read_snapshot=read_snapshot,
        verify_lease=verify_lease,
        technical_only=True,
    )


def _capture_postflight(
    expected: PostflightExpected,
    lease: cleanup.BocaJobLease,
    *,
    read_snapshot: SnapshotReader | None,
    verify_lease: LeaseVerifier | None,
    technical_only: bool,
) -> bytes:
    try:
        if (
            type(lease) is not cleanup.BocaJobLease
            or read_snapshot is None
            or verify_lease is None
            or not callable(read_snapshot)
            or not callable(verify_lease)
        ):
            raise _fail()
        _validate_expected(expected)
        if not technical_only and expected.site_url_fingerprint == _SITE_UNCONFIGURED:
            raise _fail()
        verify_lease(lease, expected.plan.attempt_id)
        first = read_snapshot(lease)
        _validate_snapshot(expected, first, technical_only=technical_only)
        verify_lease(lease, expected.plan.attempt_id)
        second = read_snapshot(lease)
        _validate_snapshot(expected, second, technical_only=technical_only)
        verify_lease(lease, expected.plan.attempt_id)
        if first != second:
            raise _fail()
        result = _receipt(expected, second, technical_only=technical_only)
        if not 0 < len(result) <= _BOUND:
            raise _fail()
        if technical_only:
            verify_technical_postflight(result, expected)
        else:
            verify_postflight(result, expected)
        return result
    except Exception:
        raise _fail() from None


def verify_postflight(raw: bytes, expected: PostflightExpected) -> bytes:
    """Independent exact-schema verifier; never upgrades BETA to GREEN.

    Offline verification consumes the previously authenticated target and
    durable final CLEANUP receipt supplied by the protected workflow. It is
    integrity validation, NOT independent evidence of a real host capture.
    """
    return _verify_postflight(raw, expected, technical_only=False)


def verify_technical_postflight(raw: bytes, expected: PostflightExpected) -> bytes:
    """Validate schema-v2 technical-only receipt; cannot authorize BETA GO."""
    return _verify_postflight(raw, expected, technical_only=True)


def _verify_postflight(raw: bytes, expected: PostflightExpected, *, technical_only: bool) -> bytes:
    try:
        _validate_expected(expected)
        if not technical_only and expected.site_url_fingerprint == _SITE_UNCONFIGURED:
            raise _fail()
        prefix = _TECHNICAL_PREFIX if technical_only else _PREFIX
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= _BOUND
            or not raw.startswith(prefix)
            or not raw.endswith(b"\n")
            or raw.count(b"\n") != 1
        ):
            raise _fail()
        value = json.loads(raw[len(prefix) :], object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise _fail()
        binding = PostflightBinding(**value["binding"])
        storage = PostflightStorage(**value["storage"])
        retained = adapters.ResourcePins(**value["retained"])
        site = value["site_url"]
        monitor = value["monitor"]
        panel = value["panel"]
        cleanup_info = value["cleanup"]
        if (
            not isinstance(site, dict)
            or not isinstance(monitor, dict)
            or not isinstance(panel, dict)
            or not isinstance(cleanup_info, dict)
        ):
            raise _fail()
        site_saved = site["fingerprint"]
        site_mirror = site["mirror"]
        if technical_only and expected.site_url_fingerprint == _SITE_UNCONFIGURED:
            if (
                site.get("state") != _SITE_UNCONFIGURED
                or site_saved is not None
                or site_mirror is not None
            ):
                raise _fail()
            site_saved = site_mirror = _SITE_UNCONFIGURED
        pair_body = value["pair"]
        snapshot = PostflightSnapshot(
            pair_receipt=_PAIR_PREFIX + _canonical_pair(pair_body) + b"\n",
            binding=binding,
            rootless_uid=value["rootless_uid"],
            rootless_gid=value["rootless_gid"],
            storage_after=storage,
            retained=retained,
            site_url_saved_fingerprint=site_saved,
            site_url_worker_mirror_fingerprint=site_mirror,
            worker_site_url_startup=site["startup"],
            monitor_source=monitor["source"],
            monitor_observation_count=monitor["observations"],
            panel_loopback_probe=panel["probe"],
            cleanup_receipt_sha256=cleanup_info["sha256"],
        )
        if _receipt(expected, snapshot, technical_only=technical_only) != raw:
            raise _fail()
        return raw
    except Exception:
        raise _fail() from None


def _canonical_pair(value: Any) -> bytes:
    """Reconstitute R177 bytes solely to reuse its strict canonical verifier."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
