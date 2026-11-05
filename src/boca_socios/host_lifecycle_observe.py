"""READ_ONLY host observation for accessible Boca lifecycle GO PREPARE (#366).

This host-only CLI does not request, claim, acknowledge, start, stop, deploy,
migrate or contact the Boca website. A separately reviewed GitHub release
provides source SHA and immutable image digests. The dedicated Boca rootless
Docker inventory supplies observed IDs, Compose config hashes and data mount.
The current owner REQUESTED intent is read from legacy SQLite in mode=ro.
Only a future protected PREPARE workflow may turn this public observation into
a reviewable artifact; this module never approves a GO.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_lifecycle as lifecycle
from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    protected_boca_job_lease,
    verify_protected_boca_job_lease,
)
from boca_socios.panel import lifecycle_intents as panel

_SOURCE = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_B64URL = re.compile(r"[A-Za-z0-9_-]{1,2750}\Z")
_CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_BROWSER = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
_VERSION = "boca-lifecycle-observe-v1"
_PUBLIC_VERSION = "boca-protected-action-v1"
_INPUT_KEYS = frozenset(
    {
        "version",
        "source_sha",
        "controller_image",
        "worker_image",
        "release_run_id",
        "observe_run_id",
    }
)
_COMPOSE_LABEL = "com.docker.compose.project"
_SERVICE_LABEL = "com.docker.compose.service"
_CONFIG_LABEL = "com.docker.compose.config-hash"
_SOURCE_LABEL = "org.opencontainers.image.revision"
_ATTEMPT_LABEL = "boca.socios.browser-ipc-attempt"
_TELEGRAM_ATTEMPT = "boca.socios.telegram-runtime-attempt"
_MAX_OUTSTANDING_REQUESTS = 1024


class LifecycleObservationNoGo(ValueError):
    """Observed Boca host/request cannot produce a reviewable PREPARE context."""


@dataclass(frozen=True, slots=True)
class ReviewedObserveRelease:
    """Only pins independently validated by the workflow's two release artifacts."""

    source_sha: str
    controller_image: str
    worker_image: str
    release_run_id: str
    observe_run_id: str

    def require(self) -> None:
        if (
            any(
                type(value) is not str
                for value in (
                    self.source_sha,
                    self.controller_image,
                    self.worker_image,
                    self.release_run_id,
                    self.observe_run_id,
                )
            )
            or not _SOURCE.fullmatch(self.source_sha)
            or not _CONTROLLER.fullmatch(self.controller_image)
            or not _BROWSER.fullmatch(self.worker_image)
            or not _RUN.fullmatch(self.release_run_id)
            or not _RUN.fullmatch(self.observe_run_id)
            or self.release_run_id == self.observe_run_id
        ):
            raise LifecycleObservationNoGo("Boca independently reviewed release pins unavailable")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise LifecycleObservationNoGo("duplicate Boca observe input field")
        output[key] = value
    return output


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def decode_observe_input(encoded: str) -> ReviewedObserveRelease:
    """One compact runner-owned canonical context; never a browser input/GO."""
    if type(encoded) is not str or not _B64URL.fullmatch(encoded):
        raise LifecycleObservationNoGo("Boca observer input encoding invalid")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if (
            not 0 < len(raw) <= 2048
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != encoded
        ):
            raise ValueError("noncanonical base64url")
        obj = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        if (
            type(obj) is not dict
            or set(obj) != _INPUT_KEYS
            or any(type(value) is not str for value in obj.values())
            or _canonical(obj) != raw
            or obj["version"] != _VERSION
        ):
            raise ValueError("noncanonical observe input")
        pins = ReviewedObserveRelease(
            source_sha=obj["source_sha"],
            controller_image=obj["controller_image"],
            worker_image=obj["worker_image"],
            release_run_id=obj["release_run_id"],
            observe_run_id=obj["observe_run_id"],
        )
        pins.require()
        return pins
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, OverflowError):
        raise LifecycleObservationNoGo("Boca observer protected context invalid") from None


