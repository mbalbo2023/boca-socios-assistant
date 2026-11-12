"""Pure fictional queue-pass observations, never live queue access."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone

import pytest

from boca_socios.queue.pass_observation import (
    OwnerQueuePassDetails,
    QueuePassObservation,
    QueuePassState,
)

OBSERVED_AT = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
FICTIONAL_TOKEN = "FICTIONAL_TEST_ONLY.alpha=beta&verbatim=alpha%2Fomega==  "
FICTIONAL_URL = "https://local-fixture.invalid/simulated?next=fictional"


def test_owner_receives_entire_opaque_token_and_observed_url_without_modification() -> None:
    observed = QueuePassObservation.observed(
        member_id="existing-member-42",
        event_id="fictional-event-1",
        session_id="synthetic-session-a",
        token=FICTIONAL_TOKEN,
        target_url=FICTIONAL_URL,
        observed_at=OBSERVED_AT,
        expires_at=OBSERVED_AT + timedelta(seconds=45),
    )
    status = observed.summary(at=OBSERVED_AT + timedelta(seconds=10))
    assert status.state is QueuePassState.OBSERVED_UNVERIFIED
    assert status.member_id == "existing-member-42"
    assert status.event_id == "fictional-event-1"
    assert status.session_id == "synthetic-session-a"
    assert status.observed_at == OBSERVED_AT

    owner = observed.private_owner_details(
        owner_authenticated=True, at=OBSERVED_AT + timedelta(seconds=10)
    )
    assert isinstance(owner, OwnerQueuePassDetails)
    assert owner.state is QueuePassState.OBSERVED_UNVERIFIED
    assert owner.copy_full_token() == FICTIONAL_TOKEN
    assert owner.target_url == FICTIONAL_URL
    assert owner.copy_full_target_url() == FICTIONAL_URL
    assert owner.expires_at == OBSERVED_AT + timedelta(seconds=45)


def test_safe_surfaces_never_expose_complete_token_or_destination() -> None:
    observed = QueuePassObservation.observed(
        member_id="m1",
        event_id="e1",
        session_id="s1",
        token=FICTIONAL_TOKEN,
        target_url=FICTIONAL_URL,
        observed_at=OBSERVED_AT,
    )
    summary = observed.summary(at=OBSERVED_AT)
    owner = observed.private_owner_details(owner_authenticated=True, at=OBSERVED_AT)
    for safe_text in (repr(observed), repr(summary), repr(owner), str(asdict(summary))):
        assert FICTIONAL_TOKEN not in safe_text
        assert FICTIONAL_URL not in safe_text
        assert "alpha%2Fomega" not in safe_text
    assert "token" not in asdict(summary)
    assert "target_url" not in asdict(summary)


@pytest.mark.parametrize("unauthorized", [False, None, 1, "true"])
def test_no_owner_authorization_means_no_private_projection(unauthorized: object) -> None:
    observed = QueuePassObservation.observed(
        member_id="m1",
        event_id="e1",
        session_id="s1",
        token=FICTIONAL_TOKEN,
        target_url=FICTIONAL_URL,
        observed_at=OBSERVED_AT,
    )
    with pytest.raises(PermissionError, match="authenticated owner"):
        observed.private_owner_details(
            owner_authenticated=unauthorized,
            at=OBSERVED_AT,  # type: ignore[arg-type]
        )


def test_unobserved_and_unknown_are_distinct_without_inventing_tokens() -> None:
    not_seen = QueuePassObservation.not_observed(member_id="m1", event_id="e1", session_id="s1")
    unknown = QueuePassObservation.unknown(member_id="m1", event_id="e1", session_id="s1")
    assert not_seen.summary(at=OBSERVED_AT).state is QueuePassState.NOT_OBSERVED
    assert unknown.summary(at=OBSERVED_AT).state is QueuePassState.UNKNOWN
    for observation in (not_seen, unknown):
        owner = observation.private_owner_details(owner_authenticated=True, at=OBSERVED_AT)
        assert owner.target_url is None
        with pytest.raises(ValueError, match="no observed token"):
            owner.copy_full_token()
        with pytest.raises(ValueError, match="no observed destination"):
            owner.copy_full_target_url()


def test_expiry_is_not_silently_treated_as_valid_admission() -> None:
    expires = OBSERVED_AT + timedelta(seconds=30)
    observed = QueuePassObservation.observed(
        member_id="m1",
        event_id="e1",
        session_id="s1",
        token=FICTIONAL_TOKEN,
        target_url=None,
        observed_at=OBSERVED_AT,
        expires_at=expires,
    )
    assert (
        observed.summary(at=expires - timedelta(microseconds=1)).state
        is QueuePassState.OBSERVED_UNVERIFIED
    )
    assert observed.summary(at=expires).state is QueuePassState.EXPIRED
    assert observed.summary(at=expires + timedelta(hours=1)).state is QueuePassState.EXPIRED
    owner = observed.private_owner_details(owner_authenticated=True, at=expires)
    assert owner.state is QueuePassState.EXPIRED
    assert owner.copy_full_token() == FICTIONAL_TOKEN


def test_unknown_expiry_is_unverified_not_validated() -> None:
    observed = QueuePassObservation.observed(
        member_id="m1",
        event_id="e1",
        session_id="s1",
        token=FICTIONAL_TOKEN,
        target_url=None,
        observed_at=OBSERVED_AT,
    )
    assert (
        observed.summary(at=OBSERVED_AT + timedelta(days=700)).state
        is QueuePassState.OBSERVED_UNVERIFIED
    )


def test_timezone_offsets_are_compared_by_instant() -> None:
    offset_time = OBSERVED_AT.astimezone(timezone(timedelta(hours=-3)))
    observed = QueuePassObservation.observed(
        member_id="m1",
        event_id="e1",
        session_id="s1",
        token=FICTIONAL_TOKEN,
        target_url=None,
        observed_at=offset_time,
        expires_at=offset_time + timedelta(minutes=1),
    )
    assert observed.summary(at=OBSERVED_AT + timedelta(minutes=1)).state is QueuePassState.EXPIRED


@pytest.mark.parametrize("bad_time", [datetime(2026, 11, 11), datetime.min])
def test_naive_times_are_rejected(bad_time: datetime) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        QueuePassObservation.observed(
            member_id="m1",
            event_id="e1",
            session_id="s1",
            token=FICTIONAL_TOKEN,
            target_url=None,
            observed_at=bad_time,
        )
    obs = QueuePassObservation.not_observed(member_id="m1", event_id="e1", session_id="s1")
    with pytest.raises(ValueError, match="timezone-aware"):
        obs.summary(at=bad_time)


def test_inconsistent_expiry_and_blank_identifiers_or_token_are_rejected() -> None:
    with pytest.raises(ValueError, match="after the observation"):
        QueuePassObservation.observed(
            member_id="m1",
            event_id="e1",
            session_id="s1",
            token=FICTIONAL_TOKEN,
            target_url=None,
            observed_at=OBSERVED_AT,
            expires_at=OBSERVED_AT - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="nonblank token"):
        QueuePassObservation.observed(
            member_id="m1",
            event_id="e1",
            session_id="s1",
            token="  ",
            target_url=None,
            observed_at=OBSERVED_AT,
        )
    with pytest.raises(ValueError, match="nonblank"):
        QueuePassObservation.not_observed(member_id="", event_id="e1", session_id="s1")


def test_multiple_observations_share_existing_member_event_identity_without_request_creation() -> (
    None
):
    first = QueuePassObservation.observed(
        member_id="registered-member-42",
        event_id="synthetic-event-1",
        session_id="session-a",
        token="FICTIONAL_A",
        target_url=None,
        observed_at=OBSERVED_AT,
    )
    second = QueuePassObservation.observed(
        member_id="registered-member-42",
        event_id="synthetic-event-1",
        session_id="session-b",
        token="FICTIONAL_B",
        target_url=None,
        observed_at=OBSERVED_AT,
    )
    assert first.summary(at=OBSERVED_AT).member_id == second.summary(at=OBSERVED_AT).member_id
    assert first.summary(at=OBSERVED_AT).event_id == second.summary(at=OBSERVED_AT).event_id
    assert first.summary(at=OBSERVED_AT).session_id != second.summary(at=OBSERVED_AT).session_id
