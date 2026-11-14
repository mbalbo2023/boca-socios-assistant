"""Unwired, fail-closed successor *finalizer*, not a second deployment engine.

The old R179 actor is never entered by this module. The reusable successor
retains its type-level APPLY interlock. The only ACCEPT path additionally
requires the durable V2 cleanup receipt produced by the SAME `final_cleanup`
invocation, two post-cleanup physical witnesses under the still-held Boca
lease, and an O_EXCL/fsync/readback postflight journal.

There is deliberately no production callback implementation, CLI, network,
Docker dispatcher, or automatic host operation here. The protected runner must
wire genuine authenticated dual releases, R188 retained observations, same-
lease snapshots, exact reviewed bundle and current main SHA, and the real V2
cleanup executor before this type can become eligible in a separate review.
Neither a syntactically valid receipt nor a synthetic test is physical proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as cleanup_v2
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_stage as staging
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_cutover_stage as stage
from boca_socios import host_on_demand_service as on_demand
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_boca_upgrade_cleanup_runtime import DurableFinalCleanupReceipt

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MAX_RECEIPT = 8192
_PAIR_PREFIX = b"BOCA_INSTALLED_PAIR "
_CONTROLLER_VOLUMES = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_browser_ipc",
        "boca-socios_boca_site_config",
    }
)
_WORKER_VOLUMES = frozenset(
    {
        "boca-socios_boca_browser_ipc",
        "boca-socios_boca_site_config",
    }
)


class SuccessorFinalizationNoGo(ValueError):
    """Fixed redacted NO_GO; never propagate untrusted runner/host contents."""


def _fail() -> SuccessorFinalizationNoGo:
    return SuccessorFinalizationNoGo("BOCA_SUCCESSOR_FINALIZATION NO_GO/INDETERMINATE")


@dataclass(frozen=True, slots=True)
class FinalCleanupCoordinates:
    """Already-captured exact physical IDs and Boca-only private receipt dir."""

    controller_id: str
    worker_id: str
    controller_image_id: str
    worker_image_id: str
    receipt_dir: Path
    historical_retained: cleanup.HistoricalRetainedImageProof


CleanupCoordinatesReader = Callable[
    [transaction.PairCoordinates, BocaJobLease], FinalCleanupCoordinates
]


class ProductionFinalCleanupCoordinatesReader:
    """Obtain cleanup coordinates from actual Boca Docker and systemd state.

    Unlike an injected `CleanupCoordinatesReader` fixture, this production
    reader has no caller-supplied IDs, paths or I/O functions. It performs
    two complete rootless, pair, binding and R108 observations *inside* the
    still-held mutation lease. It never calls cleanup or mutates Docker.
    The successor APPLY interlock remains False despite this read-side API.
    """

    def __call__(
        self, plan: transaction.PairCoordinates, lease: BocaJobLease
    ) -> FinalCleanupCoordinates:
        try:
            if type(plan) is not transaction.PairCoordinates:
                raise _fail()
            plan.validate()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)

            def capture() -> tuple[tuple[object, ...], cleanup.HistoricalRetainedImageProof]:
                raw = pair.observe(plan.attempt_id)
                pair.verify(raw, plan.attempt_id)
                observed = json.loads(raw.removeprefix(_PAIR_PREFIX))
                if type(observed) is not dict or type(observed.get("services")) is not list:
                    raise _fail()
                services = observed["services"]
                if len(services) != 2 or any(type(item) is not dict for item in services):
                    raise _fail()
                controller, worker = services
                if (
                    observed.get("source_sha") != plan.new_source_sha
                    or observed.get("attempt_id") != plan.attempt_id
                    or observed.get("ipc_volume") != "BOTH"
                    or (controller.get("service"), worker.get("service"))
                    != ("controller", "browser-worker")
                    or (
                        controller.get("running"),
                        controller.get("health"),
                        controller.get("status"),
                        controller.get("port_8443"),
                    )
                    != (True, "healthy", "running", "LOOPBACK")
                    or type(controller.get("pid")) is not int
                    or controller["pid"] <= 0
                    or (
                        worker.get("running"),
                        worker.get("status"),
                        worker.get("pid"),
                        worker.get("exit_code"),
                        worker.get("port_8443"),
                    )
                    != (False, "created", 0, 0, "NONE")
                    or type(worker.get("pid")) is not int
                    or type(worker.get("exit_code")) is not int
                    or (controller.get("image_ref"), worker.get("image_ref"))
                    != (plan.controller_ref, plan.worker_ref)
                    or not isinstance(controller.get("volumes"), list)
                    or not isinstance(worker.get("volumes"), list)
                    or set(controller["volumes"]) != _CONTROLLER_VOLUMES
                    or set(worker["volumes"]) != _WORKER_VOLUMES
                ):
                    raise _fail()
                installed = on_demand.read_installed_binding(lease)
                binding._attest(plan.attempt_id, raw, installed)
                inventory = cleanup.capture_inventory()
                cleanup._validate_inventory(inventory)
                active = (controller, worker)
                if (
                    len(inventory.containers) != 2
                    or {item.ident for item in inventory.containers}
                    != {controller["container_id"], worker["container_id"]}
                    or {volume.name for volume in inventory.volumes}
                    not in (
                        _CONTROLLER_VOLUMES,
                        _CONTROLLER_VOLUMES | {"boca-socios_boca_telegram"},
                    )
                    or {network.name for network in inventory.networks}
                    != {"boca-socios_boca_private", "boca-socios_boca_browser_egress"}
                    or cleanup.HISTORICAL_RETIRE_TARGET not in inventory.global_image_ids
                ):
                    raise _fail()
                images = {image.ident: image for image in inventory.images}
                for observed_service in active:
                    # Match by exact CID, never by tuple order or a Docker name
                    # supplied by the caller.
                    exact = next(
                        (
                            c
                            for c in inventory.containers
                            if c.ident == observed_service["container_id"]
                        ),
                        None,
                    )
                    if (
                        exact is None
                        or exact.image_id != observed_service["image_id"]
                        or exact.running is not observed_service["running"]
                        or frozenset(exact.volumes) != frozenset(observed_service["volumes"])
                        or images.get(exact.image_id) is None
                        or images[exact.image_id].source != cleanup.BOCA_SOURCE
                        or observed_service["image_ref"] not in images[exact.image_id].references
                    ):
                        raise _fail()
                if set(inventory.global_image_ids) != {image.ident for image in inventory.images}:
                    raise _fail()
                historical = cleanup.attest_historical_retained_image(inventory)
                if historical != cleanup.HistoricalRetainedImageProof(
                    cleanup.HISTORICAL_RETIRE_TARGET,
                    cleanup.HISTORICAL_RETIRE_DIGEST,
                    cleanup.HISTORICAL_RETIRE_REVISION,
                ):
                    raise _fail()
                identity = (
                    raw,
                    installed,
                    inventory.containers,
                    inventory.images,
                    inventory.networks,
                    inventory.volumes,
                    inventory.global_image_ids,
                )
                cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
                return identity, historical

            first, first_r108 = capture()
            second, second_r108 = capture()
            if first != second or first_r108 != second_r108:
                raise _fail()
            final_pair_raw = first[0]
            if type(final_pair_raw) is not bytes:
                raise _fail()
            final_pair = json.loads(final_pair_raw.removeprefix(_PAIR_PREFIX))
            controller, worker = final_pair["services"]
            result = FinalCleanupCoordinates(
                controller_id=controller["container_id"],
                worker_id=worker["container_id"],
                controller_image_id=controller["image_id"],
                worker_image_id=worker["image_id"],
                receipt_dir=stage.ROOT,
                historical_retained=first_r108,
            )
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            return result
        except Exception:
            raise _fail() from None


class OneShotFinalCleanupBridge:
    """Make `final_cleanup` and its typed completion ONE indivisible call.

    An injected reviewed function may execute V2 cleanup *once*; this bridge
    stores its exact return in memory and exposes a read-only completed receipt
    to the gated finalizer under the identical plan/lease object. There is no
    path that reparses arbitrary workflow text as a successful cleanup.
    """

    def __init__(
        self,
        delegate: reusable.RepeatableUpgradeIntegrations,
        *,
        read_cleanup_coordinates: CleanupCoordinatesReader | None,
        verify_lease: postflight.LeaseVerifier | None,
    ) -> None:
        self._delegate = delegate
        self._read_coordinates = read_cleanup_coordinates
        self._verify_lease = verify_lease
        self._started = False
        self._completed: DurableFinalCleanupReceipt | None = None
        self._lease: BocaJobLease | None = None
        self._plan: transaction.PairCoordinates | None = None

    def verify_release(
        self, plan: transaction.PairCoordinates, sources: staging.PairSources, lease: BocaJobLease
    ) -> None:
        return self._delegate.verify_release(plan, sources, lease)

    def retained_resources(
        self, plan: transaction.PairCoordinates, lease: BocaJobLease
    ) -> reusable.RetainedResourcePins:
        return self._delegate.retained_resources(plan, lease)

    def final_cleanup(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> str:
        if self._started:
            raise _fail()
        # Enter the one-way effect boundary BEFORE any potentially mutating
        # callback. A fail-after-effect must never call it again.
        self._started = True
        self._lease = lease
        self._plan = plan
        try:
            if self._read_coordinates is None or self._verify_lease is None:
                raise _fail()
            self._verify_lease(lease, plan.attempt_id)
            coordinates = self._read_coordinates(plan, lease)
            if type(coordinates) is not FinalCleanupCoordinates:
                raise _fail()
            # No function injected by the caller can simply return a forged
            # DurableFinalCleanupReceipt. Only the reviewed official V2
            # executor can produce it, with O_EXCL intent + readback.
            proof = cleanup_runtime.execute_durable_final_cleanup(
                plan,
                lease,
                controller_id=coordinates.controller_id,
                worker_id=coordinates.worker_id,
                controller_image_id=coordinates.controller_image_id,
                worker_image_id=coordinates.worker_image_id,
                receipt_dir=coordinates.receipt_dir,
                historical_retained=coordinates.historical_retained,
            )
            if (
                type(proof) is not DurableFinalCleanupReceipt
                or proof.apply_authorized is not False
                or proof.attempt_id != plan.attempt_id
                or proof.status != "ACCEPT"
                or _DIGEST.fullmatch(proof.sha256) is None
                or _DIGEST.fullmatch(proof.intent_sha256) is None
                or hashlib.sha256(proof.raw).hexdigest() != proof.sha256
            ):
                raise _fail()
            body = cleanup_v2.verify_cleanup_v2_receipt(proof.raw, plan.attempt_id)
            if body["outcome"] != "SUCCESS" or body["status"] != "ACCEPT":
                raise _fail()
            self._verify_lease(lease, plan.attempt_id)
            self._completed = proof
            return "ACCEPT"
        except Exception:
            raise _fail() from None

    def completed_final_cleanup(
        self, plan: transaction.PairCoordinates, lease: BocaJobLease
    ) -> DurableFinalCleanupReceipt:
        if (
            not self._started
            or self._completed is None
            or self._plan is not plan
            or self._lease is not lease
        ):
            raise _fail()
        return self._completed


@dataclass(frozen=True, slots=True)
class SuccessorPostflightGate:
    """Read-only physical postflight + persistent O_EXCL receipt gate.

    Every required callback defaults to None, so absence of production wiring
    is NO_GO. The path FD must refer only to Boca's protected rootless private
    journal directory. Local tests may supply a private temporary directory.
    """

    release: adapters.ReleaseEvidence
    retained: adapters.ResourcePins
    storage_before: postflight.PostflightStorage
    site_url_fingerprint: str
    controller_image_id: str
    worker_image_id: str
    read_snapshot: postflight.SnapshotReader | None = None
    verify_lease: postflight.LeaseVerifier | None = None
    open_receipt_directory: Callable[[], int] | None = None

    @staticmethod
    def _readback(root: int, name: str, digest: str) -> bytes:
        """Resist symlink/hardlink/owner/mode swaps; never discard residue."""
        handle = os.open(
            name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
        )
        try:
            before = os.fstat(handle)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_gid != os.getegid()
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= _MAX_RECEIPT
            ):
                raise _fail()
            raw = os.read(handle, _MAX_RECEIPT + 1)
            after = os.fstat(handle)
            if (
                len(raw) != before.st_size
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_mtime_ns != after.st_mtime_ns
                or hashlib.sha256(raw).hexdigest() != digest
            ):
                raise _fail()
            return raw
        finally:
            os.close(handle)

    def attest(
        self,
        plan: transaction.PairCoordinates,
        lease: BocaJobLease,
        cleanup_receipt: DurableFinalCleanupReceipt,
        controller_id: str,
        worker_id: str,
    ) -> bytes:
        """Return only VERIFIED, durable postflight bytes; no implied BETA GO.

        An uncertain write is terminal INDETERMINATE: retained residue prevents
        replay under the same attempt because O_EXCL must fail on the next try.
        """
        try:
            if (
                type(plan) is not transaction.PairCoordinates
                or type(lease) is not BocaJobLease
                or type(cleanup_receipt) is not DurableFinalCleanupReceipt
                or cleanup_receipt.attempt_id != plan.attempt_id
                or cleanup_receipt.status != "ACCEPT"
                or cleanup_receipt.apply_authorized is not False
                or type(cleanup_receipt.raw) is not bytes
                or type(cleanup_receipt.sha256) is not str
                or _DIGEST.fullmatch(cleanup_receipt.sha256) is None
                or hashlib.sha256(cleanup_receipt.raw).hexdigest() != cleanup_receipt.sha256
                or type(cleanup_receipt.intent_sha256) is not str
                or _DIGEST.fullmatch(cleanup_receipt.intent_sha256) is None
                or self.read_snapshot is None
                or self.verify_lease is None
                or self.open_receipt_directory is None
                or not callable(self.read_snapshot)
                or not callable(self.verify_lease)
                or not callable(self.open_receipt_directory)
            ):
                raise _fail()
            expected = postflight.PostflightExpected(
                plan=plan,
                release=self.release,
                controller_id=controller_id,
                worker_id=worker_id,
                controller_image_id=self.controller_image_id,
                worker_image_id=self.worker_image_id,
                retained=self.retained,
                storage_before=self.storage_before,
                site_url_fingerprint=self.site_url_fingerprint,
                cleanup_receipt=cleanup_receipt.raw,
            )
            # This function verifies final cleanup V2, both installed pair
            # snapshots, immutable SQLite/session and controls, and the lease
            # before, between and after those two snapshots.
            raw = postflight.capture_postflight(
                expected,
                lease,
                read_snapshot=self.read_snapshot,
                verify_lease=self.verify_lease,
            )
            postflight.verify_postflight(raw, expected)
            if len(raw) > _MAX_RECEIPT:
                raise _fail()
            root = self.open_receipt_directory()
            try:
                directory = os.fstat(root)
                if (
                    not stat.S_ISDIR(directory.st_mode)
                    or directory.st_uid != os.geteuid()
                    or directory.st_gid != os.getegid()
                    or stat.S_IMODE(directory.st_mode) != 0o700
                ):
                    raise _fail()
                name = f".boca-pair-upgrade-{plan.attempt_id}.postflight"
                # Strictly no replace, rename or unlink on ambiguous failure.
                stage._create_exclusive(root, name, raw)
                replay = self._readback(root, name, hashlib.sha256(raw).hexdigest())
                if replay != raw:
                    raise _fail()
                postflight.verify_postflight(replay, expected)
                return replay
            finally:
                os.close(root)
        except Exception:
            raise _fail() from None


class PostflightGatedSuccessorBackend(reusable.ReusablePairUpgradeBackend):
    """Strict extension of the existing reusable actor's `finalize` boundary.

    A downstream caller can NEVER create ACCEPTED from cleanup's bare textual
    ACK because this `finalize` returns ACCEPT only after durable postflight.
    APPLY remains forbidden: the engine checks this exact type attribute.
    """

    requires_persistent_receipt = False

    def __init__(
        self,
        sources: staging.PairSources,
        retained: reusable.RetainedResourcePins,
        integrations: reusable.RepeatableUpgradeIntegrations | None,
        *,
        gate: SuccessorPostflightGate | None,
        current_retained: bytes | None = None,
    ) -> None:
        if type(sources) is not staging.PairSources:
            raise _fail()
        super().__init__(sources, retained, integrations, current_retained=current_retained)
        self.successor_postflight_gate = gate
        self._successor_finalization_started = False

    def finalize(
        self,
        plan: transaction.PairCoordinates,
        *,
        commit_started: bool,
        controller_id: str | None,
        worker_id: str | None,
        lease: BocaJobLease,
    ) -> str:
        # Reject before super().finalize might perform ANY cleanup effect.
        if (
            self._successor_finalization_started
            or type(self.successor_postflight_gate) is not SuccessorPostflightGate
            or type(self.integrations) is not OneShotFinalCleanupBridge
        ):
            return "INDETERMINATE" if self._successor_finalization_started else "NO_GO"
        self._successor_finalization_started = True
        # One effectful final cleanup, delegated to the reviewed existing
        # reusable actor; no second cleanup actor or R179 backend call here.
        result = super().finalize(
            plan,
            commit_started=commit_started,
            controller_id=controller_id,
            worker_id=worker_id,
            lease=lease,
        )
        if result != "ACCEPT":
            return result if result in ("NO_GO", "INDETERMINATE") else "INDETERMINATE"
        if not commit_started or controller_id is None or worker_id is None:
            return "INDETERMINATE"
        try:
            integrations = self.integrations
            receipt = integrations.completed_final_cleanup(plan, lease)
            self.successor_postflight_gate.attest(plan, lease, receipt, controller_id, worker_id)
            return "ACCEPT"
        except Exception:
            # Engine cannot construct ACCEPTED; terminal sink cannot fix this.
            # Never try to recreate the pair, re-run cleanup, or roll back.
            return "INDETERMINATE"
