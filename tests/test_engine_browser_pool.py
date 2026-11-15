"""Real observer/registry coordination, fake Playwright and opaque engine boundary."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boca_socios.browser.ipc_protocol import SyntheticIPCError
from test_automatic_observer import SITE, Context, Engine, Page, snapshot
from test_engine_sessions import identity, modules


class Browser:
    def __init__(self):
        self.contexts = []
        self.closed = False

    async def new_context(self, **_options):
        page = Page(
            [
                snapshot(
                    model={
                        "eventId": "fixture-event",
                        "queueId": "fixture-queue",
                        "ticket": {
                            "progress": 0,
                            "queueNumber": 21,
                            "usersInLineAheadOfYou": 20,
                            "usersInQueue": 50,
                            "expectedServiceTime": "12:30",
                        },
                    }
                )
            ]
        )
        context = Context(page)
        self.contexts.append(context)
        return context

    async def close(self):
        self.closed = True


def playwright():
    browsers = {}
    launches = []
    exited = []

    class Type:
        def __init__(self, kind):
            self.kind = kind

        async def launch(self, **options):
            launches.append((self.kind, options))
            assert self.kind not in browsers, "one process per browser type"
            browsers[self.kind] = Browser()
            return browsers[self.kind]

    @asynccontextmanager
    async def factory():
        try:
            yield SimpleNamespace(
                **{kind: Type(kind) for kind in ("chromium", "firefox", "webkit")}
            )
        finally:
            exited.append(True)

    return factory, browsers, launches, exited


def test_fifty_isolated_contexts_share_three_processes_and_close_one_engine_only(capsys):
    async def exercise():
        protocol, sessions = modules()
        factory, browsers, launches, exited = playwright()
        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )
        reg = sessions.automatic_engine_registry(
            SITE, pool=pool, engine_factory=Engine, boundary_check=lambda: None
        )
        all_ids = []
        for engine in ("queues_tokens", "browsers_members"):
            activation = str(uuid4())
            for browser, count in (("chromium", 15), ("firefox", 5), ("webkit", 5)):
                all_ids.extend(
                    identity(protocol, engine=engine, activation=activation, browser=browser)
                    for _ in range(count)
                )
        replies = await asyncio.gather(
            *(reg.execute(protocol.EngineRequest(ident, "observe")) for ident in all_ids)
        )
        assert all(
            reply.status == "OK" and reply.result.outcome == "QUEUE_ACTIVE" for reply in replies
        )
        assert reg.live_contexts == 50 and len(launches) == 3
        assert [len(browsers[kind].contexts) for kind in ("chromium", "firefox", "webkit")] == [
            30,
            10,
            10,
        ]
        chromium_options = next(options for kind, options in launches if kind == "chromium")
        assert chromium_options["chromium_sandbox"] is True
        assert all(
            "chromium_sandbox" not in options and "args" not in options
            for kind, options in launches
            if kind != "chromium"
        )
        contexts = [context for browser in browsers.values() for context in browser.contexts]
        assert len({id(context.page) for context in contexts}) == 50
        assert all(context.pages == len(context.page.navigations) == 1 for context in contexts)
        inspected = (await reg.execute(protocol.EngineRequest(all_ids[0], "inspect"))).result
        assert inspected.queue_id == "fixture-queue" and inspected.queue_number == 21
        assert inspected.users_ahead == 20 and inspected.users_in_queue == 50
        assert inspected.expected_service_time == "12:30" and inspected.final_url == SITE
        assert SITE not in repr(inspected)
        await reg.execute(protocol.EngineRequest(all_ids[0], "close", close_scope="activation"))
        assert reg.live_contexts == 25 and sum(context.closed for context in contexts) == 25
        assert all(not browser.closed for browser in browsers.values())
        assert (await reg.execute(protocol.EngineRequest(all_ids[-1], "observe"))).status == "OK"
        await reg.close()
        assert all(context.closed for context in contexts)
        assert all(browser.closed for browser in browsers.values()) and exited == [True]

    asyncio.run(exercise())
    output = capsys.readouterr()
    assert SITE not in output.out + output.err and "legacy-cookie" not in output.out + output.err


def test_pool_initialization_lock_does_not_block_an_existing_page_poll(capsys):
    async def exercise():
        protocol, sessions = modules()
        factory, browsers, _, _ = playwright()
        entered = asyncio.Event()
        release = asyncio.Event()
        engine_calls = []

        class SlowEngine(Engine):
            async def run_isolated_task(self, worker_id, target_url):
                engine_calls.append(True)
                if len(engine_calls) == 2:
                    entered.set()
                    await release.wait()
                return await super().run_isolated_task(worker_id, target_url)

        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )
        reg = sessions.automatic_engine_registry(
            SITE, pool=pool, engine_factory=SlowEngine, boundary_check=lambda: None
        )
        first = identity(protocol)
        second = replace(first, session_id=str(uuid4()))
        third = identity(protocol, engine="browsers_members")
        await reg.execute(protocol.EngineRequest(first, "observe"))
        opening = asyncio.create_task(reg.execute(protocol.EngineRequest(second, "observe")))
        await entered.wait()
        other_opening = asyncio.create_task(reg.execute(protocol.EngineRequest(third, "observe")))
        await asyncio.sleep(0)
        assert len(engine_calls) == 2
        assert (
            await asyncio.wait_for(reg.execute(protocol.EngineRequest(first, "observe")), 0.2)
        ).status == "OK"
        assert not opening.done() and not other_opening.done()
        release.set()
        assert all(reply.status == "OK" for reply in await asyncio.gather(opening, other_opening))
        assert len(browsers["chromium"].contexts) == 3
        await reg.close()

    asyncio.run(exercise())
    output = capsys.readouterr()
    assert SITE not in output.out + output.err


def test_stop_during_poll_allows_cooperative_observer_cleanup_to_finish():
    async def exercise():
        protocol, sessions = modules()
        factory, browsers, _, _ = playwright()
        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )
        reg = sessions.automatic_engine_registry(
            SITE, pool=pool, engine_factory=Engine, boundary_check=lambda: None
        )
        ident = identity(protocol)
        await reg.execute(protocol.EngineRequest(ident, "observe"))
        context = browsers["chromium"].contexts[0]
        original_close = context.close

        async def slow_close():
            await asyncio.sleep(0.01)
            await original_close()

        context.close = slow_close
        context.page.entered.clear()
        context.page.release.clear()
        running = asyncio.create_task(reg.execute(protocol.EngineRequest(ident, "observe")))
        await context.page.entered.wait()
        closed = await reg.execute(protocol.EngineRequest(ident, "close", close_scope="activation"))
        assert closed.status == "CLOSED" and context.closed
        assert (await running).status == "NO_GO"
        await reg.close()

    asyncio.run(exercise())


def test_missing_browser_type_is_reported_without_disabling_an_available_type():
    async def exercise():
        protocol, sessions = modules()
        chrome = Browser()
        firefox_calls = []

        class Available:
            async def launch(self, **_options):
                return chrome

        class Unavailable:
            async def launch(self, **_options):
                firefox_calls.append(True)
                raise RuntimeError("missing disposable fixture executable")

        @asynccontextmanager
        async def factory():
            yield SimpleNamespace(chromium=Available(), firefox=Unavailable(), webkit=Unavailable())

        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )
        reg = sessions.automatic_engine_registry(
            SITE, pool=pool, engine_factory=Engine, boundary_check=lambda: None
        )
        first = identity(protocol)
        absent = replace(first, browser="firefox", session_id=str(uuid4()))
        assert (await reg.execute(protocol.EngineRequest(first, "observe"))).status == "OK"
        assert (await reg.execute(protocol.EngineRequest(absent, "observe"))).status == "NO_GO"
        new = replace(first, session_id=str(uuid4()))
        result = await reg.execute(protocol.EngineRequest(new, "observe"))
        assert result.status == "OK" and result.result.outcome == "QUEUE_ACTIVE"
        again = replace(absent, session_id=str(uuid4()))
        assert (await reg.execute(protocol.EngineRequest(again, "observe"))).status == "NO_GO"
        assert firefox_calls == [True] and not reg.poisoned and not chrome.closed
        await reg.close()

    asyncio.run(exercise())


def test_stop_during_browser_launch_closes_a_late_returned_process():
    async def exercise():
        protocol, sessions = modules()
        browser = Browser()
        entered = asyncio.Event()

        class Slow:
            async def launch(self, **_options):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    return browser

        @asynccontextmanager
        async def factory():
            yield SimpleNamespace(chromium=Slow())

        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )
        reg = sessions.automatic_engine_registry(
            SITE, pool=pool, engine_factory=Engine, boundary_check=lambda: None
        )
        ident = identity(protocol)
        running = asyncio.create_task(reg.execute(protocol.EngineRequest(ident, "observe")))
        await entered.wait()
        with pytest.raises(SyntheticIPCError, match="engine_teardown_unverified"):
            await asyncio.wait_for(reg.close(), 0.5)
        assert (await running).status != "OK"
        assert browser.closed, "a browser returned after STOP must still be torn down"

    asyncio.run(exercise())


def test_legacy_chromium_telemetry_is_emitted_only_for_actual_chromium(monkeypatch):
    from boca_socios.browser import activity_events, automatic_observer

    async def exercise():
        protocol, sessions = modules()
        events = []
        monkeypatch.setattr(activity_events, "emit_chromium_event", events.append)
        monkeypatch.setattr(automatic_observer, "emit_chromium_event", events.append)
        factory, _, _, _ = playwright()
        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )
        reg = sessions.automatic_engine_registry(
            SITE, pool=pool, engine_factory=Engine, boundary_check=lambda: None
        )
        firefox = identity(protocol, browser="firefox")
        await reg.execute(protocol.EngineRequest(firefox, "observe"))
        await reg.execute(protocol.EngineRequest(firefox, "close"))
        assert events == [], "Firefox must not produce a Chromium observation"
        chromium = replace(firefox, browser="chromium", session_id=str(uuid4()))
        await reg.execute(protocol.EngineRequest(chromium, "observe"))
        await reg.close()
        assert events == [
            "launch_requested",
            "launched",
            "context_ready",
            "context_closed",
            "browser_closed",
        ]

    asyncio.run(exercise())


def test_stop_retains_budget_for_remote_context_allocated_before_delayed_response():
    from boca_socios.browser.automatic_observer import AutomaticQueueObserver

    async def exercise():
        protocol, sessions = modules()
        entered, release = asyncio.Event(), asyncio.Event()

        class DelayedBrowser(Browser):
            hold = False

            async def new_context(self, **options):
                context = await super().new_context(**options)
                if self.hold:
                    self.hold = False
                    entered.set()
                    await release.wait()
                return context

        browser = DelayedBrowser()

        class Type:
            async def launch(self, **_options):
                return browser

        @asynccontextmanager
        async def factory():
            yield SimpleNamespace(chromium=Type())

        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )

        def observer(ident):
            return AutomaticQueueObserver(
                SITE,
                browsers=pool.browser_factory(ident.browser),
                engine_factory=Engine,
                boundary_check=lambda: None,
                initialization_lock=pool.initialization_lock,
                teardown_seconds=0.02,
                retain_until_closed=True,
            )

        reg = sessions.EngineSessionRegistry(
            observer_factory=observer, pool=pool, teardown_seconds=0.1
        )
        b = identity(protocol, engine="browsers_members")
        a = identity(protocol)
        assert (await reg.execute(protocol.EngineRequest(b, "observe"))).status == "OK"
        browser.hold = True
        opening = asyncio.create_task(reg.execute(protocol.EngineRequest(a, "observe")))
        await entered.wait()
        stopped = await asyncio.wait_for(
            reg.execute(protocol.EngineRequest(a, "close", close_scope="activation")), 0.3
        )
        assert stopped.status == "TEARDOWN_UNVERIFIED", (
            "unknown allocated context cannot authorize CLOSED"
        )
        assert reg.live_contexts == 2 and reg.poisoned
        assert not browser.closed and not browser.contexts[0].closed
        assert (await opening).status != "OK"
        new = identity(protocol, generation=2)
        assert (
            await reg.execute(protocol.EngineRequest(new, "observe"))
        ).status == "TEARDOWN_UNVERIFIED"
        release.set()
        async with asyncio.timeout(0.3):
            while not browser.contexts[1].closed:
                await asyncio.sleep(0.001)
        assert not browser.contexts[0].closed, "late context cleanup must not close B"
        with pytest.raises(SyntheticIPCError, match="engine_teardown_unverified"):
            await reg.close()

    asyncio.run(exercise())


def test_stop_during_playwright_acquisition_preserves_manager_custody():
    async def exercise():
        protocol, sessions = modules()
        entered, release = asyncio.Event(), asyncio.Event()
        managers, exited = [], []

        @asynccontextmanager
        async def factory():
            managers.append(True)
            entered.set()
            await release.wait()
            try:
                yield SimpleNamespace()
            finally:
                exited.append(True)

        pool = sessions.SharedBrowserPool(
            playwright_factory=factory, boundary_check=lambda: None, opening_interval=0
        )
        reg = sessions.automatic_engine_registry(
            SITE, pool=pool, engine_factory=Engine, boundary_check=lambda: None
        )
        ident = identity(protocol)
        opening = asyncio.create_task(reg.execute(protocol.EngineRequest(ident, "observe")))
        await entered.wait()
        stopped = await asyncio.wait_for(
            reg.execute(protocol.EngineRequest(ident, "close", close_scope="activation")), 0.3
        )
        assert stopped.status == "TEARDOWN_UNVERIFIED" and reg.poisoned
        assert (await opening).status != "OK"
        assert (
            await reg.execute(protocol.EngineRequest(identity(protocol, generation=2), "observe"))
        ).status == "TEARDOWN_UNVERIFIED"
        release.set()
        with pytest.raises(SyntheticIPCError, match="engine_teardown_unverified"):
            await reg.close()
        assert managers == exited == [True], "STOP must not lose or overwrite the acquired manager"

    asyncio.run(exercise())
