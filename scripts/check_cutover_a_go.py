"""Protected Cutover A GO binding; runner-only, no direct host effects.

The protected workflow exposes an inert-by-default operation: an independent
exact-run GitHub Environment variable must match this full reviewed digest.
Neither source review, PR checks nor dispatch input constitutes historical GO.
Owner-authorized V3 uses check_boca_deploy_dispatch instead; this module still
provides exact artifact verification and strict terminal receipt validation.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import boca_protected_memfd_bootstrap as memfd

from boca_socios.browser_release_manifest import validate_browser_manifest
from boca_socios.host_boca_cleanup import (
    HISTORICAL_RETIRE_DIGEST,
    HISTORICAL_RETIRE_REVISION,
    HISTORICAL_RETIRE_TARGET,
)
from boca_socios.host_boca_cutover import (
    CUTOVER_FAILURE_PHASES,
    WORKER_COMPENSATION_STATES,
    WORKER_PRIMARY_PHASES,
    CandidateEvidence,
    CutoverPlan,
)
from boca_socios.host_boca_cutover_cli import CutoverCliError, CutoverInvocation, encode_invocation
from boca_socios.prepared_go_runner import (
    PreparedGoError,
    hash_reviewed_file,
    verify_legacy_prepared_go,
)
from boca_socios.release_manifest import validate_manifest
from boca_socios.worker_start_capture import is_capture_result

VERSION = "boca-cutover-a-go-v1"
REPOSITORY = "mbalbo2023/boca-socios-assistant"
OWNER = "mbalbo2023"
MAIN = "refs/heads/main"
RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
MAX_REQUEST = 8192
HOST_INVOCATION_NAME = "boca-cutover-a-invocation.token"
HOST_APPROVAL_NAME = "boca-cutover-a-approved.digest"
HOST_RECEIPT_NAME = "boca-cutover-a-host.receipt"


class CutoverGoError(ValueError):
    """No independently controlled exact-run authorization was verified."""


@dataclass(frozen=True)
class GoRequest:
    plan: CutoverPlan
    github_repository: str
    github_actor: str
    github_ref: str
    github_sha: str
    github_run_id: str
    github_run_attempt: str
    target_release_run_id: str
    legacy_release_run_id: str
    target_manifest_path: Path
    browser_manifest_path: Path
    legacy_manifest_path: Path
    historical_compose_path: Path
    target_compose_path: Path
    overlay_path: Path
    seccomp_path: Path
    bundle_path: Path

    @classmethod
    def from_json(cls, request: object) -> GoRequest:
        if not isinstance(request, dict) or set(request) != {
            "plan",
            "github_repository",
            "github_actor",
            "github_ref",
            "github_sha",
            "github_run_id",
            "github_run_attempt",
            "target_release_run_id",
            "legacy_release_run_id",
            "target_manifest_path",
            "browser_manifest_path",
            "legacy_manifest_path",
            "historical_compose_path",
            "target_compose_path",
            "overlay_path",
            "seccomp_path",
            "bundle_path",
        }:
            raise CutoverGoError("exact Cutover A GO request fields invalid")
        plan = request["plan"]
        if not isinstance(plan, dict) or set(plan) != set(CutoverPlan.__dataclass_fields__):
            raise CutoverGoError("cutover approved plan fields invalid")
        if any(type(value) is not str for value in plan.values()):
            raise CutoverGoError("cutover approved plan coordinates invalid")
        other = {key: value for key, value in request.items() if key != "plan"}
        if any(type(value) is not str for value in other.values()):
            raise CutoverGoError("cutover GO request coordinate types invalid")
        return cls(
            plan=CutoverPlan(**plan),
            **{
                key: Path(value) if key.endswith("_path") else value for key, value in other.items()
            },
        )


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in pairs:
        if key in fields:
            raise CutoverGoError("duplicate GO artifact field")
        fields[key] = value
    return fields


def _open_no_parent_symlink(path: Path) -> int:
    """Walk each absolute directory FD; no ancestor may redirect an artifact."""
    if not path.is_absolute() or not path.name or ".." in path.parts:
        raise CutoverGoError("Cutover A GO artifact path must be absolute and unambiguous")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            next_directory = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            try:
                metadata = os.fstat(next_directory)
                if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid not in (
                    0,
                    os.geteuid(),
                ):
                    raise CutoverGoError("Cutover A GO ancestor directory untrusted")
            except BaseException:
                os.close(next_directory)
                raise
            os.close(directory)
            directory = next_directory
        # O_NONBLOCK is ignored for regular files but prevents an attacker-
        # controlled FIFO from hanging protected runner preflight BEFORE fstat.
        # The subsequent fstat still strictly requires a regular inode.
        return os.open(
            path.name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
    except OSError as exc:
        raise CutoverGoError("Cutover A GO artifact path or parent symlink untrusted") from exc
    finally:
        os.close(directory)


def _read_bounded(path: Path, maximum: int) -> bytes:
    """One bounded ancestor-safe read, stable inode and no group/world writes."""
    try:
        with os.fdopen(_open_no_parent_symlink(path), "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or bool(stat.S_IMODE(before.st_mode) & 0o022)
                or not 0 < before.st_size <= maximum
            ):
                raise CutoverGoError("Cutover A GO artifact inode untrusted")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            identity_before = (
                before.st_dev,
                before.st_ino,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_mode,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            identity_after = (
                after.st_dev,
                after.st_ino,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_mode,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if len(raw) != before.st_size or identity_before != identity_after:
                raise CutoverGoError("Cutover A GO artifact changed while reading")
            return raw
    except OSError as exc:
        raise CutoverGoError("Cutover A GO artifact cannot be read safely") from exc


def _manifest(path: Path) -> tuple[object, str]:
    raw = _read_bounded(path, 2048)
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CutoverGoError("Cutover A GO release manifest malformed") from exc
    return parsed, hashlib.sha256(raw).hexdigest()


def _digest(path: Path, *, expected: str, maximum: int) -> str:
    data = _read_bounded(path, maximum)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise CutoverGoError("Cutover A reviewed artifact digest mismatch")
    return digest


def authorization_digest(request: GoRequest) -> str:
    """Authenticate three manifests and every reviewed byte before GO compare."""
    plan = request.plan
    try:
        plan.validate()
    except ValueError as exc:
        raise CutoverGoError("Cutover A plan validation failed") from exc
    if (
        request.github_repository != REPOSITORY
        or request.github_actor != OWNER
        or request.github_ref != MAIN
        or request.github_run_attempt != "1"
        or request.github_sha != plan.target_sha
        or request.github_run_id != plan.attempt_id
        or not RUN.fullmatch(request.github_run_id)
        or not RUN.fullmatch(request.target_release_run_id)
        or not RUN.fullmatch(request.legacy_release_run_id)
        or request.target_release_run_id == request.legacy_release_run_id
        or request.target_manifest_path == request.legacy_manifest_path
        or request.target_manifest_path == request.browser_manifest_path
        or request.legacy_manifest_path == request.browser_manifest_path
    ):
        raise CutoverGoError("Cutover A GO main/owner/one-shot/releases invalid")
    target, target_sha = _manifest(request.target_manifest_path)
    browser, browser_sha = _manifest(request.browser_manifest_path)
    legacy, legacy_sha = _manifest(request.legacy_manifest_path)
    try:
        validate_manifest(target, plan.target_image, plan.target_sha, request.target_release_run_id)
        validate_browser_manifest(
            browser,
            plan.target_image,
            plan.browser_image,
            plan.target_sha,
            request.target_release_run_id,
        )
        validate_manifest(legacy, plan.legacy_image, plan.legacy_sha, request.legacy_release_run_id)
    except ValueError as exc:
        raise CutoverGoError("Cutover A GO release manifests conflict") from exc
    _digest(request.historical_compose_path, expected=plan.legacy_compose_sha, maximum=32768)
    _digest(request.target_compose_path, expected=plan.target_compose_sha, maximum=32768)
    _digest(request.overlay_path, expected=plan.overlay_sha, maximum=32768)
    _digest(request.seccomp_path, expected=plan.seccomp_sha, maximum=32768)
    bundle = _read_bounded(request.bundle_path, memfd.MAX_ZIP)
    bundle_sha = hashlib.sha256(bundle).hexdigest()
    try:
        memfd.verify(bundle, bundle_sha)
        with zipfile.ZipFile(io.BytesIO(bundle), "r") as package:
            if set(package.namelist()) != memfd.EXPECTED_ENTRIES | memfd.OPTION_B_ENTRIES:
                raise CutoverGoError("Cutover A GO requires complete Option B source ZIP")
    except CutoverGoError:
        raise
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise CutoverGoError("Cutover A GO bundle not fully authenticated") from exc
    approved = {
        "version": VERSION,
        "github_repository": request.github_repository,
        "github_actor": request.github_actor,
        "github_ref": request.github_ref,
        "github_sha": request.github_sha,
        "github_run_id": request.github_run_id,
        "github_run_attempt": request.github_run_attempt,
        "legacy_controller_id": plan.legacy_id,
        "legacy_source_sha": plan.legacy_sha,
        "legacy_image_ref": plan.legacy_image,
        "legacy_release_run_id": request.legacy_release_run_id,
        "legacy_release_manifest_sha256": legacy_sha,
        "legacy_compose_sha256": plan.legacy_compose_sha,
        "target_source_sha": plan.target_sha,
        "target_image_ref": plan.target_image,
        "target_release_run_id": request.target_release_run_id,
        "target_release_manifest_sha256": target_sha,
        "browser_image_ref": plan.browser_image,
        "browser_release_manifest_sha256": browser_sha,
        "target_compose_sha256": plan.target_compose_sha,
        "browser_overlay_sha256": plan.overlay_sha,
        "browser_seccomp_sha256": plan.seccomp_sha,
        "bundle_sha256": bundle_sha,
        "owner_subject_sha256": hashlib.sha256(plan.owner_subject.encode("utf-8")).hexdigest(),
        "panel_origin": plan.origin,
        "no_backup": True,
        "no_real_reservations": True,
    }
    raw = json.dumps(approved, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


PREPARED_REVIEW_VERSION = "boca-cutover-a-prepared-review-v1"


def cutover_prepared_context_sha256(request: GoRequest, *, prepare_run_id: str) -> str:
    """Return an inert PREPARE review digest without a future APPLY run ID.

    PREPARE and APPLY each have their own (then-known) GITHUB_RUN_ID. The
    PREPARE identifier substitutes for the ephemeral current-run ID *only in
    this context digest*. The actual GoRequest/host plan, exact run attestation,
    old authorization_digest and --from-actions gate remain unchanged.
    A privileged caller must independently authenticate the PREPARE artifact,
    owner, expiry, source, context and Environment GO before any host invocation.
    This helper never accepts a digest as a GO or writes a host token.
    """
    if (
        not isinstance(request, GoRequest)
        or type(prepare_run_id) is not str
        or RUN.fullmatch(prepare_run_id) is None
        or request.github_run_id != request.plan.attempt_id
        or request.github_run_attempt != "1"
        or RUN.fullmatch(request.github_run_id) is None
    ):
        raise CutoverGoError("Cutover A prepared review run/attempt invalid")
    projected = replace(
        request,
        github_run_id=prepare_run_id,
        plan=replace(request.plan, attempt_id=prepare_run_id),
    )
    # All three manifests, every Compose/seccomp byte, Option B ZIP and owner
    # subject are still attested by the original strict v1 implementation.
    exact_reviewed = authorization_digest(projected)
    public_context = {
        "version": PREPARED_REVIEW_VERSION,
        "operation": "cutover-a-apply",
        "prepare_run_id": prepare_run_id,
        "reviewed_authorization_sha256": exact_reviewed,
    }
    encoded = json.dumps(
        public_context, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def require_protected_go(request: GoRequest, *, protected_go_digest: str) -> str:
    """A missing protected GitHub Environment variable always remains NO_GO."""
    if not HEX.fullmatch(protected_go_digest):
        raise CutoverGoError("protected cutover GO absent or malformed")
    expected = authorization_digest(request)
    if protected_go_digest != expected:
        raise CutoverGoError("protected cutover GO not bound to this exact run")
    return expected


def actions_request(environment: Mapping[str, str]) -> GoRequest:
    """Derive exact host coordinates from protected Actions context, not input JSON."""
    if (
        environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or environment.get("BOCA_OPERATION") != "cutover-a-apply"
        or environment.get("BOCA_SERVICE") != "controller"
        or environment.get("BOCA_BUDGET") != "1.5cpu-1024m-192pids"
        or environment.get("GITHUB_SHA") != environment.get("BOCA_SOURCE_SHA")
    ):
        raise CutoverGoError("Cutover A protected Actions operation context invalid")
    try:
        workspace = Path(environment["GITHUB_WORKSPACE"])
        runner = Path(environment["RUNNER_TEMP"])
        if (
            not workspace.is_absolute()
            or not runner.is_absolute()
            or workspace == runner
            or ".." in workspace.parts
            or ".." in runner.parts
        ):
            raise CutoverGoError("Cutover A runner directory roots invalid")
        historical = runner / "boca-cutover-legacy-compose.yaml"
        target = workspace / "compose.beta.yaml"
        overlay = workspace / "compose.beta.browser.yaml"
        seccomp = workspace / "docker/seccomp_profile.json"
        plan = CutoverPlan(
            attempt_id=environment["GITHUB_RUN_ID"],
            legacy_id=environment["BOCA_LEGACY_CONTROLLER_ID"],
            legacy_sha=environment["BOCA_LEGACY_SOURCE_SHA"],
            legacy_image=environment["BOCA_LEGACY_IMAGE_REF"],
            legacy_compose_sha=hashlib.sha256(_read_bounded(historical, 32768)).hexdigest(),
            target_sha=environment["BOCA_SOURCE_SHA"],
            target_image=environment["BOCA_IMAGE_REF"],
            browser_image=environment["BOCA_BROWSER_IMAGE_REF"],
            target_compose_sha=hashlib.sha256(_read_bounded(target, 32768)).hexdigest(),
            overlay_sha=hashlib.sha256(_read_bounded(overlay, 32768)).hexdigest(),
            seccomp_sha=hashlib.sha256(_read_bounded(seccomp, 32768)).hexdigest(),
            owner_subject=environment["BOCA_BETA_OWNER_SUBJECT"],
        )
        plan.validate()
        return GoRequest(
            plan=plan,
            github_repository=environment["GITHUB_REPOSITORY"],
            github_actor=environment["GITHUB_ACTOR"],
            github_ref=environment["GITHUB_REF"],
            github_sha=environment["GITHUB_SHA"],
            github_run_id=environment["GITHUB_RUN_ID"],
            github_run_attempt=environment["GITHUB_RUN_ATTEMPT"],
            target_release_run_id=environment["BOCA_RELEASE_RUN_ID"],
            legacy_release_run_id=environment["BOCA_LEGACY_RELEASE_RUN_ID"],
            target_manifest_path=runner / "boca-release-manifest/boca-release-manifest.json",
            browser_manifest_path=runner
            / "boca-browser-release-manifest/boca-browser-release-manifest.json",
            legacy_manifest_path=runner / "boca-cutover-legacy-manifest/boca-release-manifest.json",
            historical_compose_path=historical,
            target_compose_path=target,
            overlay_path=overlay,
            seccomp_path=seccomp,
            bundle_path=runner / "boca-cutover-a-review.pyz",
        )
    except (KeyError, ValueError) as exc:
        raise CutoverGoError("Cutover A required Actions coordinates unavailable") from exc


def _write_once(path: Path, payload: bytes) -> None:
    """Runner-only receipt: no replacement after a failed approved preflight."""
    if not 0 < len(payload) <= MAX_REQUEST:
        raise CutoverGoError("Cutover A approved runner artifact unbounded")
    try:
        fd = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if _read_bounded(path, MAX_REQUEST) != payload:
            raise CutoverGoError("Cutover A runner artifact readback differs")
    except OSError as exc:
        raise CutoverGoError("Cutover A approved runner artifact unavailable") from exc


def write_actions_invocation(request: GoRequest, *, protected_go_digest: str) -> str:
    """Write host token+GO only after runner proves the independent protected GO.

    Neither output contains a credential. No SSH or host operation is made.
    The token's source ZIP digest is verified twice around the full GO check.
    """
    bundle_before = hashlib.sha256(_read_bounded(request.bundle_path, memfd.MAX_ZIP)).hexdigest()
    approved = require_protected_go(request, protected_go_digest=protected_go_digest)
    bundle_after = hashlib.sha256(_read_bounded(request.bundle_path, memfd.MAX_ZIP)).hexdigest()
    if bundle_after != bundle_before:
        raise CutoverGoError("Cutover A ZIP changed during protected GO validation")
    token = encode_invocation(request.plan, bundle_sha256=bundle_after, go_binding_sha256=approved)
    root = request.bundle_path.parent
    _write_once(root / HOST_INVOCATION_NAME, (token + "\n").encode("ascii"))
    _write_once(root / HOST_APPROVAL_NAME, (approved + "\n").encode("ascii"))
    return approved


def write_actions_invocation_prepared(request: GoRequest, *, environ: Mapping[str, str]) -> str:
    """Runner-only v2 token after #352 PREPARE GH review and independent GO_B.

    The three O_EXCL proofs must already have been staged by the privileged
    protected workflow from an authenticated SUCCESS PREPARE artifact; neither
    user dispatch input nor local receipt bytes alone grants authorization.
    """
    try:
        bundle_before = hash_reviewed_file(request.bundle_path, max_bytes=memfd.MAX_ZIP)
        proof = verify_legacy_prepared_go(
            operation="cutover-a-apply",
            expected_public_context_sha256=lambda prepare_id: cutover_prepared_context_sha256(
                request, prepare_run_id=prepare_id
            ),
            source_sha=request.plan.target_sha,
            release_run_id=request.target_release_run_id,
            release_manifest_sha256=hash_reviewed_file(request.target_manifest_path),
            browser_manifest_sha256=hash_reviewed_file(request.browser_manifest_path),
            bundle_sha256=bundle_before,
            owner_subject=request.plan.owner_subject,
            environ=environ,
        )
        bundle_after = hash_reviewed_file(request.bundle_path, max_bytes=memfd.MAX_ZIP)
        if bundle_after != bundle_before:
            raise CutoverGoError("reviewed PREPARE host ZIP changed after GO")
        token = encode_invocation(
            request.plan,
            bundle_sha256=bundle_after,
            go_binding_sha256=proof.approved_sha256,
            prepare_run_id=proof.prepare_run_id,
        )
        root = request.bundle_path.parent
        _write_once(root / HOST_INVOCATION_NAME, (token + "\n").encode("ascii"))
        _write_once(root / HOST_APPROVAL_NAME, (proof.approved_sha256 + "\n").encode("ascii"))
    except (PreparedGoError, CutoverCliError) as exc:
        raise CutoverGoError("Cutover A protected PREPARE GO_B not independently proven") from exc
    return proof.approved_sha256


_POSTFLIGHT_PREFIX = b"BOCA_CUTOVER_A_POSTFLIGHT "
# The host emits this READY observation before attempting any Cutover effect.
# On SSH failure it is diagnostic input only: never an ACCEPTED host receipt.
# Preserve the precise host grammar so a legitimate preceding observation does
# not obscure the following allowlisted NO_GO failure-phase claim.
_CUTOVER_OBSERVE_PREFIX = re.compile(
    rb"BOCA_CUTOVER_A_OBSERVE state=READY legacy_sha=[0-9a-f]{40} "
    rb"legacy_id=[0-9a-f]{64} "
    rb"legacy_image=ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64} "
    rb"target_sha=[0-9a-f]{40} "
    rb"target_image=ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64} "
    rb"browser_image=ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64} "
    rb"original=RUNNING port=127\.0\.0\.1:8443 worker=absent "
    rb"owner=preserved key=preserved data=preserved effects=none\n"
)
_POSTFLIGHT_KEYS = frozenset(
    {
        "version",
        "scope",
        "attempt_id",
        "outcome",
        "status",
        "before",
        "after",
        "removed",
        "retained_uncertain",
        "known_residue",
    }
)
_POSTFLIGHT_KEYS_V2 = _POSTFLIGHT_KEYS | {"retained_attested"}
_POSTFLIGHT_ATTESTED_EXACT = [
    {
        "kind": "image",
        "id": HISTORICAL_RETIRE_TARGET,
        "classification": "KNOWN_HISTORICAL_QUARANTINE",
        "release_run": "41559973013",
        "manifest_artifact": "13196392925",
        "digest": HISTORICAL_RETIRE_DIGEST,
        "revision": HISTORICAL_RETIRE_REVISION,
    }
]
_POSTFLIGHT_DISK_KEYS = frozenset(
    {
        "stage_bytes_free",
        "stage_inodes_free",
        "docker_bytes_free",
        "docker_inodes_free",
        "stage_device",
        "stage_inode",
        "docker_device",
        "docker_inode",
    }
)
_POSTFLIGHT_ID = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
_POSTFLIGHT_VOLUME = re.compile(r"boca-socios_[A-Za-z0-9_.-]{1,110}\Z")
_POSTFLIGHT_PRESERVE = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_telegram",
    }
)


def verify_postflight_json(raw: bytes, expected_attempt_id: str) -> str:
    """Independently validate the bounded public Boca-only host cleanup receipt.

    This parser does not substitute for Docker provenance checks: those must
    be attested under the same Boca rootless lease by the host planner.
    """
    if not 0 < len(raw) <= 8192:
        raise CutoverGoError("Boca postdeploy receipt length unverified")
    try:
        body = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
        canonical = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
        if canonical != raw or type(body) is not dict:
            raise CutoverGoError("Boca postdeploy receipt not canonical")
        version = body.get("version")
        if version == 1:
            if set(body) != _POSTFLIGHT_KEYS:
                raise CutoverGoError("Boca postdeploy legacy receipt schema drifted")
        elif version == 2:
            if (
                set(body) != _POSTFLIGHT_KEYS_V2
                or body["retained_attested"] != _POSTFLIGHT_ATTESTED_EXACT
            ):
                raise CutoverGoError("Boca historical retained image proof missing or altered")
        else:
            raise CutoverGoError("Boca postdeploy receipt version unsupported")
        if (
            type(body["version"]) is not int
            or body["scope"] != "boca-postdeploy"
            or body["attempt_id"] != expected_attempt_id
            or body["outcome"] != "SUCCESS"
            or body["status"] != "ACCEPT"
            or body["retained_uncertain"] != []
            or body["known_residue"] != []
        ):
            raise CutoverGoError("Boca postdeploy receipt is not full SUCCESS/ACCEPT")
        for key in ("before", "after"):
            values = body[key]
            if (
                type(values) is not dict
                or set(values) != _POSTFLIGHT_DISK_KEYS
                or any(type(value) is not int or value < 0 for value in values.values())
            ):
                raise CutoverGoError("Boca postdeploy disk and inode census absent")
        for key in ("stage_device", "stage_inode", "docker_device", "docker_inode"):
            if body["before"][key] != body["after"][key]:
                raise CutoverGoError("Boca postdeploy filesystem identity drifted")
        removed = body["removed"]
        if type(removed) is not list or len(removed) > 32:
            raise CutoverGoError("Boca postdeploy removed resource list unbounded")
        observed: set[tuple[str, str]] = set()
        for entry in removed:
            if type(entry) is not dict or set(entry) != {"kind", "id"}:
                raise CutoverGoError("Boca postdeploy removed resource tuple invalid")
            kind, ident = entry["kind"], entry["id"]
            if type(kind) is not str or type(ident) is not str:
                raise CutoverGoError("Boca postdeploy resource field types invalid")
            if kind in ("image", "container", "network"):
                allowed = _POSTFLIGHT_ID.fullmatch(ident) is not None
            elif kind == "volume":
                allowed = (
                    _POSTFLIGHT_VOLUME.fullmatch(ident) is not None
                    and ident not in _POSTFLIGHT_PRESERVE
                )
            else:
                allowed = False
            if not allowed or (kind, ident) in observed:
                raise CutoverGoError("Boca postdeploy foreign or duplicate removal")
            observed.add((kind, ident))
        return raw.decode("ascii")
    except (UnicodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise CutoverGoError("Boca postdeploy exact receipt missing or malformed") from exc


def classify_cutover_ssh_failure(environment: Mapping[str, str]) -> str:
    """Report only allowlisted host claims after a FAILED SSH step.

    This is diagnostic metadata, never an authenticated terminal receipt.
    It cannot turn a remote NO_GO into accepted host evidence.
    """
    if (
        environment.get("BOCA_OPERATION") != "cutover-a-apply"
        or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
    ):
        raise CutoverGoError("Cutover SSH diagnosis wrong event/operation")
    rc_raw = environment.get("BOCA_CUTOVER_A_SSH_RC", "")
    if re.fullmatch(r"[1-9][0-9]{0,2}", rc_raw) is None or int(rc_raw) > 255:
        raise CutoverGoError("Cutover SSH diagnosis requires bounded nonzero exit")
    ssh_rc = int(rc_raw)
    try:
        raw = _read_bounded(Path(environment["RUNNER_TEMP"]) / HOST_RECEIPT_NAME, 9000)
    except (CutoverGoError, KeyError, OSError, ValueError):
        raw = b""
    recorded = b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n"
    unverified = b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=UNVERIFIED runtime=UNVERIFIED\n"
    host_claim = "NONE"
    phase_claim = "UNVERIFIED"
    candidate_claim: CandidateEvidence | None = None
    worker_primary_claim = "UNVERIFIED"
    worker_compensation_claim = "UNVERIFIED"
    worker_exit_code_claim = "UNKNOWN"
    worker_oom_claim = "UNKNOWN"
    worker_exit_signature_claim = ""
    worker_observation_claim = ""
    if raw.endswith(recorded):
        prefix = raw[: -len(recorded)]
        observe = _CUTOVER_OBSERVE_PREFIX.match(prefix)
        if observe is not None:
            # Exactly one canonical observation is allowed before postflight.
            # Any duplicate or malformed line remains unverified below.
            prefix = prefix[observe.end() :]
        # Postflight and phase are only bounded host claims, not physical ACK.
        if prefix.startswith(_POSTFLIGHT_PREFIX):
            postflight_line, separator, prefix = prefix.partition(b"\n")
            if not separator or len(postflight_line) > 8000:
                prefix = b"\x00"
        candidate_line = re.match(
            rb"BOCA_CUTOVER_A_CANDIDATE_FAILURE ([^\n]{1,180}) "
            rb"run=([1-9][0-9]{0,19}) sha=([0-9a-f]{40})\n",
            prefix,
        )
        if (
            candidate_line is not None
            and ssh_rc == 3
            and candidate_line[2].decode("ascii") == environment.get("GITHUB_RUN_ID")
            and candidate_line[3].decode("ascii")
            == environment.get("GITHUB_SHA")
            == environment.get("BOCA_SOURCE_SHA")
            and prefix[candidate_line.end() :]
            == b"BOCA_CUTOVER_A_FAILURE_PHASE phase=ACCEPT_CANDIDATE\n"
        ):
            try:
                candidate_claim = CandidateEvidence.parse(candidate_line[1].decode("ascii"))
                prefix = prefix[candidate_line.end() :]
            except (UnicodeError, ValueError):
                candidate_claim = None
        worker_v3 = re.match(
            rb"BOCA_CUTOVER_A_WORKER_FAILURE primary=([A-Z_]{2,32}) "
            rb"compensation=([A-Z_]{2,32}) exit_code=(0|[1-9][0-9]{0,2}|UNKNOWN) "
            rb"oom=(YES|NO|UNKNOWN)"
            rb"(?: signature=((?:EMPTY|PRESENT_UNCLASSIFIED|UNKNOWN)\."
            rb"(?:EXITED|DEAD|OTHER|UNKNOWN)\."
            rb"(?:EARLY_LT_5S|LATE_GE_5S|UNKNOWN)\."
            rb"(?:NOT_RUN|RAN|UNKNOWN))"
            rb"(?: stderr_observation=([A-Z_]{2,48}) "
            rb"run=([1-9][0-9]{0,19}) sha=([0-9a-f]{40}))?)?\n",
            prefix,
        )
        if worker_v3 is not None and worker_v3.group(6) is not None:
            if not (
                ssh_rc == 3
                and is_capture_result(worker_v3.group(6).decode("ascii"))
                and worker_v3.group(7).decode("ascii") == environment.get("GITHUB_RUN_ID")
                and worker_v3.group(8).decode("ascii")
                == environment.get("GITHUB_SHA")
                == environment.get("BOCA_SOURCE_SHA")
            ):
                worker_v3 = None
        valid_v3 = (
            worker_v3 is not None
            and worker_v3.group(1) == b"HEALTH_EXITED"
            and (worker_v3.group(3) == b"UNKNOWN" or int(worker_v3.group(3)) <= 255)
        )
        worker_match = (
            worker_v3
            if valid_v3
            else re.match(
                rb"BOCA_CUTOVER_A_WORKER_FAILURE primary=([A-Z_]{2,32}) "
                rb"compensation=([A-Z_]{2,32})\n",
                prefix,
            )
        )
        worker_primary_candidate = ""
        worker_compensation_candidate = ""
        if worker_match is not None:
            worker_primary_candidate = worker_match.group(1).decode("ascii")
            worker_compensation_candidate = worker_match.group(2).decode("ascii")
            prefix = prefix[worker_match.end() :]
        if prefix == b"":
            host_claim = "NO_GO_RECORDED_UNVERIFIED"
        else:
            match = re.fullmatch(rb"BOCA_CUTOVER_A_FAILURE_PHASE phase=([A-Z_]{2,32})\n", prefix)
            if match is not None:
                candidate = match.group(1).decode("ascii")
                if candidate in CUTOVER_FAILURE_PHASES:
                    if worker_match is None or (
                        candidate == "PREPARE_WORKER"
                        and worker_primary_candidate in WORKER_PRIMARY_PHASES
                        and worker_compensation_candidate in WORKER_COMPENSATION_STATES
                    ):
                        phase_claim = candidate
                        host_claim = "NO_GO_RECORDED_UNVERIFIED"
                        if worker_match is not None:
                            worker_primary_claim = worker_primary_candidate
                            worker_compensation_claim = worker_compensation_candidate
                            if valid_v3 and worker_v3 is not None:
                                worker_exit_code_claim = worker_v3.group(3).decode("ascii")
                                worker_oom_claim = worker_v3.group(4).decode("ascii")
                                if worker_v3.group(5) is not None:
                                    worker_exit_signature_claim = worker_v3.group(5).decode("ascii")
                                if worker_v3.group(6) is not None:
                                    worker_observation_claim = worker_v3.group(6).decode("ascii")
    elif raw == unverified:
        host_claim = "NO_GO_UNVERIFIED"
    # This is a code-path inference from an allowlisted HOST CLAIM, never a
    # second Docker ACK or an explanation of the worker's internal exception.
    # The adapter checks the exact docker-start CID before HEALTH_EXITED.
    worker_start_ack_claim = "UNVERIFIED"
    worker_cause_evidence = "UNVERIFIED"
    if (
        ssh_rc == 3
        and host_claim == "NO_GO_RECORDED_UNVERIFIED"
        and phase_claim == "PREPARE_WORKER"
        and worker_primary_claim == "HEALTH_EXITED"
        and worker_compensation_claim == "VERIFIED"
        and worker_exit_code_claim == "1"
        and worker_oom_claim == "NO"
    ):
        worker_start_ack_claim = "EXACT_CID_IMPLIED_BY_HEALTH_PHASE"
        worker_cause_evidence = "INFERENCE_NOT_CAUSE"
    transport = "TIMEOUT" if ssh_rc == 124 else "SSH_255" if ssh_rc == 255 else "EXIT_NONZERO"
    if candidate_claim is not None and phase_claim == "ACCEPT_CANDIDATE":
        return (
            f"BOCA_CUTOVER_A_SSH_DIAGNOSTIC state=NO_GO ssh_rc={ssh_rc} "
            f"transport={transport} host_claim={host_claim} phase_claim={phase_claim} "
            f"candidate_check_claim={candidate_claim.check} candidate_result_claim={candidate_claim.result} "
            f"original_restored_claim={'VERIFIED' if candidate_claim.original_restored else 'UNVERIFIED'} "
            f"cleanup_claim={candidate_claim.cleanup} terminal_state_claim={candidate_claim.terminal} "
            "phase=UNVERIFIED host=UNVERIFIED terminal=UNVERIFIED no_retry=true"
        )
    return (
        f"BOCA_CUTOVER_A_SSH_DIAGNOSTIC state=NO_GO ssh_rc={ssh_rc} "
        f"transport={transport} host_claim={host_claim} phase_claim={phase_claim} "
        f"worker_primary_claim={worker_primary_claim} "
        f"worker_compensation_claim={worker_compensation_claim} "
        f"worker_exit_code_claim={worker_exit_code_claim} worker_oom_claim={worker_oom_claim} "
        + (
            f"worker_exit_signature_claim={worker_exit_signature_claim} "
            if worker_exit_signature_claim
            else ""
        )
        + f"worker_start_ack_claim={worker_start_ack_claim} "
        + (
            f"worker_stderr_observation_claim={worker_observation_claim} "
            if worker_observation_claim
            else ""
        )
        + f"worker_internal_cause=UNKNOWN worker_cause_evidence={worker_cause_evidence} "
        "phase=UNVERIFIED "
        "host=UNVERIFIED terminal=UNVERIFIED no_retry=true"
    )


def assert_actions_host_receipt(environment: Mapping[str, str]) -> str | None:
    """Fail closed on wrong SSH/GO or incomplete v2 cleanup; preserve v1 ABI."""
    if (
        environment.get("BOCA_OPERATION") != "cutover-a-apply"
        or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or environment.get("BOCA_CUTOVER_A_GO_PREFLIGHT") != "success"
        or environment.get("BOCA_CUTOVER_A_HOST_APPLY") != "success"
        or not RUN.fullmatch(environment.get("GITHUB_RUN_ID", ""))
        or re.fullmatch(r"[0-9a-f]{40}", environment.get("GITHUB_SHA", "")) is None
        or environment.get("GITHUB_SHA") != environment.get("BOCA_SOURCE_SHA")
    ):
        raise CutoverGoError("Cutover A GO/SSH step lacks positive evidence")
    runner = Path(environment.get("RUNNER_TEMP", ""))
    expected = (
        f"BOCA_CUTOVER_A_HOST state=ACCEPTED "
        f"attempt={environment['GITHUB_RUN_ID']} "
        f"target_sha={environment['GITHUB_SHA']} "
        "cleanup=ACCEPT receipt=RECORDED runtime=UNVERIFIED\n"
    ).encode("ascii")
    # The exact invocation/digest were already produced by the independent
    # reviewed GO preflight. Recheck their identity rather than trusting an
    # injected host receipt to choose legacy v1 or prepared GO_B v2.
    token_raw = _read_bounded(runner / HOST_INVOCATION_NAME, MAX_REQUEST)
    digest_raw = _read_bounded(runner / HOST_APPROVAL_NAME, 80)
    if (
        not token_raw.endswith(b"\n")
        or token_raw.count(b"\n") != 1
        or not digest_raw.endswith(b"\n")
        or digest_raw.count(b"\n") != 1
    ):
        raise CutoverGoError("Cutover A host invocation/GO artifacts malformed")
    try:
        invocation = CutoverInvocation.decode(token_raw[:-1].decode("ascii"))
        approved = digest_raw[:-1].decode("ascii")
    except (UnicodeError, CutoverCliError) as exc:
        raise CutoverGoError("Cutover A reviewed invocation unparseable") from exc
    if (
        invocation.plan.attempt_id != environment["GITHUB_RUN_ID"]
        or invocation.plan.target_sha != environment["GITHUB_SHA"]
        or not HEX.fullmatch(approved)
        or invocation.go_binding_sha256 != approved
    ):
        raise CutoverGoError("Cutover A host receipt differs from reviewed GO and release")
    raw = _read_bounded(runner / HOST_RECEIPT_NAME, 9000)
    if invocation.dispatch_v3:
        # The real host observer prints before the transaction's terminal ACK.
        # V3 requires exactly one full, plan-matching observation, not a regex
        # accepting some other valid-looking source or installed controller.
        plan = invocation.plan
        observed = (
            "BOCA_CUTOVER_A_OBSERVE state=READY"
            f" legacy_sha={plan.legacy_sha} legacy_id={plan.legacy_id}"
            f" legacy_image={plan.legacy_image} target_sha={plan.target_sha}"
            f" target_image={plan.target_image} browser_image={plan.browser_image}"
            " original=RUNNING port=127.0.0.1:8443 worker=absent"
            " owner=preserved key=preserved data=preserved effects=none\n"
        ).encode("ascii")
        if not raw.startswith(observed):
            raise CutoverGoError("V3 exact original observation absent or mismatched")
        raw = raw[len(observed) :]
    if environment.get("BOCA_REQUIRE_IDLE_INSTALL") == "1":
        from boca_socios.host_boca_cutover_cli import IDLE_RECEIPT

        if not invocation.dispatch_v3:
            raise CutoverGoError("idle installation requires protected V3")
        expected += (IDLE_RECEIPT + "\n").encode("ascii")
    if invocation.prepare_run_id is None and not invocation.dispatch_v3:
        if raw != expected:
            raise CutoverGoError("Cutover A terminal receipt missing or ambiguous")
        return None
    if not raw.startswith(expected):
        raise CutoverGoError("Cutover A GO_B terminal ACK absent")
    postflight = raw[len(expected) :]
    if (
        not postflight.startswith(_POSTFLIGHT_PREFIX)
        or not postflight.endswith(b"\n")
        or postflight.count(b"\n") != 1
    ):
        raise CutoverGoError("Cutover A GO_B postflight receipt absent or ambiguous")
    return verify_postflight_json(
        postflight[len(_POSTFLIGHT_PREFIX) : -1], environment["GITHUB_RUN_ID"]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Protected GO verifier; no SSH/Docker")
    parser.add_argument("request_path", type=Path, nargs="?")
    parser.add_argument("--from-actions", action="store_true")
    parser.add_argument("--prepared-from-actions", action="store_true")
    parser.add_argument("--assert-host-receipt", action="store_true")
    parser.add_argument("--report-host-failure", action="store_true")
    parser.add_argument(
        "--dispatch-command", choices=("cutover-a-dispatch-v3", "cutover-a-capture-readback-v3")
    )
    args = parser.parse_args(argv)
    if args.dispatch_command:
        from boca_socios.host_cutover_capture_readback import command

        if (
            args.request_path is not None
            or args.from_actions
            or args.prepared_from_actions
            or args.assert_host_receipt
            or args.report_host_failure
        ):
            return 1
        try:
            print(command(args.dispatch_command, os.environ, read_bounded=_read_bounded))
        except (OSError, ValueError, KeyError, TypeError):
            print("BOCA_CUTOVER_A_DISPATCH_COMMAND state=NO_GO", file=sys.stderr)
            return 1
        return 0
    try:
        if args.report_host_failure:
            if (
                args.request_path is not None
                or args.from_actions
                or args.prepared_from_actions
                or args.assert_host_receipt
            ):
                raise CutoverGoError("Cutover SSH diagnosis arguments unexpected")
            print(classify_cutover_ssh_failure(os.environ))
            return 0
        if args.assert_host_receipt:
            if args.request_path is not None or args.from_actions or args.prepared_from_actions:
                raise CutoverGoError("Cutover A receipt assertion arguments unexpected")
            postflight = assert_actions_host_receipt(os.environ)
            if postflight is not None:
                # This public JSON contains only Boca exact IDs and storage
                # counters, not owner credentials or arbitrary Docker fields.
                print("BOCA_CUTOVER_A_POSTFLIGHT_VERIFIED " + postflight)
            print("BOCA_CUTOVER_A_HOST_VERIFY state=PASS receipt=EXACT runtime=UNVERIFIED")
            return 0
        if args.from_actions and args.prepared_from_actions:
            raise CutoverGoError("Cutover A cannot combine legacy and prepared GO")
        if args.prepared_from_actions:
            if args.request_path is not None:
                raise CutoverGoError("Cutover A PREPARE cannot load caller request")
            request = actions_request(os.environ)
            approved = write_actions_invocation_prepared(request, environ=os.environ)
        elif args.from_actions:
            if args.request_path is not None:
                raise CutoverGoError("Actions Cutover A cannot load caller request")
            request = actions_request(os.environ)
            approved = write_actions_invocation(
                request,
                protected_go_digest=os.environ.get("BOCA_CUTOVER_A_GO_BINDING_SHA256", ""),
            )
        else:
            if args.request_path is None:
                raise CutoverGoError("Cutover A request is absent")
            raw = _read_bounded(args.request_path, MAX_REQUEST)
            request = GoRequest.from_json(
                json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
            )
            approved = require_protected_go(
                request,
                protected_go_digest=os.environ.get("BOCA_CUTOVER_A_GO_BINDING_SHA256", ""),
            )
    except (CutoverGoError, CutoverCliError, UnicodeError, json.JSONDecodeError, TypeError):
        if args.assert_host_receipt or args.report_host_failure:
            print("BOCA_CUTOVER_A_HOST_VERIFY state=NO_GO host=UNVERIFIED", file=sys.stderr)
        else:
            print("BOCA_CUTOVER_A_GO state=NO_GO host=untouched", file=sys.stderr)
        return 1
    print(f"BOCA_CUTOVER_A_GO state=PASS sha256={approved} host=untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
