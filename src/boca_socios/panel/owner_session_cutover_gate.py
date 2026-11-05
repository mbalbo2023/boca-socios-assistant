"""Obsolete schema-0008 cutover entrypoint, permanently disabled for Option B.

The installed controller's original SQLite ledger must never gain 0008.
Use owner_session_upgrade.bootstrap_existing_owner_session instead, exclusively
inside the canonical one-host Boca transaction under the same held lease.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass

from boca_socios.panel.owner_session_host_attestor import DockerStoppedControllerEvidence
from boca_socios.panel.owner_session_upgrade import OwnerSessionUpgradeUnavailable, UpgradeResult


@dataclass(frozen=True, slots=True)
class LegacyResumeVerifier(ABC):
    """Retained only so previous callers fail closed rather than silently migrate."""

    original_id: str
    attempt_id: str
    legacy_sha: str
    legacy_image: str
    owner_schema_0008_sha256: str

    @abstractmethod
    def hold_live_legacy_resume_proof(self) -> AbstractContextManager[None]:
        """Historical no-longer-authorized proof path."""


def owner_schema_0008_checksum() -> str:
    """There is no approved 0008 in the controller's migration package."""
    raise OwnerSessionUpgradeUnavailable("legacy schema 0008 is prohibited by Option B")


def pre_cutover_upgrade_0008(
    evidence: DockerStoppedControllerEvidence,
    legacy_resume: LegacyResumeVerifier,
) -> UpgradeResult:
    """Even a positive old verifier can never authorize legacy migration."""
    raise OwnerSessionUpgradeUnavailable(
        "legacy schema 0008 migration prohibited; use separate Boca session store"
    )
