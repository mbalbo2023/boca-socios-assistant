"""Global owner observations must not acquire an invented member or event."""

from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

from boca_socios.browser.queue_page_observation import parse_queue_page_observation

NOW = datetime(2026, 11, 14, 18, 0, tzinfo=UTC)
TARGET = "https://received.example.invalid/?queueittoken=private-observed-value"


def monitor(*, configured=True):
    factory = getattr(
        import_module("boca_socios.queue.private_pass_monitor"),
        "PrivateAutomaticObservationMonitor",
        None,
    )
    assert factory is not None, "automatic global monitor is missing"
    return factory(configured=configured, now=lambda: NOW)


def observation(**kwargs):
    values = dict(
        final_url="https://received.example.invalid/",
        queue_model=None,
        markers=frozenset(),
        observed_at=NOW,
    )
    values.update(kwargs)
    return parse_queue_page_observation(**values)


def test_configured_monitor_has_no_fake_observation_or_provider_connection():
    source = monitor()
    state = source.snapshot()
    assert state == {
        "version": 1,
        "scope": "OWNER_GLOBAL",
        "source": "AUTOMATIC_QUEUE",
        "status": "AUTOMATIC_CONFIGURED",
        "configured": True,
        "latest": None,
        "has_target_url": False,
        "observed_at": NOW.isoformat(),
    }
    assert source.owner_global_details(owner_authenticated=True) is None
    assert source.activity_events() == ()
    assert monitor(configured=False).snapshot()["status"] == "NOT_CONFIGURED"


def test_private_observation_retains_actual_url_only_after_owner_reveal():
    source = monitor()
    source.mark_checking()
    assert source.snapshot()["status"] == "AUTOMATIC_CHECKING"
    supplied = observation(final_url=TARGET)
    source.observe_global(supplied)
    state = source.snapshot()
    assert state["status"] == "AUTOMATIC_OBSERVED"
    assert state["latest"] == supplied.metadata() and state["has_target_url"] is True
    assert "private-observed-value" not in repr(state)
    assert "member" not in repr(state) and "session_id" not in repr(state)
    with pytest.raises(PermissionError):
        source.owner_global_details(owner_authenticated=False)
    assert source.owner_global_details(owner_authenticated=True) is supplied
    assert [event.code for event in source.activity_events()] == [
        "automatic_checking",
        "automatic_observed",
    ]
    assert "private-observed-value" not in repr(source.activity_events())


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"visible_text": "No hay eventos disponibles"}, "AUTOMATIC_NO_EVENT"),
        ({"queue_model": {"isIdle": True}}, "AUTOMATIC_NO_QUEUE"),
        ({"check_failed": True}, "AUTOMATIC_FAILED"),
        ({"markers": frozenset({"challenge"})}, "AUTOMATIC_FAILED"),
        ({}, "AUTOMATIC_FAILED"),
    ],
)
def test_status_records_real_terminal_evidence_without_inferring_absence(fields, status):
    source = monitor()
    source.observe_global(observation(**fields))
    assert source.snapshot()["status"] == status


def test_new_check_retires_prior_token_and_bounds_activity():
    source = monitor()
    source.observe_global(observation(final_url=TARGET))
    for _ in range(40):
        source.mark_checking()
    assert source.snapshot()["latest"] is None
    assert source.snapshot()["has_target_url"] is False
    assert source.owner_global_details(owner_authenticated=True) is None
    assert len(source.activity_events()) <= 32


def test_not_configured_and_non_observations_fail_closed():
    source = monitor(configured=False)
    with pytest.raises(RuntimeError):
        source.mark_checking()
    with pytest.raises(RuntimeError):
        source.observe_global(observation())
    source = monitor()
    with pytest.raises(TypeError):
        source.observe_global({"target_url": TARGET})
    assert source.snapshot()["latest"] is None


def test_future_or_older_observation_cannot_replace_current_result():
    source = monitor()
    source.observe_global(observation(final_url=TARGET))
    for instant in (NOW - timedelta(seconds=1), NOW + timedelta(minutes=1)):
        with pytest.raises(ValueError):
            source.observe_global(observation(observed_at=instant))
    assert source.owner_global_details(owner_authenticated=True).target_url == TARGET
