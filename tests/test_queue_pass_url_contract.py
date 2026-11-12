"""Issue #12: only a supplied queueittoken may enter the private monitor."""

from datetime import UTC, datetime
from importlib import import_module

import pytest

from boca_socios.queue.pass_observation import QueuePassObservation, QueuePassState

OBSERVED = datetime(2026, 11, 12, 11, 0, tzinfo=UTC)


def _observation(url: str, *, session: str = "session-1") -> QueuePassObservation:
    return QueuePassObservation.from_observed_url(
        member_id="member-1",
        event_id="event-1",
        session_id=session,
        target_url=url,
        observed_at=OBSERVED,
    )


def _monitor(limit: int) -> object:
    # Resolve the new module at call time so pre-implementation RED is a
    # failing contract test, not a pytest collection error.
    cls = import_module("boca_socios.queue.private_pass_monitor").PrivateQueuePassMonitor
    return cls(max_observations=limit)


def test_observed_url_retains_complete_original_and_extracts_existing_query_token() -> None:
    url = (
        "https://sandbox.invalid/queue/entry?e=fixture&queueittoken=only%2Fobserved%3D"
        "&return=%2Fprivate%3Fa%3D1#fragment"
    )
    pass_value = _observation(url)
    owner = pass_value.private_owner_details(owner_authenticated=True, at=OBSERVED)

    assert owner.state is QueuePassState.OBSERVED_UNVERIFIED
    assert owner.copy_full_token() == "only/observed="
    assert owner.copy_full_target_url() == url
    assert "only/observed" not in repr(pass_value)


@pytest.mark.parametrize(
    "url",
    [
        "https://sandbox.invalid/queue?queueId=not-a-token",
        "https://sandbox.invalid/queue?queueittoken=",
        "https://sandbox.invalid/queue?queueittoken=x&queueittoken=y",
        "https://sandbox.invalid/queue#queueittoken=fragment-only",
        "https://sandbox.invalid/queue?queueittoken=%20%20",
    ],
)
def test_missing_empty_or_duplicate_token_is_not_promoted_to_observed(url: str) -> None:
    with pytest.raises(ValueError, match="queueittoken"):
        _observation(url)


def test_private_monitor_separates_sessions_and_never_returns_secrets_in_summary() -> None:
    monitor = _monitor(2)
    first = _observation("https://sandbox.invalid/?queueittoken=first-private", session="session-1")
    second = _observation(
        "https://sandbox.invalid/?queueittoken=second-private", session="session-2"
    )
    monitor.observe(first)
    monitor.observe(second)

    summaries = monitor.list_summaries(at=OBSERVED)
    assert len(summaries) == 2
    assert {item.session_id for item in summaries} == {"session-1", "session-2"}
    assert all(item.state is QueuePassState.OBSERVED_UNVERIFIED for item in summaries)
    assert "first-private" not in repr(summaries)
    assert "second-private" not in repr(monitor)
    assert (
        monitor.owner_details(
            "member-1", "event-1", "session-2", at=OBSERVED, owner_authenticated=True
        ).copy_full_token()
        == "second-private"
    )

    with pytest.raises(PermissionError):
        monitor.owner_details(
            "member-1", "event-1", "session-1", at=OBSERVED, owner_authenticated=False
        )
    assert (
        monitor.owner_details(
            "member-1", "event-1", "absent", at=OBSERVED, owner_authenticated=True
        )
        is None
    )


def test_private_monitor_rejects_growth_beyond_bound_without_evicting_observations() -> None:
    monitor = _monitor(1)
    monitor.observe(_observation("https://sandbox.invalid/?queueittoken=first"))

    with pytest.raises(ValueError, match="limit"):
        monitor.observe(
            _observation("https://sandbox.invalid/?queueittoken=second", session="session-2")
        )
    assert len(monitor.list_summaries(at=OBSERVED)) == 1
    monitor.observe(_observation("https://sandbox.invalid/?queueittoken=replacement"))
    assert (
        monitor.owner_details(
            "member-1", "event-1", "session-1", at=OBSERVED, owner_authenticated=True
        ).copy_full_token()
        == "replacement"
    )