def _selected_services(
    inventory: cleanup.Inventory, release: ReviewedObserveRelease
) -> tuple[cleanup.Container, cleanup.Container, cleanup.Container | None, adapter.ReviewedInstalledPair]:
    """Read only the Boca daemon's positively enumerated 2/3 service objects."""
    if not isinstance(inventory, cleanup.Inventory) or len(inventory.containers) not in (2, 3):
        raise LifecycleObservationNoGo("Boca installed controller/worker topology absent")
    services: dict[str, cleanup.Container] = {}
    labels_by_service: dict[str, dict[str, str]] = {}
    for item in inventory.containers:
        if not isinstance(item, cleanup.Container):
            raise LifecycleObservationNoGo("Boca host inventory malformed")
        labels = adapter._labels(item)  # noqa: SLF001 - same Boca rootless attestor
        service = labels.get(_SERVICE_LABEL, "")
        if (
            service not in ("controller", "browser-worker", "telegram")
            or service in services
            or labels.get(_COMPOSE_LABEL) != "boca-socios"
            or labels.get(_SOURCE_LABEL) != release.source_sha
            or item.name != f"/boca-socios-{service}-1"
            or not _HASH.fullmatch(labels.get(_CONFIG_LABEL, ""))
            or not _RUN.fullmatch(labels.get(_ATTEMPT_LABEL, ""))
        ):
            raise LifecycleObservationNoGo("Boca installed Compose provenance unavailable")
        services[service] = item
        labels_by_service[service] = labels
    if set(services) not in ({"controller", "browser-worker"}, {"controller", "browser-worker", "telegram"}):
        raise LifecycleObservationNoGo("Boca installed service set changed")
    controller = services["controller"]
    worker = services["browser-worker"]
    sender = services.get("telegram")
    first = labels_by_service["controller"]
    second = labels_by_service["browser-worker"]
    if first[_ATTEMPT_LABEL] != second[_ATTEMPT_LABEL]:
        raise LifecycleObservationNoGo("Boca original browser attempt diverged")
    third = labels_by_service.get("telegram", {})
    if sender is not None and (
        third.get(_ATTEMPT_LABEL) != first[_ATTEMPT_LABEL]
        or not _RUN.fullmatch(third.get(_TELEGRAM_ATTEMPT, ""))
    ):
        raise LifecycleObservationNoGo("Boca sender attempt provenance unavailable")
    pair = adapter.ReviewedInstalledPair(
        original_browser_attempt=first[_ATTEMPT_LABEL],
        controller_config_hash=first[_CONFIG_LABEL],
        worker_config_hash=second[_CONFIG_LABEL],
        sender_id=sender.ident if sender is not None else "",
        sender_config_hash=third.get(_CONFIG_LABEL, ""),
        sender_attempt_id=third.get(_TELEGRAM_ATTEMPT, ""),
        sender_running=sender.running if sender is not None else False,
    )
    pair.require()
    return controller, worker, sender, pair


def _pending_readonly(path: Path) -> panel.LifecycleIntent:
    """Verify legacy migrations, one unresolved REQUESTED and no database writes."""
    before = lifecycle._identity(path)  # noqa: SLF001 - same owner-only DB identity
    try:
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("BEGIN")
            if lifecycle._identity(path) != before:  # noqa: SLF001
                raise LifecycleObservationNoGo("Boca lifecycle SQLite identity changed")
            versions = connection.execute(
                "SELECT version,checksum FROM schema_migrations ORDER BY version LIMIT 9"
            ).fetchall()
            expected = lifecycle._reviewed_legacy_migrations()  # noqa: SLF001
            actual = {version for version, _ in versions}
            tables = {
                value[0]
                for value in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if (
                len(versions) > len(expected)
                or len(actual) != len(versions)
                or not lifecycle._REQUIRED_LEGACY.issubset(actual)  # noqa: SLF001
                or any(
                    type(version) is not int
                    or version not in expected
                    or type(checksum) is not str
                    or checksum != expected[version]
                    for version, checksum in versions
                )
                or "audit_events" not in tables
                or "owner_browser_session" in tables
                or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
            ):
                raise LifecycleObservationNoGo("Boca legacy SQLite schema drifted")
            pending = panel.LifecycleIntentStore._current(connection)  # noqa: SLF001
            if pending is None or pending.status != "REQUESTED":
                raise LifecycleObservationNoGo("Boca current owner intent not REQUESTED")
            # Detect an older still-unresolved request, which the normal panel
            # writer would never permit. This observation must not legitimize
            # a direct or concurrent audit-ledger mutation as a single intent.
            actions = tuple(panel._REQUEST_ACTIONS.values())  # noqa: SLF001
            rows = connection.execute(
                "SELECT rowid,audit_id,action FROM audit_events "
                "WHERE action IN (?,?,?,?) ORDER BY rowid DESC LIMIT ?",
                (*actions, _MAX_OUTSTANDING_REQUESTS + 1),
            ).fetchall()
            if len(rows) > _MAX_OUTSTANDING_REQUESTS:
                raise LifecycleObservationNoGo("Boca unresolved lifecycle history unbounded")
            unresolved: list[str] = []
            for rowid, operation_id, action in rows:
                matched = next(
                    (scope for scope, marker in panel._REQUEST_ACTIONS.items() if marker == action),  # noqa: SLF001
                    None,
                )
                if type(rowid) is not int or rowid < 1 or matched is None:
                    raise LifecycleObservationNoGo("Boca observed owner request identity invalid")
                ack_id, ack_applied = panel.host_marker(operation_id, *matched, "APPLIED")
                _, ack_refused = panel.host_marker(operation_id, *matched, "REFUSED")
                ack = connection.execute(
                    "SELECT rowid,action FROM audit_events WHERE audit_id=?", (ack_id,)
                ).fetchone()
                if ack is None:
                    unresolved.append(operation_id)
                elif type(ack[0]) is not int or ack[0] <= rowid or ack[1] not in (
                    ack_applied,
                    ack_refused,
                ):
                    raise LifecycleObservationNoGo("Boca historical ACK state malformed")
            if unresolved != [pending.operation_id]:
                raise LifecycleObservationNoGo("Boca more than one owner request unresolved")
            if lifecycle._identity(path) != before:  # noqa: SLF001
                raise LifecycleObservationNoGo("Boca legacy ledger inode drifted")
            return pending
    except LifecycleObservationNoGo:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, panel.LifecycleStorageUnavailable):
        raise LifecycleObservationNoGo("Boca legacy read-only lifecycle ledger unavailable") from None


