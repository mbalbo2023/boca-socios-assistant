"""Host-only bridge from an owner REQUESTED row to a verified physical ACK.

This is a host-only CLI/library bridge without an HTTP endpoint, SSH client
or workflow dispatch. Its CLI is inert until a protected caller supplies
independently reviewed exact installed coordinates. Only the *single* protected Boca Actions workflow
may call it after independently authenticating the installed release, exact
host IDs and an operation-specific GO. Passing a dataclass is NOT a GO.

A browser/panel request never becomes APPLIED until the existing rootless
adapter observes the physical result and the legacy ledger confirms the ACK.
No backup, migration, blackbox navigation or other application is involved.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from boca_socios import host_boca_lifecycle as lifecycle
from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    protected_boca_job_lease,
    verify_protected_boca_job_lease,
)
from boca_socios.panel.lifecycle_intents import (
    LifecycleIntent,
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
)


class PhysicalAckUnavailable(ValueError):
    """No reliable protected action/ACK exists; fail closed without a retry."""


@dataclass(frozen=True, slots=True)
class ReviewedLifecycleInstallation:
    """Pins obtained from independently reviewed installed Boca receipts.

    The caller MUST attest these values against the immutable release, actual
    installed containers, Compose config hashes and current main/GO before
    calling this library. They may NOT come from HTTP, browser forms or labels
    accepted in isolation. The adapter validates them again before any effect.
    """

    attempt_id: str
    source_sha: str
    controller_id: str
    controller_image: str
    worker_id: str
    worker_image: str
    database_path: Path
    pair: adapter.ReviewedInstalledPair
    expected_component: Literal["bot", "chromium"] | None = None
    expected_target: Literal["start", "stop"] | None = None

    def coordinates_for(self, request: LifecycleIntent) -> lifecycle.LifecycleHostCoordinates:
        if (
            not isinstance(request, LifecycleIntent)
            or not isinstance(self.pair, adapter.ReviewedInstalledPair)
            or (self.expected_component is None) != (self.expected_target is None)
            or self.expected_component is not None
            and (
                request.component != self.expected_component
                or request.target != self.expected_target
            )
        ):
            raise PhysicalAckUnavailable("Boca reviewed lifecycle scope not proven")
        self.pair.require()
        coordinates = lifecycle.LifecycleHostCoordinates(
            attempt_id=self.attempt_id,
            request_id=request.operation_id,
            component=request.component,
            target=request.target,
            source_sha=self.source_sha,
            controller_id=self.controller_id,
            controller_image=self.controller_image,
            worker_id=self.worker_id,
            worker_image=self.worker_image,
            database_path=self.database_path,
        )
        coordinates.validate()
        return coordinates


@dataclass(frozen=True, slots=True)
class PhysicalLifecycleReceipt:
    """Only terminal legacy ACK fields suitable for redacted Action summaries."""

    attempt_id: str
    request_id: str
    source_sha: str
    component: Literal["bot", "chromium"]
    target: Literal["start", "stop"]
    status: Literal["APPLIED", "REFUSED"]

    @property
    def applied(self) -> bool:
        return self.status == "APPLIED"

    def redacted_json(self) -> str:
        # Never include Docker inspection text, image/host secrets, or personal
        # content from a browser. The two IDs here are public run/request pins.
        return json.dumps(
            {
                "version": 1,
                "scope": "boca-lifecycle",
                "attempt": self.attempt_id,
                "request_id": self.request_id,
                "source_sha": self.source_sha,
                "component": self.component,
                "target": self.target,
                "status": self.status,
                "physical_ack": self.applied,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def _read_current(path: Path) -> LifecycleIntent | None:
    # The host-only attestor refuses absent/changed/unsafe legacy SQLite;
    # never create a file, migrate storage, or open SQLite schema 0008.
    try:
        with lifecycle._controller_ledger(path) as connection:
            return LifecycleIntentStore._current(connection)
    except (
        lifecycle.LifecycleHostUnavailable,
        LifecycleStorageUnavailable,
        OSError,
        ValueError,
        TypeError,
    ):
        raise PhysicalAckUnavailable("Boca legacy owner lifecycle ledger unavailable") from None


def apply_latest_owner_request(
    installed: ReviewedLifecycleInstallation,
    *,
    lease: BocaJobLease,
    io: adapter.LifecycleDockerIO | None = None,
) -> PhysicalLifecycleReceipt:
    """Consume exactly ONE current REQUESTED intent under the held Boca lease.

    The single canonical protected Actions operation must first attest its
    independent GO, immutable release, installed identities and run attempt.
    This function does not grant those privileges and must NOT be exposed as
    an app/server endpoint or executed by a push-based workflow.

    No request or a previously completed/uncertain request => NO_GO with zero
    effects. The existing adapter alone performs CLAIMED/effect/reobserve/ACK;
    its NO_GO is not retried or converted into a success.
    """
    if not isinstance(installed, ReviewedLifecycleInstallation):
        raise PhysicalAckUnavailable("Boca reviewed installation coordinates required")
    verify_protected_boca_job_lease(lease, installed.attempt_id)
    # Attest the rootless Boca pair + actual data-volume mountpoint BEFORE
    # reading any host SQLite path supplied by the protected runner.
    transport = adapter.ProductionRootlessDockerIO() if io is None else io
    preview = LifecycleIntent(
        operation_id="00000000-0000-4000-8000-000000000001",
        component=installed.expected_component or "bot",
        target=installed.expected_target or "stop",
        status="REQUESTED",
        requested_at="1970-01-01 00:00:00",
    )
    try:
        preview_coordinates = installed.coordinates_for(preview)
        adapter.RootlessLifecycleProbe(installed.pair, transport).observe(
            preview_coordinates, lease
        )
    except (lifecycle.LifecycleHostUnavailable, adapter.LifecycleAdapterNoGo):
        raise PhysicalAckUnavailable("Boca rootless installed service preflight absent") from None
    pending = _read_current(installed.database_path)
    if pending is None or pending.status != "REQUESTED":
        raise PhysicalAckUnavailable("no pending owner lifecycle REQUESTED intent")
    try:
        coordinates = installed.coordinates_for(pending)
    except (lifecycle.LifecycleHostUnavailable, adapter.LifecycleAdapterNoGo):
        raise PhysicalAckUnavailable("Boca reviewed lifecycle coordinates invalid") from None
    # The host adapter attests the exact Boca rootless Docker pair and persists
    # CLAIMED before any physical effect, then a terminal/uncertain receipt.
    try:
        status = adapter.execute_requested_lifecycle(
            coordinates,
            binding=installed.pair,
            lease=lease,
            io=transport,
        )
    except adapter.LifecycleEffectUncertain:
        raise PhysicalAckUnavailable("Boca lifecycle physical result uncertain") from None
    except (adapter.LifecycleAdapterNoGo, lifecycle.LifecycleHostUnavailable):
        raise PhysicalAckUnavailable("Boca lifecycle physical effect refused") from None
    verified = _read_current(installed.database_path)
    if (
        verified is None
        or verified.operation_id != pending.operation_id
        or verified.component != pending.component
        or verified.target != pending.target
        or verified.status != status
    ):
        # A physical change might have occurred: never assume success from a
        # returned Python value, and never automatically attempt the effect.
        raise PhysicalAckUnavailable("Boca lifecycle terminal ACK missing or mismatched")
    verify_protected_boca_job_lease(lease, installed.attempt_id)
    return PhysicalLifecycleReceipt(
        attempt_id=installed.attempt_id,
        request_id=coordinates.request_id,
        source_sha=installed.source_sha,
        component=coordinates.component,
        target=coordinates.target,
        status=status,
    )


_CONTEXT_SCHEMA = "boca-protected-action-v1"
_CONTEXT_KEYS = frozenset(
    {
        "version",
        "kind",
        "attempt_id",
        "source_sha",
        "controller_id",
        "controller_image",
        "worker_id",
        "worker_image",
        "browser_attempt",
        "controller_config_hash",
        "worker_config_hash",
        "data_mountpoint",
        "expected_component",
        "expected_target",
    }
)
_SENDER_KEYS = frozenset({"sender_id", "sender_config_hash", "sender_attempt_id", "sender_state"})
_B64URL = re.compile(r"[A-Za-z0-9_-]{1,2750}\Z")


def decode_lifecycle_context(encoded: str) -> ReviewedLifecycleInstallation:
    """Parse one canonical public context; never interpret a token or an input GO.

    The SHA binding, approved actor/release/run, action authorization and
    installed manifest still MUST be independently verified by Actions before
    SSH. This parser only rejects malformed/unexpected host coordinates.
    """
    if type(encoded) is not str or not _B64URL.fullmatch(encoded):
        raise PhysicalAckUnavailable("Boca lifecycle context encoding invalid")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if (
            not 0 < len(raw) <= 2048
            or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != encoded
        ):
            raise ValueError("noncanonical context")

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            output: dict[str, object] = {}
            for key, value in pairs:
                if key in output:
                    raise ValueError("duplicate field")
                output[key] = value
            return output

        obj = json.loads(raw.decode("ascii"), object_pairs_hook=unique)
        if (
            not isinstance(obj, dict)
            or set(obj) not in (_CONTEXT_KEYS, _CONTEXT_KEYS | _SENDER_KEYS)
            or any(type(value) is not str for value in obj.values())
            or json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "ascii"
            )
            != raw
            or obj["version"] != _CONTEXT_SCHEMA
            or obj["kind"] != "lifecycle"
            or obj["expected_component"] not in ("bot", "chromium")
            or obj["expected_target"] not in ("start", "stop")
            or ("sender_state" in obj and obj["sender_state"] not in ("on", "off"))
        ):
            raise ValueError("invalid fields")
        pair = adapter.ReviewedInstalledPair(
            original_browser_attempt=obj["browser_attempt"],
            controller_config_hash=obj["controller_config_hash"],
            worker_config_hash=obj["worker_config_hash"],
            sender_id=obj.get("sender_id", ""),
            sender_config_hash=obj.get("sender_config_hash", ""),
            sender_attempt_id=obj.get("sender_attempt_id", ""),
            sender_running=obj.get("sender_state") == "on",
        )
        installed = ReviewedLifecycleInstallation(
            attempt_id=obj["attempt_id"],
            source_sha=obj["source_sha"],
            controller_id=obj["controller_id"],
            controller_image=obj["controller_image"],
            worker_id=obj["worker_id"],
            worker_image=obj["worker_image"],
            database_path=Path(obj["data_mountpoint"]) / "boca.sqlite3",
            pair=pair,
            expected_component=obj["expected_component"],
            expected_target=obj["expected_target"],
        )
        synthetic = LifecycleIntent(
            operation_id="00000000-0000-4000-8000-000000000001",
            component=obj["expected_component"],
            target=obj["expected_target"],
            status="REQUESTED",
            requested_at="1970-01-01 00:00:00",
        )
        installed.coordinates_for(synthetic)
        return installed
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        binascii.Error,
        lifecycle.LifecycleHostUnavailable,
        adapter.LifecycleAdapterNoGo,
    ):
        raise PhysicalAckUnavailable("Boca lifecycle protected context invalid") from None


def main(argv: list[str] | None = None) -> int:
    """Effectful HOST-ONLY dispatch called only after protected Actions GO.

    The verified ZIP is executed in a memfd; this entrypoint never creates
    another port/container/scheduler, does not contact the Boca website, and
    never accepts credentials. The only positional argument is bounded public
    canonical JSON encoded as base64url. A CLI call by itself is NOT a GO.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print('{"scope":"boca-lifecycle","status":"NO_GO","physical_ack":false}')
        return 3
    try:
        installed = decode_lifecycle_context(args[0])
        with protected_boca_job_lease(installed.attempt_id) as lease:
            receipt = apply_latest_owner_request(installed, lease=lease)
        print(receipt.redacted_json())
        return 0 if receipt.applied else 3
    except Exception:
        # No exception text from Docker/SQLite/host is ever printed in a
        # workflow log. The durable ledger remains authoritative on ambiguity.
        print('{"scope":"boca-lifecycle","status":"NO_GO","physical_ack":false}')
        return 3


def selftest_main() -> int:
    """ZIP import/syntax smoke; no effects, files, Docker or private data."""
    adapter.ReviewedInstalledPair("12345", "a" * 64, "b" * 64).require()
    print("BOCA_LIFECYCLE_MEMFD state=PASS host=untouched blackbox=excluded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
