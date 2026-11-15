"""Private same-session login contracts, with no provider traffic."""

from __future__ import annotations

import asyncio
import json

import pytest

from boca_socios.browser.boca_auth_protocol import (
    BocaAuthReadiness,
    BocaAuthReply,
    BocaAuthRequest,
)
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from test_automatic_observer import observer_for, snapshot

OPERATION = "11111111-1111-4111-8111-111111111111"
PORTAL = "https://bocasocios.bocajuniors.com.ar/"
TARGET = PORTAL + "?queueittoken=received-private-pass"


def auth_observer(values):
    observer, page, context, browser, engine, launches = observer_for(values)
    observer._destination = PORTAL
    original = page.evaluate

    async def evaluate(script):
        if "boca_login_ready" in script:
            return (
                [
                    {
                        "emails": 1,
                        "passwords": 1,
                        "login_buttons": 1,
                        "ambiguous": False,
                        "new_password": False,
                    }
                ]
                if getattr(page, "login_ready", True)
                else []
            )
        return await original(script)

    async def cookies(url):
        assert url == "https://bocasocios-gw.bocajuniors.com.ar/auth/login/baas"
        context.cookies_read += 1
        return [
            {
                "name": "session",
                "value": "private-cookie",
                "domain": ".bocajuniors.com.ar",
                "path": "/",
                "secure": True,
                "expires": -1,
            }
        ]

    page.evaluate = evaluate
    context.cookies = cookies
    calls = []

    async def login(request, cookies, *, deadline):
        calls.append((request, cookies))
        return b'{"token":"received","refreshToken":"received-refresh"}'

    observer._login_runner = login
    return observer, page, context, browser, calls


def test_login_uses_single_existing_context_and_consumes_nonce():
    async def exercise():
        observer, page, context, browser, calls = auth_observer([snapshot()])
        ready = await observer.prepare_boca_login(OPERATION)
        assert ready.ready and ready.operation_id == OPERATION
        assert 0 < ready.remaining_seconds <= 15 and len(ready.nonce) == 64
        assert not context.closed and context.cookies_read == 0
        request = BocaAuthRequest(OPERATION, ready.nonce, "fixture@example.invalid", "fixture")
        reply = await observer.login_boca(request)
        assert reply.operation_id == OPERATION and reply.nonce == ready.nonce
        assert len(calls) == context.cookies_read == context.pages == len(page.navigations) == 1
        assert calls[0][1][0].expires_at is None
        assert context.closed and browser.closed
        with pytest.raises(SyntheticIPCError):
            await observer.login_boca(request)

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["challenge", "queue", "unknown", "wrong_origin"])
def test_unready_pages_never_disclose_cookies_or_start_login(kind):
    async def exercise():
        value = (
            snapshot(markers=["captcha"])
            if kind == "challenge"
            else (snapshot(model={"ticket": {"progress": 0}}) if kind == "queue" else snapshot())
        )
        observer, page, context, _, calls = auth_observer([value])
        if kind == "unknown":
            page.login_ready = False
        if kind == "wrong_origin":
            observer._destination = "https://wrong.example.invalid/"
        ready = await observer.prepare_boca_login(OPERATION)
        assert not ready.ready and ready.nonce is None and ready.remaining_seconds == 0
        assert calls == [] and context.cookies_read == 0
        await observer.close()

    asyncio.run(exercise())


def test_protocol_strictness_and_redaction():
    request = BocaAuthRequest(OPERATION, "a" * 64, "fixture@example.invalid", "private-password")
    assert BocaAuthRequest.from_payload(request.to_payload()) == request
    assert "private-password" not in repr(request)
    payload = json.loads(request.to_payload())
    payload["extra"] = True
    with pytest.raises(SyntheticIPCError):
        BocaAuthRequest.from_payload(json.dumps(payload).encode())
    with pytest.raises(SyntheticIPCError):
        BocaAuthRequest.from_payload(b'{"operation_id":"x","operation_id":"y"}')
    reply = BocaAuthReply(OPERATION, "a" * 64, b"x" * 65536)
    assert BocaAuthReply.from_payload(reply.to_payload()) == reply
    with pytest.raises(SyntheticIPCError):
        BocaAuthReply(OPERATION, "a" * 64, b"x" * 65537)


def test_readiness_envelope_has_no_nonce_when_not_ready():
    from test_automatic_observer_ipc import observation

    ready = BocaAuthReadiness(OPERATION, observation(), None, 0)
    assert not ready.ready
    assert BocaAuthReadiness.from_payload(ready.to_payload()) == ready
    with pytest.raises(SyntheticIPCError):
        BocaAuthReadiness(OPERATION, observation(), "a" * 64, 0)


