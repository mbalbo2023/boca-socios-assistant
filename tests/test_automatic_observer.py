"""Automatic page capture with inert fakes; no browser, socket or destination is opened."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from boca_socios.browser.ipc_protocol import SyntheticIPCError

NOW = datetime(2026, 11, 14, 18, 0, tzinfo=UTC)
SITE = "https://queue.example.invalid/room"
TARGET = "https://tickets.example.invalid/event?queueittoken=received-private-value"


def module():
    name = "boca_socios.browser.automatic_observer"
    assert importlib.util.find_spec(name) is not None, "automatic capture adapter is missing"
    return importlib.import_module(name)


class Page:
    def __init__(self, snapshots):
        self.url = "about:blank"
        self.main_frame = SimpleNamespace(url=self.url)
        self.snapshots = iter(snapshots)
        self.latest = None
        self.navigations = []
        self.evaluations = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.swallow_cancel = False

    async def goto(self, url, **kwargs):
        self.navigations.append((url, kwargs))
        self.url = url
        self.main_frame.url = url
        return SimpleNamespace(status=200)

    async def evaluate(self, script):
        self.evaluations.append(script)
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            if not self.swallow_cancel:
                raise
        self.latest = next(self.snapshots, self.latest)
        return self.latest


class Context:
    def __init__(self, page):
        self.page = page
        self.pages = 0
        self.routes = []
        self.websocket_routes = []
        self.cookies_read = 0
        self.closed = False

    async def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    async def route_web_socket(self, pattern, handler):
        self.websocket_routes.append((pattern, handler))

    async def new_page(self):
        assert self.routes and self.websocket_routes, "guards must precede the first page"
        self.pages += 1
        return self.page

    async def cookies(self):
        self.cookies_read += 1
        pytest.fail("automatic observation must not collect browser cookies")

    async def close(self):
        self.closed = True


class Browser:
    def __init__(self, context):
        self.context = context
        self.contexts = []
        self.closed = False

    async def new_context(self, **kwargs):
        self.contexts.append(kwargs)
        return self.context

    async def close(self):
        self.closed = True


class Engine:
    def __init__(self):
        self.browser = None
        self.calls = []

    async def run_isolated_task(self, worker_id, target_url):
        self.calls.append((worker_id, target_url))
        print(target_url)
        print("legacy-cookie-private-value", file=sys.stderr)
        context = await self.browser.new_context(
            user_agent="legacy-spoof", viewport={"width": 1920}
        )
        try:
            page = await context.new_page()
            await page.goto(target_url, wait_until="networkidle")
            await context.cookies()
            return {"worker_id": worker_id, "status": "success", "token": "not-observed-access"}
        finally:
            await context.close()


def snapshot(*, model=None, markers=(), text="", links=()):
    return {
        "queue_model": model,
        "markers": list(markers),
        "visible_text": text,
        "queue_links": list(links),
    }


def observer_for(snapshots, **kwargs):
    kwargs.setdefault("settle_seconds", 0.01)
    page = Page(snapshots)
    context = Context(page)
    browser = Browser(context)
    engine = Engine()
    launches = []

    @asynccontextmanager
    async def factory():
        launches.append("launched")
        try:
            yield browser
        finally:
            await browser.close()

    observer = module().AutomaticQueueObserver(
        SITE,
        browsers=factory,
        engine_factory=lambda: engine,
        boundary_check=lambda: None,
        now=lambda: NOW,
        **kwargs,
    )
    return observer, page, context, browser, engine, launches


@pytest.mark.parametrize("already_cut", [False, True])
def test_partial_truncated_line_never_becomes_explicit_absence(already_cut):
    async def exercise():
        phrase = "No hay eventos disponibles"
        prefix = "x" * (16384 - len(phrase) - 1) + "\n"
        complete = prefix + phrase + " mientras se actualiza la página"
        received = snapshot(text=complete[:16384] if already_cut else complete)
        if already_cut:
            received["visible_text_truncated"] = True
        observer, _, _, _, _, _ = observer_for([received])
        result = await observer.observe_queue()
        assert result.outcome == "UNKNOWN"
        assert result.event_state == "UNRECOGNIZED"

    asyncio.run(exercise())


def test_slow_page_initialization_is_rechecked_without_a_second_navigation():
    async def exercise():
        observer, page, context, _, engine, _ = observer_for(
            [
                snapshot(text="Cargando eventos"),
                snapshot(model={"eventId": "received-event", "ticket": {"progress": 0}}),
            ]
        )
        result = await observer.observe_queue()
        assert result.outcome == "QUEUE_ACTIVE"
        assert len(page.evaluations) == 2
        assert len(page.navigations) == context.pages == len(engine.calls) == 1
        assert not context.closed
        await observer.close()

    asyncio.run(exercise())


def test_one_legacy_navigation_and_one_live_context_across_active_polls(capsys):
    async def exercise():
        observer, page, context, browser, engine, launches = observer_for(
            [
                snapshot(model={"eventId": "actual-event", "isBeforeOrIdle": True}),
                snapshot(model={"eventId": "actual-event", "ticket": {"progress": 0.1}}),
                snapshot(model={"eventId": "actual-event", "targetUrl": TARGET}),
            ]
        )
        assert launches == [] and engine.calls == []
        first = await observer.observe_queue()
        assert first.outcome == "PREQUEUE"
        assert not context.closed and not browser.closed
        assert (await observer.observe_queue()).outcome == "QUEUE_ACTIVE"
        result = await observer.observe_queue()
        assert result.outcome == "TARGET_OBSERVED" and result.target_url == TARGET
        assert launches == ["launched"] and engine.calls == [(0, SITE)]
        assert len(page.navigations) == len(browser.contexts) == context.pages == 1
        assert page.navigations[0][1] == {"wait_until": "domcontentloaded", "timeout": 12000}
        assert "user_agent" not in browser.contexts[0]
        assert browser.contexts[0]["service_workers"] == "block"
        assert browser.contexts[0]["accept_downloads"] is False
        assert context.cookies_read == 0
        assert context.closed and browser.closed
        with pytest.raises(SyntheticIPCError, match="^automatic_observer_stopped$"):
            await observer.observe_queue()
        await observer.close()

    asyncio.run(exercise())
    output = capsys.readouterr()
    assert SITE not in output.out + output.err
    assert "legacy-cookie-private-value" not in output.out + output.err
    assert TARGET not in output.out + output.err


@pytest.mark.parametrize(
    ("received", "outcome"),
    [
        (snapshot(text="No hay eventos disponibles"), "NO_EVENT_OBSERVED"),
        (snapshot(model={"eventId": "received-event", "isIdle": True}), "QUEUE_INACTIVE"),
        (snapshot(markers=("challenge",)), "CHALLENGE"),
        (snapshot(text="Bienvenido"), "UNKNOWN"),
    ],
)
def test_terminal_evidence_closes_resources_without_promoting_legacy_success(received, outcome):
    async def exercise():
        observer, _, context, browser, _, _ = observer_for([received])
        result = await observer.observe_queue()
        assert result.outcome == outcome and result.target_url is None
        assert context.closed and browser.closed

    asyncio.run(exercise())


def test_stop_closes_active_page_and_discards_a_swallowed_cancellation():
    async def exercise():
        observer, page, context, browser, _, _ = observer_for(
            [snapshot(model={"targetUrl": TARGET})]
        )
        page.release.clear()
        page.swallow_cancel = True
        active = asyncio.create_task(observer.observe_queue())
        await asyncio.wait_for(page.entered.wait(), 1)
        await asyncio.wait_for(observer.close(), 1)
        with pytest.raises((SyntheticIPCError, asyncio.CancelledError)):
            await active
        assert context.closed and browser.closed

    asyncio.run(exercise())


def test_timeout_is_failed_check_and_leaves_no_live_context():
    async def exercise():
        observer, page, context, browser, _, _ = observer_for([snapshot()], timeout_seconds=0.01)
        page.release.clear()
        result = await observer.observe_queue()
        assert result.outcome == "CHECK_FAILED"
        assert result.target_url is None and context.closed and browser.closed

    asyncio.run(exercise())


def test_private_browser_exception_is_not_returned_or_logged(capsys):
    async def exercise():
        observer, page, context, browser, _, _ = observer_for([snapshot()])

        async def broken(_script):
            raise ValueError(TARGET)

        page.evaluate = broken
        result = await observer.observe_queue()
        assert result.outcome == "CHECK_FAILED"
        assert TARGET not in repr(result)
        assert context.closed and browser.closed

    asyncio.run(exercise())
    output = capsys.readouterr()
    assert TARGET not in output.out + output.err


def test_one_received_visible_boca_queue_link_is_followed_without_rewriting_it():
    async def exercise():
        link = "https://bocajuniors.queue-it.net/?c=bocajuniors&e=actually-received"
        observer, page, context, _, engine, _ = observer_for(
            [
                snapshot(links=(link,)),
                snapshot(model={"eventId": "actually-received", "ticket": {"progress": 0}}),
                snapshot(model={"eventId": "actually-received", "targetUrl": TARGET}),
            ]
        )
        assert (await observer.observe_queue()).outcome == "QUEUE_ACTIVE"
        assert [url for url, _options in page.navigations] == [SITE, link]
        assert context.pages == 1 and len(engine.calls) == 1
        assert (await observer.observe_queue()).target_url == TARGET
        assert len(page.navigations) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "links",
    [
        (),
        ("https://other-client.queue-it.net/?e=not-boca",),
        ("https://bocajuniors.queue-it.net/?e=one", "https://bocajuniors.queue-it.net/?e=two"),
        ("https://bocajuniors.queue-it.net.evil.invalid/?e=not-boca",),
        ("http://bocajuniors.queue-it.net/?e=downgrade",),
    ],
)
def test_bridge_never_selects_among_events_or_uses_other_provider_clients(links):
    async def exercise():
        observer, page, context, _, _, _ = observer_for([snapshot(links=links)])
        result = await observer.observe_queue()
        assert result.outcome == "UNKNOWN" and result.target_url is None
        assert [url for url, _options in page.navigations] == [SITE]
        assert context.closed

    asyncio.run(exercise())


def test_visible_queue_link_contradicts_generic_no_event_line():
    async def exercise():
        observer, page, _, _, _, _ = observer_for(
            [
                snapshot(
                    text="No hay eventos disponibles",
                    links=("https://bocajuniors.queue-it.net/?e=received",),
                ),
            ]
        )
        result = await observer.observe_queue()
        assert result.outcome == "UNKNOWN" and result.reason == "CONTRADICTORY_EVIDENCE"
        assert len(page.navigations) == 1

    asyncio.run(exercise())


def test_blocked_status_write_is_failed_check_instead_of_false_absence():
    async def exercise():
        observer, page, context, _, _, _ = observer_for(
            [
                snapshot(text="No hay eventos disponibles"),
            ]
        )
        evaluate = page.evaluate

        class Write:
            request = SimpleNamespace(url=SITE, method="POST")

            async def abort(self):
                return

            async def continue_(self):
                pytest.fail("page writes must not leave this adapter")

        async def received(script):
            await context.routes[0][1](Write())
            return await evaluate(script)

        page.evaluate = received
        result = await observer.observe_queue()
        assert result.outcome == "CHECK_FAILED" and result.event_state == "UNRECOGNIZED"

    asyncio.run(exercise())


@pytest.mark.parametrize("websocket", [False, True])
@pytest.mark.parametrize("target", [False, True])
def test_blocked_unrelated_telemetry_does_not_discard_queue_evidence(websocket, target):
    async def exercise():
        observer, page, context, _, _, _ = observer_for(
            [snapshot(model={"targetUrl": TARGET} if target else {"ticket": {"progress": 0}})]
        )
        evaluate = page.evaluate

        class Telemetry:
            url = "wss://analytics.example.invalid/stream"
            request = SimpleNamespace(
                url="https://analytics.example.invalid/collect", method="POST"
            )
            blocked = False

            async def abort(self):
                self.blocked = True

            async def close(self):
                self.blocked = True

            async def continue_(self):
                pytest.fail("unrelated telemetry must remain blocked")

        telemetry = Telemetry()

        async def received(script):
            routes = context.websocket_routes if websocket else context.routes
            await routes[0][1](telemetry)
            return await evaluate(script)

        page.evaluate = received
        result = await observer.observe_queue()
        assert telemetry.blocked
        assert result.outcome == ("TARGET_OBSERVED" if target else "QUEUE_ACTIVE")
        assert result.target_url == (TARGET if target else None)
        await observer.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("request_url", "page_url", "resource_type", "navigation", "allowed"),
    [
        (
            "https://bocajuniors.queue-it.net/received-status",
            "https://bocajuniors.queue-it.net/",
            "xhr",
            False,
            True,
        ),
        (
            "https://bocajuniors.queue-it.net/received-status",
            "https://bocajuniors.queue-it.net/",
            "fetch",
            False,
            True,
        ),
        ("https://bocajuniors.queue-it.net/received-status", SITE, "xhr", False, False),
        (
            "https://bocajuniors.queue-it.net/received-status",
            "https://bocajuniors.queue-it.net/",
            "document",
            True,
            False,
        ),
        (
            "https://bocajuniors.queue-it.net.evil.invalid/received-status",
            "https://bocajuniors.queue-it.net/",
            "xhr",
            False,
            False,
        ),
        (
            "https://bocasocios.bocajuniors.com.ar/received-action",
            "https://bocasocios.bocajuniors.com.ar/",
            "xhr",
            False,
            False,
        ),
    ],
)
def test_only_same_queue_page_can_send_its_ordinary_status_request(
    request_url, page_url, resource_type, navigation, allowed
):
    main_frame = SimpleNamespace(url=page_url)

    class Route:
        request = SimpleNamespace(
            url=request_url,
            method="POST",
            resource_type=resource_type,
            is_navigation_request=lambda: navigation,
            frame=main_frame,
        )
        continued = False

        async def continue_(self):
            self.continued = True

        async def abort(self):
            return

    async def exercise():
        route = Route()
        await module().readonly_request_guard(route, page_url=page_url, main_frame=main_frame)
        assert route.continued is allowed

    asyncio.run(exercise())


@pytest.mark.parametrize("frame_kind", ["main", "foreign", "child", "missing", "throws"])
def test_queue_write_requires_the_owned_main_frame(frame_kind):
    queue_url = "https://bocajuniors.queue-it.net/"
    page = Page([])
    page.url = queue_url
    page.main_frame = SimpleNamespace(url=queue_url)
    facade = module()._BrowserFacade(Browser(Context(page)), queue_url)
    facade.page = page

    class Request:
        url = queue_url + "received-status"
        method = "POST"
        resource_type = "fetch"

        def is_navigation_request(self):
            return False

        @property
        def frame(self):
            if frame_kind == "throws":
                raise RuntimeError("frame unavailable")
            if frame_kind == "main":
                return page.main_frame
            if frame_kind == "missing":
                return None
            return SimpleNamespace(
                url=queue_url if frame_kind == "child" else "https://analytics.example.invalid/"
            )

    class Route:
        request = Request()
        allowed = False

        async def continue_(self):
            self.allowed = True

        async def abort(self):
            return

    async def exercise():
        route = Route()
        await facade._guard(route)
        assert route.allowed is (frame_kind == "main")

    asyncio.run(exercise())


def test_teardown_failure_is_fixed_error_and_permanently_blocks_new_navigation():
    async def exercise():
        observer, _, context, _, engine, _ = observer_for([snapshot(model={"targetUrl": TARGET})])

        async def broken():
            raise ValueError(TARGET)

        context.close = broken
        with pytest.raises(SyntheticIPCError, match="^automatic_observer_teardown_unverified$"):
            await observer.observe_queue()
        with pytest.raises(SyntheticIPCError, match="^automatic_observer_stopped$"):
            await observer.observe_queue()
        assert len(engine.calls) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("url", "method", "allowed"),
    [
        (SITE, "GET", True),
        (TARGET, "GET", True),
        (SITE, "POST", False),
        (SITE, "PUT", False),
        ("file:///tmp/private", "GET", False),
        ("http://169.254.169.254/latest", "GET", False),
        ("https://user:secret@example.invalid/", "GET", False),
    ],
)
def test_automatic_guard_allows_received_get_paths_and_blocks_writes(url, method, allowed):
    class Route:
        def __init__(self):
            self.request = SimpleNamespace(url=url, method=method)
            self.allowed = False
            self.aborted = False

        async def continue_(self):
            self.allowed = True

        async def abort(self):
            self.aborted = True

    async def exercise():
        route = Route()
        await module().readonly_request_guard(route)
        assert route.allowed is allowed and route.aborted is not allowed

    asyncio.run(exercise())


def test_ordinary_factory_keeps_sandbox_without_legacy_stealth_flags():
    async def exercise():
        browser = Browser(Context(Page([])))
        launches = []

        class Chromium:
            async def launch(self, **kwargs):
                launches.append(kwargs)
                return browser

        @asynccontextmanager
        async def api():
            yield SimpleNamespace(chromium=Chromium())

        async with module().isolated_automatic_browser(
            playwright_factory=api, boundary_check=lambda: None
        ):
            assert not browser.closed
        assert browser.closed
        assert launches == [
            {
                "headless": True,
                "chromium_sandbox": True,
                "timeout": 12000,
                "args": ["--disable-background-networking"],
            }
        ]

    asyncio.run(exercise())
