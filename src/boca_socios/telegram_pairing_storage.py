"""Storage boundary for the existing same-lease pairing transaction."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from boca_socios.host_boca_cleanup import BocaJobLease
    from boca_socios.telegram_bootstrap import RecipientReceipt
    from boca_socios.telegram_pairing_cutover import CutoverCoordinates
    from boca_socios.telegram_pairing_install import PairingCustodyReceipt
    from boca_socios.telegram_pairing_resolver import PairingInstallPlan
    from boca_socios.telegram_same_lease_stage import EncryptedPairingStage


class PairingStorage(Protocol):
    def read_stage(
        self,
        directory: Path,
        *,
        coordinates: CutoverCoordinates,
        lease: BocaJobLease,
        trusted_now: int | None = None,
    ) -> EncryptedPairingStage: ...
    def consume_nonce(
        self, directory: Path, nonce: str, coordinates: CutoverCoordinates, *, lease: BocaJobLease
    ) -> bool: ...
    def unseal(
        self, envelope: bytes, private: bytes | None, recipient: RecipientReceipt
    ) -> tuple[bytes, str]: ...
    def seal(self, recipient: RecipientReceipt, token: str, chat: str) -> bytes: ...
    def install(
        self, directory: Path, plan: PairingInstallPlan, *, expected_source_sha: str, now: int
    ) -> PairingCustodyReceipt: ...
    def verify(self, directory: Path, *, expected_source_sha: str) -> PairingCustodyReceipt: ...
