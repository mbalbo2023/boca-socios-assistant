"""Read-only same-lease physical capture for a later Boca pair upgrade.

This is an injectable witness for :class:`SuccessorPairJournal`, NOT an
upgrade entrypoint or authority. The protected caller must separately
authenticate the previous pair observation artifact and R188 retained-resource
custody. A valid-looking dataclass or Actions step summary is not proof of
either origin. In particular, absent authenticated custody fails closed.

The current pair, systemd binding, resource graph, and no-follow control
directory inode are independently re-read while the *upgrade* lease remains
held. No Env, contents of protected mounts, secrets, Docker mutations or
network requests are used. The effectful reusable actor remains interlocked.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_observation_bridge as observation_bridge
from boca_socios import host_boca_upgrade_retained_bridge as retained_bridge
from boca_socios import host_on_demand_service as service
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_ROOTLESS_HOME = "/home/boca-deploy/.local/share/docker"
_CENSUS_FIELDS = frozenset(
    {
        "service",
        "container_id",
        "image_id",
        "image_ref",
        "config_hash",
        "network_name",
        "network_id",
        "volumes",
        "port_8443",
    }
)


class SameLeaseCaptureNoGo(ValueError):
    """Fixed, non-sensitive refusal; no raw host exception crosses boundary."""


def _fail() -> SameLeaseCaptureNoGo:
    return SameLeaseCaptureNoGo("Boca same-lease evidence unverified")


class ProductionRetainedResourceIO:
    """Exact read-only production implementation of the R188 resource IO.

    The existing adapters perform the complete dual inventory, labels,
    topology, mounts, worker state, OCI and pinned inode checks. This class
    only supplies their already-reviewed narrow host field readers.
    """

    def rootless_identity(self) -> tuple[int, int, str]:
        cleanup._rootless_docker_disk_inodes()
        value = json.loads(cleanup._docker("info", "--format", "{{json .DockerRootDir}}"))
        if type(value) is not str:
            raise _fail()
        return os.geteuid(), os.getegid(), value

    def inventory(self) -> cleanup.Inventory:
        return cleanup.capture_inventory()

    def identity(self, name: str) -> str:
        return retained._identity(name)

    def worker_state(self, ident: str) -> object:
        if type(ident) is not str or _HASH.fullmatch(ident) is None:
            raise _fail()
        observed = {
            # The cleanup inventory allowlist intentionally excludes process
            # state. Reuse R177's exact-ID, exact-field READ_ONLY projection
            # without broadening that cleanup interface or reading Config.Env.
            "Status": pair._fields_from_proven_boca(ident, "State.Status"),
            "Running": cleanup._inspect_field("container", ident, "State.Running"),
            "Pid": pair._fields_from_proven_boca(ident, "State.Pid"),
            "ExitCode": pair._fields_from_proven_boca(ident, "State.ExitCode"),
        }
        if (
            observed["Status"] != "created"
            or observed["Running"] is not False
            or type(observed["Pid"]) is not int
            or observed["Pid"] != 0
            or type(observed["ExitCode"]) is not int
            or observed["ExitCode"] != 0
        ):
            raise _fail()
        return observed

    def mounts(self, ident: str) -> object:
        if type(ident) is not str or _HASH.fullmatch(ident) is None:
            raise _fail()
        return cleanup._inspect_field("container", ident, "Mounts")


@dataclass(slots=True)
class _PairBoundIO:
    """Cross-bind two retained inventories to the IDs observed by pair IO."""

    delegate: adapters.RetainedResourceIO
    controller_id: str
    worker_id: str
    controller_image_id: str
    worker_image_id: str

    def rootless_identity(self) -> tuple[int, int, str]:
        return self.delegate.rootless_identity()

    def inventory(self) -> cleanup.Inventory:
        value = self.delegate.inventory()
        if (
            type(value) is not cleanup.Inventory
            or len(value.containers) != 2
            or {c.ident: (c.image_id, c.running) for c in value.containers}
            != {
                self.controller_id: (self.controller_image_id, True),
                self.worker_id: (self.worker_image_id, False),
            }
        ):
            raise _fail()
        return value

    def identity(self, name: str) -> str:
        return self.delegate.identity(name)

    def worker_state(self, ident: str) -> object:
        return self.delegate.worker_state(ident)

    def mounts(self, ident: str) -> object:
        return self.delegate.mounts(ident)


def _decode_pair(raw: bytes, run_id: str) -> dict[str, object]:
    pair.verify(raw, run_id)
    value = json.loads(raw.removeprefix(pair._PREFIX))
    if type(value) is not dict:
        raise _fail()
    return cast(dict[str, object], value)


def _services(value: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    raw = value.get("services")
    if (
        type(raw) is not list
        or len(raw) != 2
        or type(raw[0]) is not dict
        or type(raw[1]) is not dict
    ):
        raise _fail()
    return cast(tuple[dict[str, object], dict[str, object]], (raw[0], raw[1]))


def _fixed_coordinates(value: dict[str, object]) -> tuple[object, ...]:
    controller, worker = _services(value)
    return (
        value["source_sha"],
        value["attempt_id"],
        value["volumes"],
        value["ipc_volume"],
        *(tuple(item[key] for key in sorted(_CENSUS_FIELDS)) for item in (controller, worker)),
    )


def _current_pair_matches(
    plan: transaction.PairCoordinates,
    current: dict[str, object],
    previous: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    if _fixed_coordinates(current) != _fixed_coordinates(previous):
        raise _fail()
    controller, worker = _services(current)
    if (
        current["source_sha"] != plan.old_source_sha
        or current["attempt_id"] != plan.old_attempt_id
        or controller["container_id"] != plan.old_controller_id
        or worker["container_id"] != plan.old_worker_id
        or controller["image_id"] != plan.old_controller_image_id
        or worker["image_id"] != plan.old_worker_image_id
        or controller["running"] is not True
        or controller["status"] != "running"
        or controller["health"] != "healthy"
        or type(controller["pid"]) is not int
        or controller["pid"] <= 0
        or worker["running"] is not False
        or worker["status"] != "created"
        or worker["pid"] != 0
        or worker["exit_code"] != 0
    ):
        raise _fail()
    return controller, worker


def _custody_matches(custody: adapters.CustodyEvidence, plan: transaction.PairCoordinates) -> None:
    if (
        type(custody) is not adapters.CustodyEvidence
        or custody.installed_source_sha != plan.old_source_sha
        or custody.installation_attempt != plan.old_attempt_id
        or type(custody.observation_run_id) is not str
        or _RUN.fullmatch(custody.observation_run_id) is None
        or type(custody.receipt_sha256) is not str
        or _HASH.fullmatch(custody.receipt_sha256) is None
        or type(custody.resources) is not adapters.ResourcePins
        or type(custody.control_directory_inode_sha256) is not str
        or _HASH.fullmatch(custody.control_directory_inode_sha256) is None
    ):
        raise _fail()
    custody.resources.validate()


@dataclass(frozen=True, slots=True)
class ProductionSameLeaseCapture:
    """Callable bridge, expected historical provenance must be trusted upstream.

    `observation_receipt` MUST be byte-for-byte from a protected Actions
    artifact authenticated by the runner for `plan.observation_run_id`.
    `custody` MUST come from the independently authenticated R188 receipt,
    not a guessed label, form, or R189 Step Summary. This class cannot create
    that missing artifact and never treats its absence as a successful proof.

    Physical pair observations use the **current lease attempt** as their
    observation ID; the old run ID in FreshPairWitness remains the provenance
    of the authenticated historical receipt, not a fabricated new run.
    """

    observation_receipt: bytes
    custody: adapters.CustodyEvidence | None
    retained_io: adapters.RetainedResourceIO | None = None
    pair_reader: Callable[[str], bytes] = pair.observe
    binding_reader: Callable[[cleanup.BocaJobLease], OnDemandInstallation] = (
        service.read_installed_binding
    )
    control_identity_reader: Callable[[str], str] = retained._identity

    def __call__(
        self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
    ) -> journal.FreshPairWitness:
        try:
            if type(plan) is not transaction.PairCoordinates or not callable(self.pair_reader):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            plan.validate()
            if self.custody is None:
                raise _fail()  # No authenticated R188 artifact: hard NO_GO.
            _custody_matches(self.custody, plan)
            previous = _decode_pair(self.observation_receipt, plan.observation_run_id)
            if (
                previous["source_sha"] != plan.old_source_sha
                or previous["attempt_id"] != plan.old_attempt_id
            ):
                raise _fail()

            current = _decode_pair(self.pair_reader(plan.attempt_id), plan.attempt_id)
            controller, worker = _current_pair_matches(plan, current, previous)
            installed_first = self.binding_reader(lease)
            installed_second = self.binding_reader(lease)
            if installed_first != installed_second:
                raise _fail()
            binding._attest(plan.attempt_id, pair._canonical(current), installed_first)

            graph = adapters.GraphExpectation(
                (
                    adapters.ExpectedService(
                        plan.old_controller_id,
                        "controller",
                        plan.old_source_sha,
                        plan.old_attempt_id,
                        cast(str, controller["image_ref"]),
                    ),
                    adapters.ExpectedService(
                        plan.old_worker_id,
                        "browser-worker",
                        plan.old_source_sha,
                        plan.old_attempt_id,
                        cast(str, worker["image_ref"]),
                    ),
                )
            )
            base_io: adapters.RetainedResourceIO = (
                self.retained_io if self.retained_io is not None else ProductionRetainedResourceIO()
            )
            observed_pins = adapters.observe_retained(
                self.custody.resources,
                graph,
                plan.attempt_id,
                lease,
                io=_PairBoundIO(
                    base_io,
                    plan.old_controller_id,
                    plan.old_worker_id,
                    plan.old_controller_image_id,
                    plan.old_worker_image_id,
                ),
            )
            first_inode = self.control_identity_reader("control_socket_directory")
            second_inode = self.control_identity_reader("control_socket_directory")
            if (
                first_inode != second_inode
                or first_inode != self.custody.control_directory_inode_sha256
            ):
                raise _fail()
            after = _decode_pair(self.pair_reader(plan.attempt_id), plan.attempt_id)
            _current_pair_matches(plan, after, previous)
            if _fixed_coordinates(after) != _fixed_coordinates(current):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            result = journal.FreshPairWitness(
                observation_run_id=plan.observation_run_id,
                old_attempt_id=plan.old_attempt_id,
                old_source_sha=plan.old_source_sha,
                controller_id=plan.old_controller_id,
                worker_id=plan.old_worker_id,
                controller_image_id=plan.old_controller_image_id,
                worker_image_id=plan.old_worker_image_id,
                retained=observed_pins,
                control_inode_sha256=first_inode,
            )
            result.validate(plan, self.custody.resources)
            return result
        except Exception:
            raise _fail() from None


@dataclass(frozen=True, slots=True)
class AuthenticatedProductionSameLeaseCapture:
    """Protected-bundle entry to the physical witness, with no caller I/O.

    The runner has independently verified each GitHub artifact archive and
    published these exact bytes through the SHA-checked memfd bundle. Here
    both proofs are rechecked *before* any Docker or filesystem read. Unlike
    the testable low-level bridge, the production entry cannot substitute
    fake pair, binding, retained-resource or inode callbacks. The SHA-pinned
    bundle and protected Actions caller remain mandatory trust boundaries.
    """

    observer_main_sha: str
    retained_observation_run_id: str
    pair_proof: bytes
    pair_receipt: bytes
    retained_proof: bytes
    retained_receipt: bytes

    def __call__(
        self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
    ) -> journal.FreshPairWitness:
        try:
            if type(plan) is not transaction.PairCoordinates:
                raise _fail()
            plan.validate()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            observation_bridge.verify_bundled_observation(
                self.pair_proof,
                self.pair_receipt,
                self.observer_main_sha,
                plan.observation_run_id,
                plan.attempt_id,
                plan.release_run_id,
            )
            custody = retained_bridge.verify_bundled_retained(
                self.retained_proof,
                self.retained_receipt,
                self.pair_proof,
                self.pair_receipt,
                self.observer_main_sha,
                self.retained_observation_run_id,
                plan.observation_run_id,
                plan.attempt_id,
                plan.release_run_id,
            )
            # The default source readers below really inspect the rootless
            # Boca daemon, canonical systemd binding and filesystem identities.
            return ProductionSameLeaseCapture(
                observation_receipt=self.pair_receipt,
                custody=custody,
                retained_io=ProductionRetainedResourceIO(),
                pair_reader=pair.observe,
                binding_reader=service.read_installed_binding,
                control_identity_reader=retained._identity,
            )(plan, lease)
        except Exception:
            raise _fail() from None
