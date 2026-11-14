"""Received-page classification is pure and never manufactures queue access."""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import json
import socket
from datetime import UTC, datetime

import pytest

NOW = datetime(2026, 11, 14, 18, 0, tzinfo=UTC)
PAGE = "https://queue.example.invalid/room"
TARGET = "https://tickets.example.invalid/event?e=observed&queueittoken=received%2Fopaque%3D"


def _module():
    name = "boca_socios.browser.queue_page_observation"
    assert importlib.util.find_spec(name) is not None, "received-page classification is missing"
    return importlib.import_module(name)


def _parse(**changes):
    arguments = {
        "final_url": PAGE,
        "queue_model": None,
        "markers": frozenset(),
        "visible_text": "",
        "http_status": 200,
        "observed_at": NOW,
    }
    arguments.update(changes)
    return _module().parse_queue_page_observation(**arguments)


def test_http_success_without_queue_model_never_proves_absence_of_events() -> None:
    result = _parse(visible_text="Bienvenido al sitio")
    assert result.outcome == "UNKNOWN"
    assert result.event_state == "UNRECOGNIZED"
    assert result.queue_state == "UNKNOWN"
    assert result.event_id is None and result.target_url is None


@pytest.mark.parametrize(
    ("model", "markers", "outcome", "event_state", "queue_state"),
    [
        ({"eventId": "observed-event"}, frozenset(), "UNKNOWN", "EVENT_VERIFIED", "UNKNOWN"),
        (
            {"eventId": "observed-event", "isIdle": True},
            frozenset(),
            "QUEUE_INACTIVE",
            "EVENT_VERIFIED",
            "QUEUE_INACTIVE",
        ),
        (
            {"eventId": "observed-event", "isBeforeOrIdle": True},
            frozenset(),
            "PREQUEUE",
            "EVENT_ANNOUNCED",
            "PREQUEUE",
        ),
        (
            {"eventId": "observed-event", "isBeforeOrIdle": True, "isIdle": True},
            frozenset(),
            "QUEUE_INACTIVE",
            "EVENT_VERIFIED",
            "QUEUE_INACTIVE",
        ),
        (
            {"eventId": "observed-event", "ticket": {"queuePaused": False, "progress": 0}},
            frozenset(),
            "QUEUE_ACTIVE",
            "EVENT_VERIFIED",
            "QUEUE_ACTIVE",
        ),
        (None, frozenset({"queuenumber"}), "QUEUE_ACTIVE", "UNRECOGNIZED", "QUEUE_ACTIVE"),
        (None, frozenset({"prequeue"}), "PREQUEUE", "EVENT_ANNOUNCED", "PREQUEUE"),
        ({"queueState": 20}, frozenset(), "UNKNOWN", "UNRECOGNIZED", "UNKNOWN"),
        ({"ticket": {}}, frozenset(), "UNKNOWN", "UNRECOGNIZED", "UNKNOWN"),
    ],
)
def test_event_and_queue_evidence_remain_independent(
    model, markers, outcome, event_state, queue_state
) -> None:
    result = _parse(queue_model=model, markers=markers)
    assert result.outcome == outcome
    assert result.event_state == event_state
    assert result.queue_state == queue_state
    assert result.target_url is None
    if model and "eventId" in model:
        assert result.event_id == "observed-event"


@pytest.mark.parametrize("text", ["No hay eventos disponibles", "No hay partidos disponibles"])
def test_only_explicit_visible_absence_can_confirm_no_event(text: str) -> None:
    result = _parse(visible_text="Inicio\n" + text + "\nAyuda")
    assert result.outcome == "NO_EVENT_OBSERVED"
    assert result.event_state == "NO_EVENT_CONFIRMED"
    assert result.queue_state == "UNKNOWN"
    assert result.event_id is None


@pytest.mark.parametrize(
    "text",
    [
        "No se pudo cargar el listado de eventos",
        "Si aparece No hay eventos disponibles, vuelva después",
        "No hay eventos disponibles mientras se actualiza la página",
        "",
    ],
)
def test_partial_or_failed_page_text_does_not_confirm_absence(text: str) -> None:
    assert _parse(visible_text=text).outcome == "UNKNOWN"


@pytest.mark.parametrize(
    "changes",
    [
        {"queue_model": {"eventId": "observed-event"}},
        {"queue_model": {"isIdle": True}},
        {"markers": frozenset({"queueid"})},
        {"markers": frozenset({"prequeue"})},
        {"final_url": TARGET},
    ],
)
def test_contradictory_presence_blocks_no_event_confirmation(changes) -> None:
    result = _parse(visible_text="No hay eventos disponibles", **changes)
    assert result.outcome == "UNKNOWN"
    assert result.event_state == "UNRECOGNIZED"
    assert result.target_url is None


@pytest.mark.parametrize("marker", ["captcha", "challenge"])
def test_intervention_dominates_targets_absence_and_http_failure(marker: str) -> None:
    result = _parse(
        final_url=TARGET,
        queue_model={"eventId": "observed-event", "isIdle": True},
        visible_text="No hay partidos disponibles",
        markers=frozenset({marker}),
        http_status=503,
        check_failed=True,
    )
    assert result.outcome == "CHALLENGE"
    assert result.event_state == "UNRECOGNIZED"
    assert result.queue_state == "UNKNOWN"
    assert result.target_url is None


@pytest.mark.parametrize(
    "changes", [{"check_failed": True}, {"http_status": 403}, {"http_status": 500}]
)
def test_failed_check_cannot_promote_partial_dom_to_success(changes) -> None:
    result = _parse(
        visible_text="No hay eventos disponibles", markers=frozenset({"queueid"}), **changes
    )
    assert result.outcome == "CHECK_FAILED"
    assert result.event_state == "UNRECOGNIZED"
    assert result.target_url is None