def observe_pending_lifecycle(
    release: ReviewedObserveRelease,
    *,
    lease: BocaJobLease,
    io: adapter.LifecycleDockerIO | None = None,
) -> dict[str, str]:
    """Read and reobserve one pending owner intent; no host effect or ACK."""
    if not isinstance(release, ReviewedObserveRelease):
        raise LifecycleObservationNoGo("Boca reviewed observer release required")
    release.require()
    verify_protected_boca_job_lease(lease, release.observe_run_id)
    transport = adapter.ProductionRootlessDockerIO() if io is None else io
    try:
        inventory = transport.inventory()
        controller, worker, sender, pair = _selected_services(inventory, release)
        mount = transport.field("volume", "boca-socios_boca_data", "Mountpoint")
        if (
            type(mount) is not str
            or not Path(mount).is_absolute()
            or ".." in Path(mount).parts
            or Path(mount) == Path("/")
        ):
            raise LifecycleObservationNoGo("Boca exact data mountpoint unavailable")
        path = Path(mount) / "boca.sqlite3"
        probe = adapter.RootlessLifecycleProbe(pair, transport)
        preview = lifecycle.LifecycleHostCoordinates(
            attempt_id=release.observe_run_id,
            request_id="00000000-0000-4000-8000-000000000001",
            component="bot",
            target="stop",
            source_sha=release.source_sha,
            controller_id=controller.ident,
            controller_image=release.controller_image,
            worker_id=worker.ident,
            worker_image=release.worker_image,
            database_path=path,
        )
        probe.observe(preview, lease)
        pending = _pending_readonly(path)
        exact = lifecycle.LifecycleHostCoordinates(
            attempt_id=release.observe_run_id,
            request_id=pending.operation_id,
            component=pending.component,
            target=pending.target,
            source_sha=release.source_sha,
            controller_id=controller.ident,
            controller_image=release.controller_image,
            worker_id=worker.ident,
            worker_image=release.worker_image,
            database_path=path,
        )
        probe.observe(exact, lease)
        latest = _pending_readonly(path)
        if latest != pending:
            raise LifecycleObservationNoGo("Boca owner intent changed during observation")
        verify_protected_boca_job_lease(lease, release.observe_run_id)
        public = {
            "version": _PUBLIC_VERSION,
            "kind": "lifecycle",
            "source_sha": release.source_sha,
            "controller_id": controller.ident,
            "controller_image": release.controller_image,
            "worker_id": worker.ident,
            "worker_image": release.worker_image,
            "browser_attempt": pair.original_browser_attempt,
            "controller_config_hash": pair.controller_config_hash,
            "worker_config_hash": pair.worker_config_hash,
            "data_mountpoint": mount,
            "expected_component": pending.component,
            "expected_target": pending.target,
        }
        if sender is not None:
            public |= {
                "sender_id": pair.sender_id,
                "sender_config_hash": pair.sender_config_hash,
                "sender_attempt_id": pair.sender_attempt_id,
                "sender_state": "on" if pair.sender_running else "off",
            }
        if not 0 < len(_canonical(public)) <= 2048:
            raise LifecycleObservationNoGo("Boca public lifecycle observation oversized")
        return public
    except LifecycleObservationNoGo:
        raise
    except (
        cleanup.CleanupError,
        lifecycle.LifecycleHostUnavailable,
        adapter.LifecycleAdapterNoGo,
        OSError,
        TypeError,
        ValueError,
    ):
        raise LifecycleObservationNoGo("Boca rootless lifecycle observation unverified") from None


def main(argv: list[str] | None = None) -> int:
    """Exactly one public JSON line on PASS; never host data on NO_GO."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("BOCA_LIFECYCLE_OBSERVE state=NO_GO", file=sys.stderr)
        return 3
    try:
        release = decode_observe_input(args[0])
        with protected_boca_job_lease(release.observe_run_id) as lease:
            public = observe_pending_lifecycle(release, lease=lease)
        print(_canonical(public).decode("ascii"))
        return 0
    except Exception:
        print("BOCA_LIFECYCLE_OBSERVE state=NO_GO", file=sys.stderr)
        return 3


def selftest_main() -> int:
    """Check stdlib-only ZIP import and canonical parser without host access."""
    ReviewedObserveRelease(
        source_sha="a" * 40,
        controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        worker_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "c" * 64,
        release_run_id="101",
        observe_run_id="102",
    ).require()
    print("BOCA_LIFECYCLE_OBSERVE_MEMFD state=PASS host=untouched blackbox=excluded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
