"""Fail-closed pre-cutover contract for additive owner session schema 0008.

No host verifier is implemented or wired in this code-only draft. A release
manifest or user receipt alone cannot prove that the *legacy binary* will
resume after the installed database gains a migration it did not know.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.resources import files

from boca_socios.panel.owner_session_host_attestor import DockerStoppedControllerEvidence
from boca_socios.panel.owner_session_upgrade import (
    OwnerSessionUpgradeUnavailable,
    UpgradeResult,
    upgrade_existing_owner_schema_0008,
)

# GitHub main cabce9f1 (installed controller, 04/11/2026): packaged SQL 0001..0007
# only; operational.validate_existing_beta_storage rejects an unknown 0008
# ledger checksum, so its controller cannot resume against upgraded storage.
_KNOWN_LEGACY_REJECTS_0008 = frozenset({"cabce9f1e452e63ded115f447559a358dc0f4d1b"})


@dataclass(frozen=True, slots=True)
class LegacyResumeVerifier(ABC):
    """Exact-image, exact-attempt, live host proof contract, NOT a JSON receipt.

    A future protected Boca host implementation must execute the ORIGINAL
    immutable legacy image's real schema validation and restart/read-only
    startup paths against an isolated, entirely synthetic SQLite schema 0008,
    without connecting the installed owner/data/key volume. It must retain
    that verified image and the canonical Boca job lease throughout upgrade.
    There is intentionally no default implementation in this PR.
    """

    original_id: str
    attempt_id: str
    legacy_sha: str
    legacy_image: str
    owner_schema_0008_sha256: str

    @abstractmethod
    def hold_live_legacy_resume_proof(self) -> AbstractContextManager[None]:
        """Fail if real legacy resume compatibility or exact binding drifts."""


def owner_schema_0008_checksum() -> str:
    sql = (
        files("boca_socios.storage.migrations")
        .joinpath("0008_owner_browser_session.sql")
        .read_bytes()
    )
    return hashlib.sha256(sql).hexdigest()


def pre_cutover_upgrade_0008(
    evidence: DockerStoppedControllerEvidence,
    legacy_resume: LegacyResumeVerifier,
) -> UpgradeResult:
    """Perform 0008 only while the exact parked legacy is proven resumable.

    Caller remains responsible for one protected Actions job, parked controller
    and restoration/cleanup. A supported candidate is NOT inferred from
    source SHA or manifest: it must be proven by a live trusted verifier.
    """
    if not isinstance(evidence, DockerStoppedControllerEvidence):
        raise OwnerSessionUpgradeUnavailable("protected Boca controller evidence required")
    # This known installed binary fails on 0008 even if a fake verifier says GO.
    if evidence.legacy_sha in _KNOWN_LEGACY_REJECTS_0008:
        raise OwnerSessionUpgradeUnavailable("installed legacy cannot resume schema 0008")
    if evidence.borrowed_lease_fd is None:
        raise OwnerSessionUpgradeUnavailable("outer protected Boca job lease required")
    if not isinstance(legacy_resume, LegacyResumeVerifier):
        raise OwnerSessionUpgradeUnavailable("live legacy resume proof required")
    expected = (
        evidence.original_id,
        evidence.attempt_id,
        evidence.legacy_sha,
        evidence.legacy_image,
        owner_schema_0008_checksum(),
    )
    received = (
        legacy_resume.original_id,
        legacy_resume.attempt_id,
        legacy_resume.legacy_sha,
        legacy_resume.legacy_image,
        legacy_resume.owner_schema_0008_sha256,
    )
    if received != expected:
        raise OwnerSessionUpgradeUnavailable("legacy resume proof is stale or mismatched")
    with legacy_resume.hold_live_legacy_resume_proof():
        # Host volume path and current stopped-controller state are independently
        # re-validated by the concrete Docker attestor UNDER the canonical job
        # lease inside the additive migration. No user flag authorizes DDL.
        return upgrade_existing_owner_schema_0008(evidence, path=evidence.host_database_path())