@pytest.mark.parametrize("source", ["final", "target"])
def test_received_complete_token_url_is_preserved_without_inventing_identity(source: str) -> None:
    result = (
        _parse(final_url=TARGET)
        if source == "final"
        else _parse(queue_model={"targetUrl": TARGET, "eventId": "observed-event"})
    )
    assert result.outcome == "TARGET_OBSERVED"
    assert result.queue_state == "ACCESS_OBSERVED"
    assert result.target_url == TARGET
    assert result.event_id == (None if source == "final" else "observed-event")
    assert TARGET not in repr(result) and "received%2Fopaque" not in repr(result)
    assert "member_id" not in result.to_payload().decode()
    assert "session_id" not in result.to_payload().decode()


@pytest.mark.parametrize(
    "url",
    [
        "https://tickets.example.invalid/?queueId=not-a-token",
        "https://tickets.example.invalid/#queueittoken=not-a-query",
        "https://tickets.example.invalid/?queueittoken=",
        "https://tickets.example.invalid/?queueittoken=one&queueittoken=two",
        "https://user:secret@tickets.example.invalid/?queueittoken=private",
        "https://169.254.169.254/?queueittoken=private",
        "javascript:alert('private')",
    ],
)
def test_unusable_or_non_token_urls_never_become_observed_access(url: str) -> None:
    result = _parse(final_url=url)
    assert result.outcome == "UNKNOWN"
    assert result.target_url is None
    assert "private" not in repr(result)


def test_idle_page_with_received_target_without_token_is_only_inactive() -> None:
    result = _parse(queue_model={"targetUrl": "https://tickets.example.invalid/", "isIdle": True})
    assert result.outcome == "QUEUE_INACTIVE"
    assert result.event_state == "UNRECOGNIZED"
    assert result.target_url is None


def test_different_received_token_targets_are_ambiguous_instead_of_chosen() -> None:
    result = _parse(final_url=TARGET, queue_model={"targetUrl": TARGET + "different"})
    assert result.outcome == "UNKNOWN"
    assert result.target_url is None


@pytest.mark.parametrize(
    "changes",
    [
        {"queue_model": {"isIdle": "true"}},
        {"queue_model": {"eventId": "https://private.invalid/token"}},
        {"queue_model": {"ticket": {"progress": float("nan")}}},
        {"queue_model": {"ticket": {"progress": 10**1000}}},
        {"queue_model": {"ticket": {"progress": True}}},
        {"queue_model": {"unknown": "private-value"}},
        {"http_status": True},
        {"visible_text": "x" * 16385},
        {"final_url": "x" * 8193},
        {"markers": frozenset({"unreviewed-marker"})},
    ],
)
def test_malformed_or_unbounded_observations_fail_closed_without_echo(changes) -> None:
    result = _parse(**changes)
    assert result.outcome == "UNKNOWN"
    assert result.target_url is None
    assert "private-value" not in repr(result)


def test_private_payload_round_trip_contains_only_allowlisted_projection() -> None:
    result = _parse(queue_model={"eventId": "observed-event", "targetUrl": TARGET})
    payload = result.to_payload()
    assert len(payload) <= 32768
    assert set(json.loads(payload)) == {
        "version",
        "outcome",
        "event_state",
        "queue_state",
        "reason",
        "observed_at",
        "event_id",
        "target_url",
    }
    assert _module().QueuePageObservation.from_payload(payload) == result
    assert "queue_model" not in payload.decode() and "visible_text" not in payload.decode()
    assert TARGET not in json.dumps(result.metadata())


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"extra": "private-value"},
        {"outcome": "ADMITTED"},
        {"queue_state": "QUEUE_ACTIVE"},
        {"observed_at": "2026-11-14T18:00:00"},
        {"target_url": "https://tickets.example.invalid/?queueId=not-a-token"},
        {"event_state": "NO_EVENT_CONFIRMED"},
    ],
)
def test_private_payload_rejects_unknown_fields_inconsistent_states_and_bad_values(changes) -> None:
    document = json.loads(_parse(final_url=TARGET).to_payload())
    document.update(changes)
    with pytest.raises(ValueError) as caught:
        _module().QueuePageObservation.from_payload(json.dumps(document).encode())
    assert "private-value" not in str(caught.value)
    assert TARGET not in str(caught.value)


def test_private_payload_rejects_duplicates_and_oversize() -> None:
    parser = _module().QueuePageObservation.from_payload
    payload = _parse().to_payload().replace(b'"version":1', b'"version":0,"version":1')
    with pytest.raises(ValueError):
        parser(payload)
    with pytest.raises(ValueError):
        parser(b"x" * 32769)


def test_conflicting_idle_and_visible_queue_require_another_observation() -> None:
    result = _parse(queue_model={"isIdle": True}, markers=frozenset({"queuenumber"}))
    assert result.outcome == "UNKNOWN"
    assert result.reason == "CONTRADICTORY_EVIDENCE"
    assert result.target_url is None


def test_observation_clock_is_aware_and_normalized_without_assuming_local_time() -> None:
    result = _parse(observed_at=datetime.fromisoformat("2026-11-14T15:00:00-03:00"))
    assert result.observed_at == NOW
    assert result.observed_at.tzinfo is UTC
    with pytest.raises(ValueError):
        _parse(observed_at=NOW.replace(tzinfo=None))


def test_classifier_uses_no_network_or_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = _module().parse_queue_page_observation

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the observation classifier must be pure")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    result = parser(final_url=TARGET, queue_model=None, markers=frozenset(), observed_at=NOW)
    assert result.outcome == "TARGET_OBSERVED"
