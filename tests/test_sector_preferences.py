"""Purely offline sector preferences; no navigation, queue or ticket operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest

from boca_socios.domain.policy import TicketIntent
from boca_socios.domain.sector_preferences import (
    SectorMode,
    SectorPreference,
    evaluate_sector_preference,
)
from boca_socios.queue import OfflineQueueSimulator, SimulatorConfig

STAMP = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
CATALOG = ("sector_norte", "sector_sur", "sector_este")


def ordered(*sector_ids: str) -> SectorPreference:
    return SectorPreference(
        member_id="opaque-member",
        event_id="fictional-event",
        mode=SectorMode.ORDERED_ALLOWLIST,
        sector_ids=sector_ids,
        version=1,
        updated_at=STAMP,
    )


def all_sectors() -> SectorPreference:
    return SectorPreference(
        member_id="opaque-member",
        event_id="fictional-event",
        mode=SectorMode.ALL,
        sector_ids=(),
        version=1,
        updated_at=STAMP,
    )


def test_ordered_preference_selects_only_first_available_sector() -> None:
    result = evaluate_sector_preference(
        ordered("sector_este", "sector_norte", "sector_sur"),
        CATALOG,
        {"sector_este": False, "sector_norte": True, "sector_sur": True},
    )

    assert result.considered_sector_ids == ("sector_este", "sector_norte", "sector_sur")
    assert result.selected_sector_id == "sector_norte"
    assert result.unavailable_sector_ids == ("sector_este",)
    assert result.ticket_intent == TicketIntent("opaque-member", "fictional-event", 1)


def test_all_mode_follows_catalog_order_and_never_creates_extra_ticket() -> None:
    result = evaluate_sector_preference(
        all_sectors(),
        CATALOG,
        {"sector_norte": False, "sector_sur": True, "sector_este": True},
    )

    assert result.considered_sector_ids == CATALOG
    assert result.selected_sector_id == "sector_sur"
    assert result.unavailable_sector_ids == ("sector_norte",)
    assert result.ticket_intent.quantity == 1


def test_absent_availability_data_fails_closed_without_a_sector_choice() -> None:
    result = evaluate_sector_preference(ordered("sector_este", "sector_sur"), CATALOG, {})
    assert result.selected_sector_id is None
    assert result.unavailable_sector_ids == ("sector_este", "sector_sur")
    assert result.ticket_intent.quantity == 1


def test_non_available_sectors_are_skipped_and_not_selected() -> None:
    result = evaluate_sector_preference(
        ordered("sector_este", "sector_sur"),
        CATALOG,
        {"sector_este": False, "sector_sur": True},
    )
    assert result.selected_sector_id == "sector_sur"


@pytest.mark.parametrize(
    "sector_ids",
    [(), ("sector_norte", "sector_norte"), ("",), (" sector_norte",), ("sector_norte ",)],
)
def test_ordered_sector_identifiers_must_be_nonempty_unique_and_exact(
    sector_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        ordered(*sector_ids)


def test_all_mode_cannot_also_include_explicit_allowlist() -> None:
    with pytest.raises(ValueError):
        SectorPreference(
            member_id="opaque-member",
            event_id="fictional-event",
            mode=SectorMode.ALL,
            sector_ids=("sector_norte",),
            version=1,
            updated_at=STAMP,
        )


@pytest.mark.parametrize(
    ("member_id", "event_id"),
    [("", "fixture"), ("member", ""), (" ", "fixture"), ("member", " ")],
)
def test_member_and_event_required_for_single_logical_request(
    member_id: str, event_id: str
) -> None:
    with pytest.raises(ValueError):
        SectorPreference(
            member_id=member_id,
            event_id=event_id,
            mode=SectorMode.ALL,
            sector_ids=(),
            version=1,
            updated_at=STAMP,
        )


def test_invalid_versions_and_naive_timestamps_rejected() -> None:
    for version in (-1, 0, True):
        with pytest.raises(ValueError):
            SectorPreference("m", "e", SectorMode.ALL, (), version, STAMP)
    with pytest.raises(ValueError):
        SectorPreference("m", "e", SectorMode.ALL, (), 1, datetime(2026, 11, 11))


def test_unknown_catalog_sector_fails_instead_of_silently_substituting() -> None:
    with pytest.raises(ValueError, match="unknown"):
        evaluate_sector_preference(ordered("fake-sector"), CATALOG, {})


def test_duplicate_or_empty_catalog_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_sector_preference(all_sectors(), ("sector_norte", "sector_norte"), {})
    with pytest.raises(ValueError):
        evaluate_sector_preference(all_sectors(), (), {})


def test_availability_map_rejects_unknown_keys_and_nonboolean_values() -> None:
    with pytest.raises(ValueError):
        evaluate_sector_preference(all_sectors(), CATALOG, {"fake-sector": True})
    with pytest.raises(ValueError):
        evaluate_sector_preference(all_sectors(), CATALOG, {"sector_sur": 1})


def test_evaluation_does_not_modify_catalog_or_availability() -> None:
    availability = {"sector_norte": False, "sector_sur": True}
    original = availability.copy()
    result = evaluate_sector_preference(all_sectors(), CATALOG, MappingProxyType(availability))

    assert result.considered_sector_ids == CATALOG
    assert availability == original


def test_multisession_preference_shares_one_simulated_logical_request() -> None:
    queue = OfflineQueueSimulator(
        SimulatorConfig(
            event_id="fictional-event",
            opens_at=STAMP + timedelta(minutes=5),
            closes_at=STAMP + timedelta(minutes=15),
        )
    )
    first = queue.create_session("opaque-member", "local-session-1", STAMP)
    second = queue.create_session("opaque-member", "local-session-2", STAMP)
    selection = evaluate_sector_preference(
        ordered("sector_sur", "sector_norte"), CATALOG, {"sector_sur": True}
    )

    assert first.requested_quantity == second.requested_quantity == 1
    assert queue.session_count == 2
    assert queue.request_count == 1
    assert selection.ticket_intent == TicketIntent("opaque-member", "fictional-event", 1)
    assert selection.selected_sector_id == "sector_sur"
