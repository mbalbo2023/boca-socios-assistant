"""Unwired successor actor: replace containers, retain existing Boca resources.

This module has no CLI and is not in the protected bundle. Its transaction
capability is deliberately FALSE until authenticated provenance, same-lease
retained-resource observation and mandatory cleanup have real adapters.
R188 READ_ONLY evidence is never itself an authorization for this actor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from boca_socios import host_boca_pair_observe as observer
from boca_socios import host_boca_pair_stage as staging
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_backend as historical
from boca_socios import host_boca_sqlite_identity as sqlite
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_replace as binding
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_cleanup import BocaJobLease, verify_protected_boca_job_lease
from boca_socios.host_lifecycle_rootless_adapter import ProductionRootlessDockerIO

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")


class ReusableUpgradeNoGo(ValueError):
    """Fixed, redacted refusal category; no Docker output or member data."""


def _fail() -> ReusableUpgradeNoGo:
    return ReusableUpgradeNoGo("reusable Boca upgrade integration unverified")


@dataclass(frozen=True, slots=True)
class RetainedResourcePins:
    """Resource *creation* origins, never the current pair installation attempt.

    These are equality coordinates, not provenance or authority. The pending
    protected adapter must authenticate R188 and recapture the same resources
    under the actual operation lease before supplying them here.
    """

    ipc_creator_attempt: str
    ipc_inode_sha256: str
    site_creator_attempt: str
    site_inode_sha256: str
    egress_creator_attempt: str
    egress_id: str

    def validate(self) -> None:
        if any(
            type(value) is not str or pattern.fullmatch(value) is None
            for pattern, values in (
                (
                    _RUN,
                    (
                        self.ipc_creator_attempt,
                        self.site_creator_attempt,
                        self.egress_creator_attempt,
                    ),
                ),
                (_HASH, (self.ipc_inode_sha256, self.site_inode_sha256, self.egress_id)),
            )
            for value in values
        ):
            raise _fail()


class RepeatableUpgradeIntegrations(Protocol):
    """No production implementation exists yet. Missing proof must raise.

    verify_release authenticates protected Actions/main/dual OCI manifests,
    exact role digests and same source SHA; labels alone cannot implement it.
    retained_resources rechecks exact labels/inodes/network ID/empty peers,
    no unknown containers or mounts, without requiring exactly two CIDs in
    the temporary four-CID interval. Old control inode belongs to pre-park;
    the replacement control mount must be separately verified before commit.
    final_cleanup is the reviewed SUCCESS-only bridge: call it exclusively
    after the committed new pair and retained pins have been verified. A
    failed/unverified replacement must retain unknown resources and return
    NO_GO/INDETERMINATE until a distinct same-lease FAILURE cleanup bridge
    independently inventories and proves safe removal candidates. ACCEPT
    requires a durable detailed receipt with before/after disk/inodes and
    exact removals; preserve all retained pins.
    """

    def verify_release(
        self, plan: transaction.PairCoordinates, sources: staging.PairSources, lease: BocaJobLease
    ) -> None: ...

    def retained_resources(
        self, plan: transaction.PairCoordinates, lease: BocaJobLease
    ) -> RetainedResourcePins: ...

    def final_cleanup(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> str: ...


class ReusablePairUpgradeBackend(historical.RootlessPairUpgradeBackend):
    """Reuse ordering/compensation; never repeat first-migration provisioning.

    The inherited transaction gate reads this on the concrete TYPE, so even
    supplying callbacks or changing an instance attribute cannot activate it.
    Removing this interlock requires an explicit, reviewed integration change.
    """

    requires_persistent_receipt = False

    def __init__(
        self,
        sources: staging.PairSources,
        retained: RetainedResourcePins,
        integrations: RepeatableUpgradeIntegrations | None = None,
    ) -> None:
        super().__init__(sources)
        if type(retained) is not RetainedResourcePins:
            raise _fail()
        retained.validate()
        self.retained = retained
        self.integrations = integrations

    def _integrations(self) -> RepeatableUpgradeIntegrations:
        if self.integrations is None:
            raise _fail()
        return self.integrations

    def _guard(self, plan: transaction.PairCoordinates, lease: BocaJobLease, state: str) -> None:
        super()._guard(plan, lease, state)
        if state != "NEW":
            self.verify_retained(plan, lease)

    def verify_retained(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        verify_protected_boca_job_lease(lease, plan.attempt_id)
        found = self._integrations().retained_resources(plan, lease)
        if type(found) is not RetainedResourcePins:
            raise _fail()
        found.validate()
        if found != self.retained:
            raise _fail()

    def _require_fresh_attempt_resources(self, plan: transaction.PairCoordinates) -> None:
        # Retained fixed names MUST exist, independently verified with original
        # creator labels; only additional/uncertain containers are refused here.
        if host._browser_docker_ids() != {plan.old_controller_id, plan.old_worker_id}:
            raise _fail()

    def _old_exact(self, plan: transaction.PairCoordinates, *, parked: bool) -> None:
        if self.old is None:
            raise _fail()
        for role, cid, canonical in (
            ("controller", plan.old_controller_id, historical._ORIGINAL_CONTROLLER),
            ("browser-worker", plan.old_worker_id, historical._ORIGINAL_WORKER),
        ):
            name = (
                f"{canonical.removesuffix('-1')}-legacy-{plan.attempt_id}" if parked else canonical
            )
            record = historical._full_old_record(
                plan, cid, role=role, name=name, running=role == "controller" and not parked
            )
            state, config = record.get("State"), record.get("HostConfig")
            if not isinstance(state, dict) or not isinstance(config, dict):
                raise _fail()
            container_config = record.get("Config")
            labels = container_config.get("Labels") if isinstance(container_config, dict) else None
            expected_hash = (
                self.old.pair.controller_config_hash
                if role == "controller"
                else self.old.pair.worker_config_hash
            )
            if (
                not isinstance(labels, dict)
                or labels.get("com.docker.compose.config-hash") != expected_hash
            ):
                raise _fail()
            restart = "unless-stopped" if role == "controller" and not parked else "no"
            if config.get("RestartPolicy") != {"Name": restart, "MaximumRetryCount": 0}:
                raise _fail()
            if role == "browser-worker":
                if (
                    state.get("Status") != "created"
                    or state.get("Pid") != 0
                    or state.get("ExitCode") != 0
                ):
                    raise _fail()
            elif parked and (state.get("Status") != "exited" or state.get("Pid") != 0):
                raise _fail()

    def attest(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        self._guard(plan, lease, "NEW")
        self._integrations().verify_release(plan, self.sources, lease)
        host._require_dedicated_identity()
        if not host._rootless_socket_secure():
            raise _fail()
        self._require_fresh_attempt_resources(plan)
        self.verify_retained(plan, lease)
        raw = observer.observe(plan.attempt_id)
        observer.verify(raw, plan.attempt_id)
        data = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
        controller, worker = data["services"]
        old = service.read_installed_binding(lease)
        if (
            data["source_sha"] != plan.old_source_sha
            or data["attempt_id"] != plan.old_attempt_id
            or controller["container_id"] != plan.old_controller_id
            or worker["container_id"] != plan.old_worker_id
            or controller["image_id"] != plan.old_controller_image_id
            or worker["image_id"] != plan.old_worker_image_id
            or controller["running"] is not True
            or controller["health"] != "healthy"
            or worker["status"] != "created"
            or worker["pid"] != 0
            or worker["exit_code"] != 0
            or old.installation_run_id != plan.old_attempt_id
            or old.source_sha != plan.old_source_sha
            or old.controller_id != plan.old_controller_id
            or old.worker_id != plan.old_worker_id
            or old.controller_image != controller["image_ref"]
            or old.worker_image != worker["image_ref"]
            or old.pair.sender_id
        ):
            raise _fail()
        self.old = old
        self._old_exact(plan, parked=False)
        self.owner = historical._reviewed_owner(plan.old_controller_id)
        host._validate_data_volume()
        self.root = host._checked_docker_storage_dir()
        if (
            self.root != historical._ROOTLESS_DB
            or sqlite.observe_sqlite_identity(self.root) != "VERIFIED_STABLE"
        ):
            raise _fail()
        self.sqlite_identity = sqlite.capture_sqlite_identity(self.root)
        engine = ProductionRootlessDockerIO().engine_request(plan.old_controller_id, "status")
        if engine.state != "STOPPED" or engine.changed or engine.pid <= 0:
            raise _fail()
        self.old_pair_receipt = raw
        self.state = "ATTESTED"

    def stage(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> None:
        self._guard(plan, lease, "ATTESTED")
        self._integrations().verify_release(plan, self.sources, lease)
        self._sqlite()
        self._require_fresh_attempt_resources(plan)
        self.verify_retained(plan, lease)
        self.stage_dir = staging.prepare(plan.attempt_id, self.sources)
        host._browser_compose_model(
            plan.controller_ref,
            historical._BASE_ORIGIN,
            self.owner,
            plan.worker_ref,
            plan.attempt_id,
            base_file=self.stage_dir / "compose.beta.yaml",
            overlay_file=self.stage_dir / "compose.beta.browser.yaml",
            seccomp_file=self.stage_dir / "seccomp_profile.json",
            control_directory=service.control_directory(),
        )
        self.worker_hash = self._compose_hash(plan, "browser-worker")
        self.controller_hash = self._compose_hash(plan, "controller")
        if self.worker_hash == self.controller_hash:
            raise _fail()
        host._browser_pull_both(plan.controller_ref, plan.worker_ref, plan.new_source_sha)
        self.verify_retained(plan, lease)
        self._sqlite()
        self.state = "STAGED"

    def replace_binding(
        self,
        plan: transaction.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: BocaJobLease,
    ) -> None:
        super().replace_binding(plan, controller_id, worker_id, lease)
        # The next transaction operation is the irreversible journal marker.
        self.verify_retained(plan, lease)

    def _reclaim_stage_resources(self, plan: transaction.PairCoordinates) -> None:
        # No resource in retained belongs to this new attempt. Never invoke
        # first-migration volume/network compensation on success or failure.
        return None

    def restore_old(self, plan: transaction.PairCoordinates, lease: BocaJobLease) -> bool:
        try:
            # Drift makes the old pair unsafe to reactivate as well. Do not
            # mistake a failed candidate check for permission to start it.
            self.verify_retained(plan, lease)
            if super().restore_old(plan, lease) is not True:
                return False
            self.verify_retained(plan, lease)
            return True
        except Exception:
            return False

    def _verify_final_pair(
        self, plan: transaction.PairCoordinates, commit_started: bool, lease: BocaJobLease
    ) -> None:
        installed = self.new if commit_started else self.old
        if (
            self.state != ("RETIRED" if commit_started else "RESTORED")
            or installed is None
            or service.read_installed_binding(lease) != installed
        ):
            raise _fail()
        if commit_started:
            binding._new_pair_only(installed)
        else:
            self._old_exact(plan, parked=False)

    def finalize(
        self,
        plan: transaction.PairCoordinates,
        *,
        commit_started: bool,
        controller_id: str | None,
        worker_id: str | None,
        lease: BocaJobLease,
    ) -> str:
        verify_protected_boca_job_lease(lease, plan.attempt_id)
        # The only reviewed durable V2 cleanup adapter currently proves a
        # SUCCESS topology and protects the *new* pair. A recovered old pair
        # is not that topology: its failure-specific cleanup needs a separate
        # same-lease receipt before it may remove anything. Preserve residue.
        if not commit_started:
            try:
                self._sqlite()
                self.verify_retained(plan, lease)
                self._verify_final_pair(plan, False, lease)
                return "NO_GO"
            except Exception:
                return "INDETERMINATE"
        try:
            self._sqlite()
            self.verify_retained(plan, lease)
            self._verify_final_pair(plan, True, lease)
        except Exception:
            # A forged/partial pair cannot be passed to the success-only
            # executor even if that executor independently inventories.
            return "INDETERMINATE"
        try:
            result = self._integrations().final_cleanup(plan, lease)
            self.verify_retained(plan, lease)
            self._sqlite()
            # Cleanup is an effectful boundary, not the last word on the pair.
            # Reprove the active installation after it, never accept an ACK
            # which silently changed the serving pair or its control binding.
            self._verify_final_pair(plan, commit_started, lease)
            return result if result in ("ACCEPT", "NO_GO", "INDETERMINATE") else "INDETERMINATE"
        except Exception:
            return "INDETERMINATE"
