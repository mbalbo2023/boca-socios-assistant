"""R255 two-phase production-read-only postflight expectation, CODE_ONLY.

Capture a stable old pair, three Boca-only volume identities, storage metadata
and the saved SITE_URL state/digest *while the old controller still runs*, before
PARK. After a separately completed, official SUCCESS cleanup, derive new CIDs
and image IDs from the actual R177 pair and systemd binding. No user/form CID
is accepted. This module cannot invoke APPLY, park a pair, create a container,
write an owner receipt or attest a passkey/monitor. Inclusion in the protected
pair ZIP does not authorize APPLY. The structural V2 reader requires a live
pidfd/namespace-bound mapped-owner proof and fails closed without one; actual
rootless custody still requires independent physical evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_postflight_sources_v2 as sources_v2
from boca_socios import host_boca_rootless_mapped_custody as mapped
from boca_socios import host_boca_successor_integrations as integration
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_postflight_runtime as runtime
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_repeatable_journal import FreshPairWitness


class PreParkExpectedNoGo(ValueError):
    """Fixed category: never expose rootless metadata, URL or Docker errors."""


def _fail() -> PreParkExpectedNoGo:
    return PreParkExpectedNoGo("BOCA_PREPARK_EXPECTED_V2 NO_GO")


SiteUrlState = Literal["ATTESTED", "NOT_CONFIGURED"]
_CID = re.compile(r"[a-f0-9]{64}\Z")


def _old_site_custody(plan: transaction.PairCoordinates) -> tuple[SiteUrlState, str | None]:
    """Distinguish a saved digest from genuinely absent old-controller URL.

    This is the reviewed R247 fixed `-I -B` read-only source, never a browser
    navigation, HTTP probe or a user-supplied address. Missing configuration
    is explicitly `NOT_CONFIGURED`, never a synthesized digest. That allows
    future *technical* cold-worker installation of the broken-form fix,
    but by construction cannot produce URL-dependent BETA acceptance.
    """
    try:
        raw = cleanup._docker(
            "exec",
            "--user",
            "10001:10001",
            plan.old_controller_id,
            "/app/.venv/bin/python",
            "-I",
            "-B",
            "-c",
            runtime._SAVED_URL_PROBE,
        )
        # The reviewed inline script prints this ONE exact sentinel only when
        # SiteUrlSettingsStore.read() genuinely returned None. Any unsafe
        # volume/file/URL raises inside Docker and is a hard NO_GO instead.
        if raw == "BOCA_SITE_URL_NOT_CONFIGURED\n":
            return "NOT_CONFIGURED", None
        found = runtime._SITE_FRAME.fullmatch(raw)
        if found is None:
            raise _fail()
        return "ATTESTED", found.group(1)
    except Exception:
        raise _fail() from None


def _storage_for_live_controller(
    plan: transaction.PairCoordinates,
    controller_id: str,
    lease: cleanup.BocaJobLease,
) -> postflight.PostflightStorage:
    """Read structural Boca inodes under a live controller's kernel owner map.

    The structural V2 reader excludes mutable SQLite size/times to permit
    ordinary transactions while requiring exact device/inode/owner/mode.
    The owner is derived from the live container's kernel uid_map/gid_map,
    never assumed to be host UID 10001. A positive physical mapping proof
    remains mandatory before a protected operation may be enabled.
    """
    try:
        if (
            type(controller_id) is not str
            or _CID.fullmatch(controller_id) is None
            or runtime._read_rootless_identity() != (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID)
        ):
            raise _fail()
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        first_owner = mapped.read_container_mapped_owner(controller_id)
        host._validate_data_volume()
        host._validate_key_volume()
        host._validate_owner_volume()
        if host._checked_docker_storage_dir() != runtime._ROOT:
            raise _fail()
        item = sources_v2.capture_structural_storage_fingerprints(mapped_owner=first_owner)
        host._validate_data_volume()
        host._validate_key_volume()
        host._validate_owner_volume()
        if mapped.read_container_mapped_owner(controller_id) != first_owner:
            raise _fail()
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        if type(item) is not postflight.PostflightStorage:
            raise _fail()
        item.validate()
        return item
    except Exception:
        raise _fail() from None


def _before_park_storage(
    plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
) -> postflight.PostflightStorage:
    """The old controller is still running at this precise pre-PARK stage."""
    return _storage_for_live_controller(plan, plan.old_controller_id, lease)


def _candidate_storage(
    plan: transaction.PairCoordinates,
    new_controller_id: str,
    new_worker_id: str,
    lease: cleanup.BocaJobLease,
) -> postflight.PostflightStorage:
    """After PARK, bind the structural read to the *new* live controller.

    Only a controller already installed by the same held lease and immutable
    release coordinates may attest these retained Boca volumes. The old PID
    was deliberately stopped and can no longer provide a pidfd witness.
    """
    try:
        if (
            type(plan) is not transaction.PairCoordinates
            or type(new_controller_id) is not str
            or _CID.fullmatch(new_controller_id) is None
            or type(new_worker_id) is not str
            or _CID.fullmatch(new_worker_id) is None
            or len({plan.old_controller_id, plan.old_worker_id, new_controller_id, new_worker_id})
            != 4
        ):
            raise _fail()

        def require_binding() -> None:
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            current = service.read_installed_binding(lease)
            if (
                current.installation_run_id != plan.attempt_id
                or current.source_sha != plan.new_source_sha
                or current.controller_id != new_controller_id
                or current.worker_id != new_worker_id
                or current.controller_image != plan.controller_ref
                or current.worker_image != plan.worker_ref
                or current.pair.sender_id
            ):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)

        require_binding()
        captured = _storage_for_live_controller(plan, new_controller_id, lease)
        require_binding()
        return captured
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class PreParkExpectedSeed:
    """Held-lease old-pair evidence; only a future protected actor can use it.

    The two phase dependency is essential: new IDs do not exist before PARK,
    whereas storage and saved SITE_URL need the still-running original pair.
    A Python object is never a release/authentication capability on its own.
    """

    inputs: integration.BoundSuccessorInputs
    lease: cleanup.BocaJobLease
    storage_before: postflight.PostflightStorage
    site_url_state: SiteUrlState
    site_url_fingerprint: str | None
    old_pair_witness: FreshPairWitness

    @property
    def plan(self) -> transaction.PairCoordinates:
        return self.inputs.plan

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def terminal_accept_authorized(self) -> Literal[False]:
        return False

    def expected_after_cleanup(
        self,
        official_final_cleanup: successor.OneShotFinalCleanupBridge,
        lease: cleanup.BocaJobLease,
    ) -> postflight.PostflightExpected:
        """Bind new pair from physical observer + official SUCCESS V2 only.

        Called after cleanup inside the original lease, never before PARK.
        The actual technical receipt still needs two independent snapshots,
        strict volume/subuid proof, O_EXCL/fsync/readback and owner acceptance.
        """
        try:
            plan = self.plan
            if (
                type(self.inputs) is not integration.BoundSuccessorInputs
                or type(self.storage_before) is not postflight.PostflightStorage
                or type(self.old_pair_witness) is not FreshPairWitness
                or not (
                    self.site_url_state == "NOT_CONFIGURED"
                    and self.site_url_fingerprint is None
                    or self.site_url_state == "ATTESTED"
                    and type(self.site_url_fingerprint) is str
                    and runtime._SITE_FRAME.fullmatch(
                        "BOCA_SITE_URL_SHA256 " + self.site_url_fingerprint + "\n"
                    )
                    is not None
                )
                or lease is not self.lease
                or type(official_final_cleanup) is not successor.OneShotFinalCleanupBridge
            ):
                raise _fail()
            self.old_pair_witness.validate(plan, self.inputs.custody.resources)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            proof = official_final_cleanup.completed_final_cleanup(plan, lease)
            if (
                type(proof) is not cleanup_runtime.DurableFinalCleanupReceipt
                or proof.attempt_id != plan.attempt_id
                or proof.status != "ACCEPT"
                or proof.apply_authorized is not False
                or hashlib.sha256(proof.raw).hexdigest() != proof.sha256
            ):
                raise _fail()
            first_raw = pair.observe(plan.attempt_id)
            pair.verify(first_raw, plan.attempt_id)
            first_binding = service.read_installed_binding(lease)
            binding._attest(plan.attempt_id, first_raw, first_binding)
            second_raw = pair.observe(plan.attempt_id)
            second_binding = service.read_installed_binding(lease)
            if first_raw != second_raw or first_binding != second_binding:
                raise _fail()
            binding._attest(plan.attempt_id, second_raw, second_binding)
            payload = json.loads(second_raw[len(pair._PREFIX) :])
            controller, worker = payload["services"]
            if (
                payload["source_sha"] != plan.new_source_sha
                or payload["attempt_id"] != plan.attempt_id
                or controller["image_ref"] != plan.controller_ref
                or worker["image_ref"] != plan.worker_ref
            ):
                raise _fail()
            expected = postflight.PostflightExpected(
                plan,
                self.inputs.release,
                controller["container_id"],
                worker["container_id"],
                controller["image_id"],
                worker["image_id"],
                self.inputs.custody.resources,
                self.storage_before,
                self.site_url_fingerprint,
                proof.raw,
            )
            postflight._validate_expected(expected)
            postflight._pair_payload(expected, second_raw)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            return expected
        except Exception:
            raise _fail() from None


def capture_prepark_expected_seed(
    inputs: integration.BoundSuccessorInputs,
    lease: cleanup.BocaJobLease,
) -> PreParkExpectedSeed:
    """Capture twice under same lease, before any old-pair PARK/effect.

    Strict production readers are used directly; there is no injected
    function returning an optimistic fingerprint or spoofed Docker identity.
    Current runner provenance must already have been GH-authenticated by the
    separately reviewed `_successor_preflight` bridge. No later method here
    grants APPLY, SUCCESS terminal or BETA acceptance.
    """
    try:
        if (
            type(inputs) is not integration.BoundSuccessorInputs
            or type(lease) is not cleanup.BocaJobLease
            or lease.attempt_id != inputs.plan.attempt_id
        ):
            raise _fail()
        plan = inputs.plan
        plan.validate()
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        capture = physical.SuccessorCurrentPairCapture(
            historical_custody=inputs.custody,
            current_pair_observation=inputs.original_pair_receipt,
        )
        witness_one = capture(plan, lease)
        if type(witness_one) is not FreshPairWitness:
            raise _fail()
        witness_one.validate(plan, inputs.custody.resources)
        storage_one = _before_park_storage(plan, lease)
        site_one = _old_site_custody(plan)
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        storage_two = _before_park_storage(plan, lease)
        site_two = _old_site_custody(plan)
        witness_two = capture(plan, lease)
        if (
            type(witness_two) is not FreshPairWitness
            or witness_one != witness_two
            or storage_one != storage_two
            or site_one != site_two
        ):
            raise _fail()
        witness_two.validate(plan, inputs.custody.resources)
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        return PreParkExpectedSeed(inputs, lease, storage_two, *site_two, witness_two)
    except Exception:
        raise _fail() from None


def attest_precommit_candidate_site_state(
    plan: transaction.PairCoordinates,
    new_controller_id: str,
    new_worker_id: str,
    lease: cleanup.BocaJobLease,
    seed: PreParkExpectedSeed,
) -> None:
    """Additional PRE-MARKER veto: two true candidate saved/mirror URL reads.

    This is called only after the backend's full candidate topology/binding
    validation and before the irreversible commit marker. It observes the
    temporary FOUR-CID graph, not R177's final two-CID postflight. It does
    not replace either backend custody checks or the later official SUCCESS
    cleanup and technical postflight. No candidate start/network/write/GO.
    """
    try:
        if (
            type(plan) is not transaction.PairCoordinates
            or type(seed) is not PreParkExpectedSeed
            or seed.plan is not plan
            or lease is not seed.lease
            or type(new_controller_id) is not str
            or _CID.fullmatch(new_controller_id) is None
            or type(new_worker_id) is not str
            or _CID.fullmatch(new_worker_id) is None
            or len({plan.old_controller_id, plan.old_worker_id, new_controller_id, new_worker_id})
            != 4
            or not (
                seed.site_url_state == "NOT_CONFIGURED"
                and seed.site_url_fingerprint is None
                or seed.site_url_state == "ATTESTED"
                and type(seed.site_url_fingerprint) is str
                and runtime._SITE_FRAME.fullmatch(
                    "BOCA_SITE_URL_SHA256 " + seed.site_url_fingerprint + "\n"
                )
                is not None
            )
        ):
            raise _fail()
        plan.validate()
        seed.old_pair_witness.validate(plan, seed.inputs.custody.resources)
        expected_ids = {
            plan.old_controller_id,
            plan.old_worker_id,
            new_controller_id,
            new_worker_id,
        }

        def current_binding() -> None:
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            current_ids = cleanup._ids("ps", "-a", "-q", "--no-trunc")
            if (
                type(current_ids) is not list
                or len(current_ids) != 4
                or set(current_ids) != expected_ids
            ):
                raise _fail()
            current = service.read_installed_binding(lease)
            if (
                current.installation_run_id != plan.attempt_id
                or current.source_sha != plan.new_source_sha
                or current.controller_id != new_controller_id
                or current.worker_id != new_worker_id
                or current.controller_image != plan.controller_ref
                or current.worker_image != plan.worker_ref
                or current.pair.sender_id
            ):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)

        def read_candidate(script: str) -> str:
            raw = cleanup._docker(
                "exec",
                "--user",
                "10001:10001",
                new_controller_id,
                "/app/.venv/bin/python",
                "-I",
                "-B",
                "-c",
                script,
            )
            if seed.site_url_state == "NOT_CONFIGURED":
                if raw != "BOCA_SITE_URL_NOT_CONFIGURED\n":
                    raise _fail()
            else:
                matched = runtime._SITE_FRAME.fullmatch(raw)
                if matched is None or matched.group(1) != seed.site_url_fingerprint:
                    raise _fail()
            return raw

        first: tuple[str, str] | None = None
        for _ in range(2):
            current_binding()
            observed = (
                read_candidate(runtime._SAVED_URL_PROBE),
                read_candidate(runtime._MIRRORED_URL_PROBE),
            )
            current_binding()
            if first is None:
                first = observed
            elif first != observed:
                raise _fail()
    except Exception:
        raise _fail() from None