def test_queue_completion_follows_only_received_target_in_same_page():
    async def exercise():
        observer, page, context, _, calls = auth_observer(
            [
                snapshot(model={"eventId": "observed", "ticket": {"progress": 0}}),
                snapshot(model={"eventId": "observed", "targetUrl": TARGET}),
                snapshot(),
            ]
        )
        observer._destination = "https://bocajuniors.queue-it.net/received"
        waiting = await observer.prepare_boca_login(OPERATION)
        assert waiting.observation.outcome == "QUEUE_ACTIVE" and not waiting.ready
        ready = await observer.prepare_boca_login(OPERATION)
        assert ready.ready and ready.observation.target_url == TARGET
        repeated = await observer.prepare_boca_login(OPERATION)
        assert (
            repeated.nonce == ready.nonce and repeated.remaining_seconds <= ready.remaining_seconds
        )
        assert context.pages == 1 and len(page.navigations) == 2
        assert page.navigations[-1][0] == TARGET
        await observer.login_boca(
            BocaAuthRequest(OPERATION, ready.nonce, "fixture@example.invalid", "fixture")
        )
        assert len(calls) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "target",
    [
        "https://wrong.example.invalid/?queueittoken=received",
        "http://bocasocios.bocajuniors.com.ar/?queueittoken=received",
        "https://user@bocasocios.bocajuniors.com.ar/?queueittoken=received",
    ],
)
def test_untrusted_queue_targets_do_not_trigger_continuation(target):
    async def exercise():
        observer, page, context, _, calls = auth_observer([snapshot(model={"targetUrl": target})])
        observer._destination = "https://bocajuniors.queue-it.net/received"
        result = await observer.prepare_boca_login(OPERATION)
        assert not result.ready and len(page.navigations) == 1
        assert calls == [] and context.cookies_read == 0
        await observer.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "drift", ["operation", "nonce", "expiry", "url", "page", "context", "form"]
)
def test_readiness_cannot_authorize_changed_or_expired_session(drift):
    from time import monotonic

    async def exercise():
        observer, page, context, _, calls = auth_observer([snapshot()])
        ready = await observer.prepare_boca_login(OPERATION)
        operation, nonce = OPERATION, ready.nonce
        if drift == "operation":
            operation = "22222222-2222-4222-8222-222222222222"
        elif drift == "nonce":
            nonce = "b" * 64
        elif drift == "expiry":
            observer._auth_deadline = monotonic() - 1
        elif drift == "url":
            page.url = "https://wrong.example.invalid/"
        elif drift == "page":
            observer._auth_page = object()
        elif drift == "context":
            observer._auth_context = object()
        else:
            page.login_ready = False
        with pytest.raises(SyntheticIPCError):
            await observer.login_boca(
                BocaAuthRequest(operation, nonce, "fixture@example.invalid", "fixture")
            )
        assert calls == [] and context.cookies_read == 0
        await observer.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("stop", [True, False])
def test_stop_or_expiry_discards_even_cancellation_suppressing_http_result(stop):
    from time import monotonic

    async def exercise():
        observer, _, context, browser, _ = auth_observer([snapshot()])
        ready = await observer.prepare_boca_login(OPERATION)
        entered = asyncio.Event()

        async def late(*_args, **_kwargs):
            entered.set()
            if stop:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    pass
            else:
                observer._auth_deadline = monotonic() - 1
            return b"private-late-response"

        observer._login_runner = late
        running = asyncio.create_task(
            observer.login_boca(
                BocaAuthRequest(OPERATION, ready.nonce, "fixture@example.invalid", "fixture")
            )
        )
        await entered.wait()
        if stop:
            await observer.close()
        with pytest.raises(SyntheticIPCError):
            await running
        assert context.closed and browser.closed

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "change",
    [
        {"emails": 0},
        {"passwords": 0},
        {"passwords": 2},
        {"login_buttons": 0},
        {"login_buttons": 2},
        {"ambiguous": True},
        {"new_password": True},
        {"emails": True},
        {"extra": "untrusted"},
    ],
)
def test_visible_form_requires_both_enabled_fields_and_unambiguous_login(change):
    from boca_socios.browser.automatic_observer import _login_form_ready

    form = {
        "emails": 1,
        "passwords": 1,
        "login_buttons": 1,
        "ambiguous": False,
        "new_password": False,
    }
    assert _login_form_ready([form])
    assert not _login_form_ready([form, form])
    assert not _login_form_ready([{**form, **change}])
    # Fields observed in different forms cannot combine into readiness.
    assert not _login_form_ready([{**form, "emails": 0}, {**form, "passwords": 0}])


@pytest.mark.parametrize("phase", ["cookies", "response"])
def test_page_drift_during_private_await_never_yields_authentication(phase):
    async def exercise():
        observer, page, context, _, calls = auth_observer([snapshot()])
        ready = await observer.prepare_boca_login(OPERATION)
        if phase == "cookies":
            original = context.cookies

            async def cookies(url):
                result = await original(url)
                page.login_ready = False
                return result

            context.cookies = cookies
        else:
            original = observer._login_runner

            async def runner(*args, **kwargs):
                result = await original(*args, **kwargs)
                page.url = "https://bocajuniors.queue-it.net/received"
                return result

            observer._login_runner = runner
        with pytest.raises(SyntheticIPCError):
            await observer.login_boca(
                BocaAuthRequest(OPERATION, ready.nonce, "fixture@example.invalid", "fixture")
            )
        assert context.closed
        assert len(calls) == (0 if phase == "cookies" else 1)

    asyncio.run(exercise())
