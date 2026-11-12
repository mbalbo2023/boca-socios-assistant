"""Unwired evidence adapters, never a host-operation or authorization route.

No CLI, credentials, network client, default host IO, Docker mutation or
upgrade-actor import. Authentication must come from a separately reviewed
protected transport; successfully parsing supplied JSON cannot replace it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_cutover_stage as stage
from boca_socios.browser_release_manifest import validate_browser_manifest
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
from boca_socios.release_manifest import validate_manifest
from boca_socios.release_run import validate_release_run

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_IPC = "boca-socios_boca_browser_ipc"
_SITE = "boca-socios_boca_site_config"
_EGRESS = "boca-socios_boca_browser_egress"
_ATTEMPT = "boca.socios.browser-ipc-attempt"
_VOLUMES = frozenset(
    {"boca-socios_boca_data", "boca-socios_boca_key", "boca-socios_boca_owner", _IPC, _SITE}
)


class EvidenceNoGo(ValueError):
    """Fixed refusal category, without host output or untrusted exception text."""


def _fail() -> EvidenceNoGo:
    return EvidenceNoGo("Boca upgrade evidence remains unverified")


def _json(raw: bytes, bound: int) -> object:
    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise _fail()
            value[key] = item
        return value

    if type(raw) is not bytes or not 0 < len(raw) <= bound:
        raise _fail()
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError, UnicodeError):
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class AuthenticationRequest:
    """Bind authentication to the exact payload and workflow, not a boolean.

    payload_sha256 hashes extracted receipt/manifest bytes, NOT the Actions
    artifact archive. The provider must independently verify the genuine
    archive digest, member allowlist and extraction before authenticating it.
    Witnesses instead need the actual protected receipt transport; do not
    invent an artifact for a workflow which publishes only a step summary.
    """

    kind: Literal["controller-release", "paired-release", "retained-resource-observe"]
    run_id: str
    source_sha: str
    workflow_path: str
    payload_sha256: str


class EvidenceAuthenticator(Protocol):
    """Trusted boundary, deliberately no production implementation or default.

    Return metadata obtained from authenticated Actions and authenticate the
    exact request payload, workflow/operation, protected actor/environment,
    run/source/first-attempt and freshness. Caller-provided JSON is not enough.
    Failure MUST raise; returning a plausible metadata dict without proving
    the payload's origin does not implement this protocol's security contract.
    """

    def authenticate(self, request: AuthenticationRequest) -> object: ...


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    source_sha: str
    release_run_id: str
    controller_ref: str
    worker_ref: str
    controller_manifest_sha256: str
    paired_manifest_sha256: str

    @property
    def apply_authorized(self) -> Literal[False]:
        return False


def verify_release(
    candidate: CandidateRelease,
    *,
    controller_manifest: bytes,
    paired_manifest: bytes,
    current_main_sha: str,
    authenticator: EvidenceAuthenticator | None = None,
) -> ReleaseEvidence:
    """Verify same-source dual manifests only after explicit authentication."""
    try:
        if authenticator is None or type(candidate) is not CandidateRelease:
            raise _fail()
        candidate.validate()
        if current_main_sha != candidate.source_sha:
            raise _fail()
        digests = []
        manifests: tuple[tuple[Literal["controller-release", "paired-release"], bytes], ...] = (
            ("controller-release", controller_manifest),
            ("paired-release", paired_manifest),
        )
        for kind, raw in manifests:
            value = _json(raw, 1024)
            digest = hashlib.sha256(raw).hexdigest()
            request = AuthenticationRequest(
                kind,
                candidate.release_run_id,
                candidate.source_sha,
                ".github/workflows/release-image.yml",
                digest,
            )
            run = authenticator.authenticate(request)
            validate_release_run(run, candidate.source_sha, candidate.release_run_id)
            if kind == "controller-release":
                validate_manifest(
                    value,
                    candidate.controller_image_ref,
                    candidate.source_sha,
                    candidate.release_run_id,
                )
            else:
                validate_browser_manifest(
                    value,
                    candidate.controller_image_ref,
                    candidate.worker_image_ref,
                    candidate.source_sha,
                    candidate.release_run_id,
                )
            digests.append(digest)
        return ReleaseEvidence(
            candidate.source_sha,
            candidate.release_run_id,
            candidate.controller_image_ref,
            candidate.worker_image_ref,
            digests[0],
            digests[1],
        )
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class ResourcePins:
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


@dataclass(frozen=True, slots=True)
class CustodyEvidence:
    installed_source_sha: str
    installation_attempt: str
    observation_run_id: str
    receipt_sha256: str
    resources: ResourcePins
    control_directory_inode_sha256: str

    @property
    def apply_authorized(self) -> Literal[False]:
        return False


def verify_custody_seed(
    raw: bytes,
    *,
    observation_run_id: str,
    observer_source_sha: str,
    authenticator: EvidenceAuthenticator | None = None,
) -> CustodyEvidence:
    """Authenticate unchanged success-frame V1; reject R189 NO_GO frames.

    This seed is historical resource custody, not a live pair receipt and
    not release provenance for a later installed pair or target image.
    """
    try:
        if authenticator is None or not _SHA.fullmatch(observer_source_sha):
            raise _fail()
        retained.verify(raw, observation_run_id)
        request = AuthenticationRequest(
            "retained-resource-observe",
            observation_run_id,
            observer_source_sha,
            ".github/workflows/boca-first-deploy.yml",
            hashlib.sha256(raw).hexdigest(),
        )
        run = authenticator.authenticate(request)
        expected = {
            "id": int(observation_run_id),
            "run_attempt": 1,
            "name": "Boca first deploy",
            "event": "workflow_dispatch",
            "head_sha": observer_source_sha,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
        }
        if (
            not isinstance(run, dict)
            or any(
                type(run.get(key)) is not type(value) or run.get(key) != value
                for key, value in expected.items()
            )
            or run.get("path") not in (request.workflow_path, request.workflow_path + "@main")
        ):
            raise _fail()
        actor, repository = run.get("actor"), run.get("repository")
        if (
            not isinstance(actor, dict)
            or actor.get("login") != "mbalbo2023"
            or not isinstance(repository, dict)
            or repository.get("full_name") != "mbalbo2023/boca-socios-assistant"
        ):
            raise _fail()
        value = _json(raw.removeprefix(b"BOCA_RETAINED_RESOURCES "), 48_000)
        if not isinstance(value, dict) or value["expected_resource_provenance"] is not True:
            raise _fail()
        volumes, network = value["volumes"], value["egress"]
        if not isinstance(volumes, list) or not isinstance(network, dict):
            raise _fail()
        pins = ResourcePins(
            volumes[0]["creator_attempt"],
            volumes[0]["inode_sha256"],
            volumes[1]["creator_attempt"],
            volumes[1]["inode_sha256"],
            network["creator_attempt"],
            network["id"],
        )
        pins.validate()
        return CustodyEvidence(
            str(value["source_sha"]),
            str(value["installation_attempt"]),
            observation_run_id,
            request.payload_sha256,
            pins,
            str(value["control_socket_directory_inode_sha256"]),
        )
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class ExpectedService:
    ident: str
    role: Literal["controller", "browser-worker"]
    source_sha: str
    installation_attempt: str
    image_ref: str


@dataclass(frozen=True, slots=True)
class GraphExpectation:
    """Only exact binding/journal IDs; never workflow-form name/glob inputs."""

    services: tuple[ExpectedService, ...]

    def validate(self) -> None:
        if not 2 <= len(self.services) <= 4 or len({s.ident for s in self.services}) != len(
            self.services
        ):
            raise _fail()
        for role in ("controller", "browser-worker"):
            if not 1 <= sum(s.role == role for s in self.services) <= 2:
                raise _fail()
        for service in self.services:
            prefix = (
                "ghcr.io/mbalbo2023/boca-socios-assistant"
                + ("-browser" if service.role == "browser-worker" else "")
                + "@sha256:"
            )
            if (
                service.role not in ("controller", "browser-worker")
                or not _HASH.fullmatch(service.ident)
                or not _SHA.fullmatch(service.source_sha)
                or not _RUN.fullmatch(service.installation_attempt)
                or not service.image_ref.startswith(prefix)
                or not _HASH.fullmatch(service.image_ref.removeprefix(prefix))
            ):
                raise _fail()


class RetainedResourceIO(Protocol):
    """Read-only boundary with no default production implementation.

    inventory must perform the existing global exclusivity census before
    detail reads. identity must use no-follow per-ancestor fstat, checking
    the exact Docker volume mountpoint as R189; never read volume contents.
    """

    def rootless_identity(self) -> tuple[int, int, str]: ...
    def inventory(self) -> cleanup.Inventory: ...
    def identity(self, name: str) -> str: ...
    def worker_state(self, ident: str) -> object: ...
    def mounts(self, ident: str) -> object: ...


def _retained_snapshot(
    pins: ResourcePins, graph: GraphExpectation, io: RetainedResourceIO
) -> tuple[object, ...]:
    if io.rootless_identity() != (10001, 10001, "/home/boca-deploy/.local/share/docker"):
        raise _fail()
    snapshot = io.inventory()
    cleanup._validate_inventory(snapshot)
    if (
        {c.ident for c in snapshot.containers} != {s.ident for s in graph.services}
        or {v.name for v in snapshot.volumes} != _VOLUMES
        or snapshot.global_image_ids - {image.ident for image in snapshot.images}
    ):
        raise _fail()
    containers = {c.ident: c for c in snapshot.containers}
    images = {image.ident: image for image in snapshot.images}
    for expected in graph.services:
        current = containers[expected.ident]
        labels = cleanup._labels(current.labels)
        image = images.get(current.image_id)
        if (
            labels.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or labels.get("com.docker.compose.service") != expected.role
            or labels.get(_ATTEMPT) != expected.installation_attempt
            or labels.get("org.opencontainers.image.revision") != expected.source_sha
            or image is None
            or image.source != cleanup.BOCA_SOURCE
            or expected.image_ref not in image.references
            or sum(expected.image_ref in item.references for item in snapshot.images) != 1
        ):
            raise _fail()
        mounts = pair._safe_mounts(
            io.mounts(expected.ident),
            service=expected.role,
            valid_volumes=_VOLUMES,
            historical=False,
        )
        required = sorted(_VOLUMES if expected.role == "controller" else {_IPC, _SITE})
        if mounts != required or list(current.volumes) != required:
            raise _fail()
        expected_network_name = (
            _EGRESS if expected.role == "browser-worker" else "boca-socios_boca_private"
        )
        if (
            current.networks not in ((), (expected_network_name,))
            or current.running
            and current.networks != (expected_network_name,)
        ):
            raise _fail()
        if expected.role == "browser-worker":
            state = io.worker_state(expected.ident)
            if (
                current.running
                or not isinstance(state, dict)
                or state.get("Status") != "created"
                or state.get("Running") is not False
                or type(state.get("Pid")) is not int
                or state["Pid"] != 0
                or type(state.get("ExitCode")) is not int
                or state["ExitCode"] != 0
            ):
                raise _fail()
    for name, role, creator in (
        (_IPC, "boca_browser_ipc", pins.ipc_creator_attempt),
        (_SITE, "boca_site_config", pins.site_creator_attempt),
    ):
        volume = next(v for v in snapshot.volumes if v.name == name)
        if cleanup._labels(volume.labels) != {
            "com.docker.compose.project": cleanup.BOCA_PROJECT,
            "com.docker.compose.volume": role,
            _ATTEMPT: creator,
        }:
            raise _fail()
    networks = [network for network in snapshot.networks if network.name == _EGRESS]
    if len(networks) != 1 or {n.name for n in snapshot.networks} != {
        _EGRESS,
        "boca-socios_boca_private",
    }:
        raise _fail()
    egress = networks[0]
    if (
        egress.ident != pins.egress_id
        or egress.attached_ids
        or cleanup._labels(egress.labels)
        != {
            "com.docker.compose.project": cleanup.BOCA_PROJECT,
            "com.docker.compose.network": "boca_browser_egress",
            _ATTEMPT: pins.egress_creator_attempt,
        }
        or io.identity(_IPC) != pins.ipc_inode_sha256
        or io.identity(_SITE) != pins.site_inode_sha256
    ):
        raise _fail()
    for network in snapshot.networks:
        if network.name != _EGRESS:
            labels = cleanup._labels(network.labels)
            controllers = {s.ident for s in graph.services if s.role == "controller"}
            if (
                labels.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
                or not set(network.attached_ids) <= controllers
            ):
                raise _fail()
    return (
        snapshot.containers,
        snapshot.images,
        snapshot.networks,
        snapshot.volumes,
        snapshot.global_image_ids,
    )


def observe_retained(
    pins: ResourcePins,
    graph: GraphExpectation,
    attempt_id: str,
    lease: cleanup.BocaJobLease,
    *,
    io: RetainedResourceIO | None = None,
) -> ResourcePins:
    """Double-read retained graph, including the bounded 3/4-CID transition."""
    try:
        cleanup.verify_protected_boca_job_lease(lease, attempt_id)
        if io is None or type(pins) is not ResourcePins or type(graph) is not GraphExpectation:
            raise _fail()
        pins.validate()
        graph.validate()
        if _retained_snapshot(pins, graph, io) != _retained_snapshot(pins, graph, io):
            raise _fail()
        cleanup.verify_protected_boca_job_lease(lease, attempt_id)
        return pins
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class CleanupEvidence:
    attempt_id: str
    status: Literal["ACCEPT", "NO_GO", "INDETERMINATE"]
    receipt_sha256: str

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def coverage(self) -> Literal["IMAGE_RECEIPT_ONLY"]:
        return "IMAGE_RECEIPT_ONLY"


def _targets(value: object) -> tuple[cleanup.Target, ...]:
    if not isinstance(value, list) or len(value) > cleanup.MAX_DELETIONS:
        raise _fail()
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"kind", "id"}:
            raise _fail()
        if (
            item["kind"] != "image"
            or type(item["id"]) is not str
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", item["id"])
        ):
            # Container retirement belongs to the transaction, persistent
            # graph/stage custody to their own exact-file contracts. This
            # adapter never promotes a volume/network deletion into ACCEPT.
            raise _fail()
        result.append(cleanup.Target("image", item["id"]))
    return tuple(result)


def verify_cleanup(
    raw: bytes,
    attempt_id: str,
    *,
    before: cleanup.Inventory,
    after: cleanup.Inventory,
    expected_removed: tuple[cleanup.Target, ...],
) -> CleanupEvidence:
    """Certify recorded image cleanup, not execute it or authorize an upgrade.

    Both inventories must be freshly captured by the protected caller. V2
    forensic quarantine is intentionally refused until its genuine historical
    release/physical-proof adapter is integrated; no guessed exception here.
    """
    try:
        if not _RUN.fullmatch(attempt_id):
            raise _fail()
        value = _json(raw, 8192)
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "version",
                "scope",
                "outcome",
                "attempt_id",
                "status",
                "before",
                "after",
                "removed",
                "retained_uncertain",
                "known_residue",
            }
            or value["version"] != 1
            or type(value["version"]) is not int
            or value["scope"] != "boca-postdeploy"
            or value["attempt_id"] != attempt_id
            or value["outcome"] not in ("SUCCESS", "FAILURE")
            or value["status"] not in ("ACCEPT", "NO_GO", "INDETERMINATE")
            or not isinstance(value["retained_uncertain"], list)
            or any(type(reason) is not str for reason in value["retained_uncertain"])
        ):
            raise _fail()
        removed, residue = _targets(value["removed"]), _targets(value["known_residue"])
        receipt = cleanup.CleanupReceipt(
            cast(cleanup.OUTCOME, value["outcome"]),
            attempt_id,
            cast(Literal["ACCEPT", "NO_GO", "INDETERMINATE"], value["status"]),
            before.disk,
            after.disk,
            removed,
            tuple(cast(list[str], value["retained_uncertain"])),
            residue,
        )
        if receipt.redacted_json().encode("ascii") != raw or removed != expected_removed:
            raise _fail()
        cleanup._validate_inventory(before)
        cleanup._validate_inventory(after)
        ids = {target.ident for target in removed}
        if (
            any(target.kind != "image" for target in expected_removed)
            or len(ids) != len(removed)
            or cleanup.HISTORICAL_RETIRE_TARGET in ids
            or before.containers != after.containers
            or before.volumes != after.volumes
            or before.networks != after.networks
            or before.global_image_ids != {image.ident for image in before.images}
            or after.global_image_ids != {image.ident for image in after.images}
            or before.global_image_ids - ids != after.global_image_ids
            or tuple(image for image in before.images if image.ident not in ids) != after.images
        ):
            raise _fail()
        referenced = {container.image_id for container in before.containers + after.containers}
        for image in before.images:
            if image.source != cleanup.BOCA_SOURCE or any(
                not (
                    cleanup.BOCA_PUBLIC_DIGEST.fullmatch(ref)
                    or cleanup.BOCA_PUBLIC_SHA_TAG.fullmatch(ref)
                )
                for ref in image.references
            ):
                raise _fail()
            if image.ident in ids and image.ident in referenced:
                raise _fail()
        if not ids <= {image.ident for image in before.images}:
            raise _fail()
        return CleanupEvidence(attempt_id, receipt.status, hashlib.sha256(raw).hexdigest())
    except Exception:
        raise _fail() from None


def persist_cleanup(
    raw: bytes,
    attempt_id: str,
    lease: cleanup.BocaJobLease,
    *,
    before: cleanup.Inventory,
    after: cleanup.Inventory,
    expected_removed: tuple[cleanup.Target, ...],
) -> CleanupEvidence:
    """O_EXCL/fsync/readback of one exact receipt; no deletion or overwrite.

    There is no workflow/CLI route to this function. Tests substitute only a
    private temporary stage. A failed fsync/ACK preserves the file and NO_GO;
    it cannot be retried under the same or a renamed attempt automatically.
    """
    try:
        cleanup.verify_protected_boca_job_lease(lease, attempt_id)
        evidence = verify_cleanup(
            raw, attempt_id, before=before, after=after, expected_removed=expected_removed
        )
        root = stage._root_fd()
        try:
            name = f".boca-upgrade-cleanup-{attempt_id}.json"
            stage._create_exclusive(root, name, raw)
            os.fsync(root)
            stored, _metadata = stage._read_file(root, name, evidence.receipt_sha256, limit=8192)
            if stored != raw:
                raise _fail()
        finally:
            os.close(root)
        cleanup.verify_protected_boca_job_lease(lease, attempt_id)
        return evidence
    except Exception:
        raise _fail() from None
