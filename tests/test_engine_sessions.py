"""Scoped engine coordination with fake browser boundaries; no provider traffic."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply, BocaAuthRequest
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from test_automatic_observer import snapshot
from test_automatic_observer_ipc import observation


def modules():
    names = ["boca_socios.browser.engine_protocol", "boca_socios.browser.engine_sessions"]
    assert all(importlib.util.find_spec(name) is not None for name in names), (
        "scoped engine registry and strict protocol are missing"
    )
    return tuple(importlib.import_module(name) for name in names)


def identity(
    protocol, *, engine="queues_tokens", activation=None, generation=1, browser="chromium"
):
    return protocol.EngineIdentity(
        engine, activation or str(uuid4()), generation, str(uuid4()), browser
    )


class Observer:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.close_release = asyncio.Event()
        self.close_release.set()
        self.closed = False
        self.auth_calls = 0
        self.swallow = False

    async def observe_queue(self):
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            if not self.swallow:
                raise
        return observation()

    async def prepare_boca_login(self, operation):
        return BocaAuthReadiness(operation, observation(), "a" * 64, 15)

    async def login_boca(self, request):
        self.auth_calls += 1
        await self.release.wait()
        return BocaAuthReply(request.operation_id, request.nonce, b'{"token":"fixture"}')

    async def close(self):
        self.closed = True
        await self.close_release.wait()


def registry(sessions, observers, **options):
    def factory(ident):
        value = Observer()
        observers[ident.session_id] = value
        return value

    return sessions.EngineSessionRegistry(observer_factory=factory, **options)


def test_protocol_round_trip_preserves_identity_and_rejects_unknown_or_duplicate_fields():
    protocol, _ = modules()
    ident = identity(protocol, engine="browsers_members")
    auth = BocaAuthRequest(
        ident.activation_id, "a" * 64, "fixture@example.invalid", "secret-fixture"
    )
    request = protocol.EngineRequest(ident, "login", auth=auth)
    assert protocol.EngineRequest.from_payload(request.to_payload()) == request
    assert "secret-fixture" not in repr(request)
    body = json.loads(request.to_payload())
    body["extra"] = True
    with pytest.raises(SyntheticIPCError):
        protocol.EngineRequest.from_payload(json.dumps(body).encode())
    with pytest.raises(SyntheticIPCError):
        protocol.EngineRequest.from_payload(b'{"identity":{},"identity":{}}')
    for field, value in (("generation", True), ("browser", "chrome"), ("activation_id", "bad")):
        with pytest.raises(SyntheticIPCError):
            replace(ident, **{field: value})
    with pytest.raises(SyntheticIPCError):
        protocol.EngineRequest(replace(ident, engine="queues_tokens"), "login", auth=auth)
    with pytest.raises(SyntheticIPCError):
        protocol.EngineRequest(ident, "login", auth=replace(auth, operation_id=str(uuid4())))


def test_two_engines_poll_and_close_without_waiting_on_other_engine():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers, teardown_seconds=0.05)
        a = identity(protocol)
        b = identity(protocol, engine="browsers_members")
        assert (await reg.execute(protocol.EngineRequest(a, "observe"))).result == observation()
        observers[a.session_id].release.clear()
        observers[a.session_id].entered.clear()
        blocked = asyncio.create_task(reg.execute(protocol.EngineRequest(a, "observe")))
        await observers[a.session_id].entered.wait()
        assert (
            await asyncio.wait_for(reg.execute(protocol.EngineRequest(b, "observe")), 0.1)
        ).status == "OK"
        closed = await asyncio.wait_for(
            reg.execute(protocol.EngineRequest(b, "close", close_scope="activation")), 0.1
        )
        assert closed.status == "CLOSED" and not blocked.done()
        assert not observers[a.session_id].closed and observers[b.session_id].closed
        observers[a.session_id].release.set()
        assert (await blocked).status == "OK"
        await reg.close()

    asyncio.run(exercise())


def test_stop_fences_before_teardown_and_late_result_never_reopens_identity():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers, teardown_seconds=0.05)
        ident = identity(protocol)
        await reg.execute(protocol.EngineRequest(ident, "observe"))
        obs = observers[ident.session_id]
        obs.release.clear()
        obs.entered.clear()
        obs.swallow = True
        running = asyncio.create_task(reg.execute(protocol.EngineRequest(ident, "observe")))
        await obs.entered.wait()
        result = await reg.execute(protocol.EngineRequest(ident, "close", close_scope="activation"))
        assert result.status == "CLOSED"
        assert (await running).status == "NO_GO"
        assert (await reg.execute(protocol.EngineRequest(ident, "observe"))).status == "NO_GO"
        unseen = replace(ident, session_id=str(uuid4()))
        assert (await reg.execute(protocol.EngineRequest(unseen, "observe"))).status == "NO_GO"
        assert len(observers) == 1
        await reg.close()

    asyncio.run(exercise())


def test_generation_and_cross_engine_identity_are_fenced():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers)
        old = identity(protocol)
        await reg.execute(protocol.EngineRequest(old, "observe"))
        wrong = replace(old, engine="browsers_members")
        assert (await reg.execute(protocol.EngineRequest(wrong, "observe"))).status == "NO_GO"
        assert (
            await reg.execute(protocol.EngineRequest(replace(old, browser="firefox"), "observe"))
        ).status == "NO_GO"
        new = identity(protocol, generation=2)
        assert (await reg.execute(protocol.EngineRequest(new, "observe"))).status == "BUSY"
        await reg.execute(protocol.EngineRequest(old, "close", close_scope="activation"))
        assert (await reg.execute(protocol.EngineRequest(new, "observe"))).status == "OK"
        assert (await reg.execute(protocol.EngineRequest(old, "observe"))).status == "NO_GO"
        assert (
            await reg.execute(protocol.EngineRequest(old, "close", close_scope="activation"))
        ).status == "NO_GO"
        assert not observers[new.session_id].closed
        await reg.close()

    asyncio.run(exercise())


def test_cap_is_fifty_shared_contexts_and_uncertain_close_keeps_its_slot():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers, teardown_seconds=0.01)
        activations = {"queues_tokens": str(uuid4()), "browsers_members": str(uuid4())}
        identities = [
            identity(protocol, engine=engine, activation=activations[engine])
            for engine in activations
            for _ in range(25)
        ]
        for ident in identities:
            assert (await reg.execute(protocol.EngineRequest(ident, "observe"))).status == "OK"
        assert reg.live_contexts == 50
        extra = identity(protocol, activation=activations["queues_tokens"])
        assert (await reg.execute(protocol.EngineRequest(extra, "observe"))).status == "BUSY"
        first = identities[0]
        observers[first.session_id].close_release.clear()
        result = await reg.execute(protocol.EngineRequest(first, "close"))
        assert result.status == "TEARDOWN_UNVERIFIED" and reg.live_contexts == 50
        assert (await reg.execute(protocol.EngineRequest(extra, "observe"))).status != "OK"
        observers[first.session_id].close_release.set()
        with pytest.raises(SyntheticIPCError, match="engine_teardown_unverified"):
            await reg.close()

    asyncio.run(exercise())


def test_nonce_is_bound_to_session_and_single_use_before_login_await():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers)
        ident = identity(protocol, engine="browsers_members")
        second = replace(ident, session_id=str(uuid4()))
        ready = (await reg.execute(protocol.EngineRequest(ident, "prepare_login"))).result
        auth = BocaAuthRequest(
            ident.activation_id, ready.nonce, "fixture@example.invalid", "fixture"
        )
        assert (
            await reg.execute(protocol.EngineRequest(second, "login", auth=auth))
        ).status == "NO_GO"
        wrong = replace(auth, nonce="b" * 64)
        assert (
            await reg.execute(protocol.EngineRequest(ident, "login", auth=wrong))
        ).status == "NO_GO"
        assert observers[ident.session_id].auth_calls == 0
        assert (await reg.execute(protocol.EngineRequest(ident, "login", auth=auth))).status == "OK"
        assert (
            await reg.execute(protocol.EngineRequest(ident, "login", auth=auth))
        ).status == "NO_GO"
        assert observers[ident.session_id].auth_calls == 1
        await reg.close()

    asyncio.run(exercise())


def test_close_before_first_observe_tombstones_entire_activation():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers)
        ident = identity(protocol)
        assert (
            await reg.execute(protocol.EngineRequest(ident, "close", close_scope="activation"))
        ).status == "CLOSED"
        assert (
            await reg.execute(
                protocol.EngineRequest(replace(ident, session_id=str(uuid4())), "observe")
            )
        ).status == "NO_GO"
        assert observers == {}
        await reg.close()

    asyncio.run(exercise())


def test_retention_after_auth_keeps_same_page_and_inspection_without_claiming_dom_login():
    from test_boca_auth_continuation import OPERATION, auth_observer

    async def exercise():
        protocol, _ = modules()
        observer, page, context, browser, calls = auth_observer([snapshot()])
        observer._retain_after_auth = True
        ready = await observer.prepare_boca_login(OPERATION)
        await observer.login_boca(
            BocaAuthRequest(OPERATION, ready.nonce, "fixture@example.invalid", "fixture")
        )
        assert not context.closed and not browser.closed
        observed = await observer.observe_queue()
        assert observed.outcome == "UNKNOWN" and not context.closed
        before = len(page.evaluations)
        inspected = await observer.inspect()
        assert isinstance(inspected, protocol.SessionInspection)
        assert inspected.context_open and inspected.auth_response_received
        assert inspected.dom_authentication == "UNVERIFIED"
        assert len(page.evaluations) == before and len(page.navigations) == 1
        assert len(calls) == 1
        await observer.close()
        assert context.closed

    asyncio.run(exercise())


def test_timed_out_login_closes_only_its_session_and_rejects_replay():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers, operation_seconds=0.02, teardown_seconds=0.02)
        a = identity(protocol)
        b = identity(protocol, engine="browsers_members")
        await reg.execute(protocol.EngineRequest(a, "observe"))
        ready = (await reg.execute(protocol.EngineRequest(b, "prepare_login"))).result
        observers[b.session_id].release.clear()
        auth = BocaAuthRequest(b.activation_id, ready.nonce, "fixture@example.invalid", "fixture")
        running = asyncio.create_task(reg.execute(protocol.EngineRequest(b, "login", auth=auth)))
        await asyncio.sleep(0)
        assert (await reg.execute(protocol.EngineRequest(a, "observe"))).status == "OK"
        assert (await running).status == "NO_GO"
        assert observers[b.session_id].closed and not observers[a.session_id].closed
        assert (await reg.execute(protocol.EngineRequest(b, "login", auth=auth))).status == "NO_GO"
        assert reg.live_contexts == 1 and not reg.poisoned
        await reg.close()

    asyncio.run(exercise())


def test_cancel_suppressing_cleanup_is_bounded_poisoned_and_never_releases_capacity():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers, teardown_seconds=0.01)
        ident = identity(protocol)
        await reg.execute(protocol.EngineRequest(ident, "observe"))
        release = asyncio.Event()
        finished = asyncio.Event()

        async def stubborn_close():
            try:
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        continue
            finally:
                finished.set()

        observers[ident.session_id].close = stubborn_close
        result = await asyncio.wait_for(
            reg.execute(protocol.EngineRequest(ident, "close", close_scope="activation")), 0.1
        )
        assert result.status == "TEARDOWN_UNVERIFIED" and reg.poisoned and reg.live_contexts == 1
        assert (
            await reg.execute(
                protocol.EngineRequest(identity(protocol, engine="browsers_members"), "observe")
            )
        ).status == "TEARDOWN_UNVERIFIED"
        release.set()
        await finished.wait()
        with pytest.raises(SyntheticIPCError, match="engine_teardown_unverified"):
            await reg.close()

    asyncio.run(exercise())


def test_single_session_busy_gate_does_not_create_a_second_observer():
    async def exercise():
        protocol, sessions = modules()
        observers = {}
        reg = registry(sessions, observers)
        ident = identity(protocol)
        await reg.execute(protocol.EngineRequest(ident, "observe"))
        observer = observers[ident.session_id]
        observer.entered.clear()
        observer.release.clear()
        running = asyncio.create_task(reg.execute(protocol.EngineRequest(ident, "observe")))
        await observer.entered.wait()
        assert (await reg.execute(protocol.EngineRequest(ident, "observe"))).status == "BUSY"
        assert len(observers) == reg.live_contexts == 1
        observer.release.set()
        assert (await running).status == "OK"
        await reg.close()

    asyncio.run(exercise())


def navigation_value():
    return {
        "sequence": 2,
        "purpose": "QUEUE_BRIDGE",
        "display_url": "https://bocajuniors.queue-it.net/received",
        "started_at": "2026-11-15T12:00:00+03:00",
        "result": "RETURNED",
        "http_status": 503,
    }


def test_navigation_attempt_round_trip_and_legacy_inspection():
    from datetime import UTC, datetime

    protocol, _ = modules()
    assert hasattr(protocol, "NavigationAttempt"), "private navigation contract is missing"
    attempt = protocol.NavigationAttempt.from_value(navigation_value())
    assert attempt.started_at == datetime(2026, 11, 15, 9, tzinfo=UTC)
    assert attempt.to_value() == {**navigation_value(), "started_at": "2026-11-15T09:00:00+00:00"}
    inspected = protocol.SessionInspection(
        final_url="https://example.invalid/final?private=value#fragment",
        configured_url="https://example.invalid/configured",
        navigation_attempt=attempt,
    )
    payload = inspected.to_payload()
    assert protocol.SessionInspection.from_payload(payload) == inspected
    assert b'"configured_url"' in payload and b'"navigation_attempt"' in payload
    assert "example.invalid" not in repr(inspected) + repr(attempt)
    old = json.loads(payload)
    del old["configured_url"], old["navigation_attempt"]
    legacy = protocol.SessionInspection.from_payload(json.dumps(old).encode())
    assert legacy.final_url == inspected.final_url
    assert legacy.configured_url is legacy.navigation_attempt is None
    ident = identity(protocol)
    reply = protocol.EngineReply(ident, "inspect", "OK", inspected)
    assert protocol.EngineReply.from_payload(reply.to_payload()) == reply


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sequence", True),
        ("sequence", 1.0),
        ("sequence", 0),
        ("sequence", 4),
        ("purpose", "REDIRECT"),
        ("purpose", []),
        ("display_url", "https://user:private@example.invalid/"),
        ("display_url", "https://example.invalid/?bearer=private"),
        ("display_url", "https://example.invalid/#private"),
        ("display_url", "https://example.invalid/" + "x" * 490),
        ("display_url", "https://example.invalid/\n"),
        ("display_url", 1),
        ("started_at", "2026-11-15T12:00:00"),
        ("started_at", 1),
        ("result", "SUCCESS"),
        ("result", []),
        ("http_status", True),
        ("http_status", 200.0),
        ("http_status", 99),
        ("http_status", 600),
    ],
)
def test_navigation_attempt_rejects_invalid_shape_and_values(field, value):
    protocol, _ = modules()
    assert hasattr(protocol, "NavigationAttempt"), "private navigation contract is missing"
    with pytest.raises(SyntheticIPCError):
        protocol.NavigationAttempt.from_value({**navigation_value(), field: value})


def test_navigation_attempt_rejects_nonexact_inspection_and_nested_duplicates():
    protocol, _ = modules()
    assert hasattr(protocol, "NavigationAttempt"), "private navigation contract is missing"
    for bad in ([], None, {}, {**navigation_value(), "extra": None}):
        with pytest.raises(SyntheticIPCError):
            protocol.NavigationAttempt.from_value(bad)
    for result in ("STARTED", "FAILED", "CANCELLED"):
        with pytest.raises(SyntheticIPCError):
            protocol.NavigationAttempt.from_value({**navigation_value(), "result": result})
    body = json.loads(protocol.SessionInspection().to_payload())
    for field in ("configured_url", "navigation_attempt"):
        partial = {key: value for key, value in body.items() if key != field}
        with pytest.raises(SyntheticIPCError):
            protocol.SessionInspection.from_payload(json.dumps(partial).encode())
    for extra in (
        {"extra": None},
        {"configured_url": "https://a.invalid/?secret=x"},
        {"navigation_attempt": []},
        {"navigation_attempt": navigation_value() | {"extra": 1}},
    ):
        with pytest.raises(SyntheticIPCError):
            protocol.SessionInspection.from_payload(json.dumps(body | extra).encode())
    body["navigation_attempt"] = navigation_value()
    duplicate = json.dumps(body).replace('"sequence": 2', '"sequence": 2, "sequence": 2')
    with pytest.raises(SyntheticIPCError):
        protocol.SessionInspection.from_payload(duplicate.encode())
    with pytest.raises(SyntheticIPCError):
        protocol.SessionInspection.from_payload(b" " * 32769)


def test_inspection_maximum_encoded_payload_remains_bounded():
    from datetime import UTC, datetime

    protocol, _ = modules()
    assert hasattr(protocol, "NavigationAttempt"), "private navigation contract is missing"

    # U+0080 consumes two UTF-8 bytes but six ASCII JSON bytes; this is the
    # largest encoding ratio allowed by the preexisting text validators.
    def padded_url(size, *, query=False):
        prefix = "https://example.invalid/" + ("?" if query else "")
        rest = size - len(prefix)
        return prefix + "\x80" * (rest // 2) + "\\" * (rest % 2)

    attempt = protocol.NavigationAttempt.from_value(
        navigation_value() | {"display_url": padded_url(512)}
    )
    inspected = protocol.SessionInspection(
        final_url=padded_url(8192, query=True),
        queue_id="q" * 128,
        queue_number="\x80" * 128,
        users_ahead="\x80" * 128,
        users_in_queue="\x80" * 128,
        expected_service_time="\x80" * 128,
        observed_at=datetime(2026, 11, 15, tzinfo=UTC),
        context_open=True,
        auth_response_received=True,
        configured_url=padded_url(512),
        navigation_attempt=attempt,
    )
    payload = inspected.to_payload()
    assert 31000 < len(payload) <= 32768
    assert protocol.SessionInspection.from_payload(payload) == inspected
    ident = identity(protocol)
    request = protocol.EngineRequest(ident, "inspect")
    reply = protocol.EngineReply(ident, "inspect", "OK", inspected)
    assert len(request.to_payload()) <= 33792
    assert len(reply.to_payload()) <= 98304
    assert protocol.EngineReply.from_payload(reply.to_payload()) == reply
