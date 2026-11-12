"""Deterministic sector selection from fictional, offline availability data.

Preferences describe *one* logical ticket intent per member and event. Evaluating
them never creates a browser session, joins a queue, or attempts a reservation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from boca_socios.domain.policy import TicketIntent


class SectorMode(StrEnum):
    """Selection priority when only one simulated ticket is allowed."""

    ALL = "ALL"
    ORDERED_ALLOWLIST = "ORDERED_ALLOWLIST"


def _check_sector_ids(ids: Sequence[str], *, require_nonempty: bool) -> None:
    if require_nonempty and not ids:
        raise ValueError("at least one sector_id is required")
    if any(
        not isinstance(sector_id, str) or not sector_id or sector_id.strip() != sector_id
        for sector_id in ids
    ):
        raise ValueError("sector IDs must be nonempty strings without surrounding whitespace")
    if len(set(ids)) != len(ids):
        raise ValueError("sector IDs must be unique")


@dataclass(frozen=True, slots=True)
class SectorPreference:
    """Immutable owner preference, scoped to a member and a fictional event."""

    member_id: str
    event_id: str
    mode: SectorMode
    sector_ids: tuple[str, ...]
    version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        TicketIntent(self.member_id, self.event_id, 1).validate()
        if not isinstance(self.mode, SectorMode):
            raise ValueError("invalid sector preference mode")
        if not isinstance(self.sector_ids, tuple):
            raise ValueError("sector_ids must be an ordered tuple")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer")
        if (
            not isinstance(self.updated_at, datetime)
            or self.updated_at.tzinfo is None
            or self.updated_at.utcoffset() is None
        ):
            raise ValueError("updated_at must be timezone-aware")
        _check_sector_ids(
            self.sector_ids,
            require_nonempty=self.mode is SectorMode.ORDERED_ALLOWLIST,
        )
        if self.mode is SectorMode.ALL and self.sector_ids:
            raise ValueError("ALL mode does not take an explicit sector allowlist")


@dataclass(frozen=True, slots=True)
class SectorEvaluation:
    """Single offline choice; `None` means no sector can be selected."""

    ticket_intent: TicketIntent
    considered_sector_ids: tuple[str, ...]
    unavailable_sector_ids: tuple[str, ...]
    selected_sector_id: str | None


def evaluate_sector_preference(
    preference: SectorPreference,
    catalog_sector_ids: Sequence[str],
    availability: Mapping[str, bool],
) -> SectorEvaluation:
    """Choose the first available fictional sector; missing data is unavailable.

    The catalog defines priority for ALL mode. ORDERED_ALLOWLIST explicitly
    overrides that ordering. Unknown IDs fail closed rather than being ignored.
    This pure function has no side effects and does not reserve tickets.
    """

    catalog = tuple(catalog_sector_ids)
    _check_sector_ids(catalog, require_nonempty=True)
    known = set(catalog)
    if not isinstance(availability, Mapping):
        raise ValueError("availability must be a sector mapping")
    if any(key not in known for key in availability):
        raise ValueError("availability references unknown sectors")
    if any(type(value) is not bool for value in availability.values()):
        raise ValueError("availability values must be boolean")

    if preference.mode is SectorMode.ALL:
        considered = catalog
    else:
        if any(sector_id not in known for sector_id in preference.sector_ids):
            raise ValueError("preference references unknown sectors")
        considered = preference.sector_ids

    unavailable: list[str] = []
    selected: str | None = None
    for sector_id in considered:
        if availability.get(sector_id, False):
            selected = sector_id
            break
        unavailable.append(sector_id)

    intent = TicketIntent(preference.member_id, preference.event_id, quantity=1)
    intent.validate()
    return SectorEvaluation(
        ticket_intent=intent,
        considered_sector_ids=considered,
        unavailable_sector_ids=tuple(unavailable),
        selected_sector_id=selected,
    )
