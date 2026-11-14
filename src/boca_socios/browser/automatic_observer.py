"""Owner-started, single-session observation through the existing engine boundary.

The legacy navigation modules stay byte-for-byte intact. Only their one-job
entry point is reused, behind an ordinary sandboxed browser and a facade that
owns the lifetime of the page. There is no swarm, stealth launch, cookie
collection, login, form submission, ticket action or challenge interaction.
Import and construction are inert; the explicit IPC observation starts work.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    redirect_stderr,
    redirect_stdout,
)
from datetime import UTC, datetime
from importlib import import_module
from math import isfinite
from time import monotonic
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from boca_socios.browser.activity_events import emit_chromium_event
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.offline_fixture import _bounded_close
from boca_socios.browser.queue_page_observation import (
    QueuePageObservation,
    parse_queue_page_observation,
)
from boca_socios.browser.site_url_runtime import require_site_url
from boca_socios.browser.worker_health import validate_worker_boundary

_QUEUE_BRIDGE_HOST = "bocajuniors.queue-it.net"
_WAITING = {"QUEUE_ACTIVE", "PREQUEUE"}

# Read only the established Queue-it view-model fields and visible evidence.
# Never return cookies, storage, HTML, arbitrary page properties or credentials.
_SNAPSHOT_SCRIPT = r"""() => {
  const visible = element => !!element && !!element.getClientRects().length &&
    getComputedStyle(element).visibility !== 'hidden' &&
    getComputedStyle(element).display !== 'none';
  const read = value => typeof value === 'function' ? value() : value;
  let invalid = false;
  const scalar = value => {
    if (typeof value === 'string' && value.length > 8192) { invalid = true; return false; }
    return value === null || ['string', 'number', 'boolean'].includes(typeof value);
  };
  const vm = window.queueViewModel;
  let model = null;
  if (vm && typeof vm === 'object') {
    model = {};
    for (const key of ['eventId', 'queueId', 'queueState', 'targetUrl', 'isBeforeOrIdle', 'isIdle']) {
      const value = read(vm[key]);
      if (scalar(value)) model[key] = value;
    }
    const ticket = read(vm.ticket);
    if (ticket && typeof ticket === 'object') {
      model.ticket = {};
      for (const key of ['queuePaused', 'progress', 'expectedServiceTime', 'whichIsIn',
        'usersInLineAheadOfYou', 'usersInQueue', 'queueNumber']) {
        const value = read(ticket[key]);
        if (scalar(value)) model.ticket[key] = value;
      }
    }
  }
  const selectors = {
    prequeue: '#MainPart_divPreQueue', progressbar: '#MainPart_divProgressbar',
    queueid: '#queueId', queuenumber: '#MainPart_lbQueueNumber',
    expectedservice: '#MainPart_lbExpectedServiceTimeRelative',
    captcha: '[id*="captcha" i], iframe[src*="recaptcha"], iframe[src*="hcaptcha"]',
    challenge: '#challenge-form, #challenge-running, iframe[src*="challenges.cloudflare.com"]'
  };
  const markers = Object.entries(selectors).filter(([, selector]) =>
    [...document.querySelectorAll(selector)].some(visible)).map(([name]) => name);
  const links = [...document.querySelectorAll('a[href]')].filter(element => {
    if (!visible(element) || element.hasAttribute('disabled') ||
      element.getAttribute('aria-disabled') === 'true') return false;
    try { return new URL(element.href).hostname === 'bocajuniors.queue-it.net'; }
    catch (_) { return false; }
  }).map(element => element.href);
  const bodyText = document.body?.innerText || '';
  return {invalid, queue_model: model, markers,
    visible_text: bodyText.slice(0, 16384), visible_text_truncated: bodyText.length > 16384,
    queue_links: [...new Set(links)].slice(0, 2)};
}"""


class _Frame(Protocol):
    url: str


class _Request(Protocol):
    url: str
    method: str
    resource_type: str
    frame: _Frame

    def is_navigation_request(self) -> bool: ...


class _Route(Protocol):
    request: _Request

    async def continue_(self) -> None: ...

    async def abort(self) -> None: ...


class _WebSocketRoute(Protocol):
    url: str

    async def close(self) -> None: ...


class _Response(Protocol):
    status: int


class _Page(Protocol):
    url: str
    main_frame: _Frame

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> _Response | None: ...

    async def evaluate(self, expression: str) -> object: ...


class _Context(Protocol):
    async def route(self, pattern: str, handler: Callable[[_Route], Awaitable[None]]) -> None: ...

    async def route_web_socket(
        self, pattern: str, handler: Callable[[_WebSocketRoute], Awaitable[None]]
    ) -> None: ...

    async def new_page(self) -> _Page: ...

    async def close(self) -> None: ...


class _Browser(Protocol):
    async def new_context(self, **options: object) -> _Context: ...

    async def close(self) -> None: ...


class _Chromium(Protocol):
    async def launch(self, **options: object) -> _Browser: ...


class _Playwright(Protocol):
    chromium: _Chromium


class _Engine(Protocol):
    browser: object

    async def run_isolated_task(self, worker_id: int, target_url: str) -> object: ...


BrowserFactory = Callable[[], AbstractAsyncContextManager[_Browser]]
EngineFactory = Callable[[], _Engine]
PlaywrightFactory = Callable[[], AbstractAsyncContextManager[_Playwright]]


def _default_engine() -> _Engine:
    module = import_module("boca_socios.browser.synthetic")
    return cast("_Engine", module.SyntheticBrowserEngine(concurrency_limit=1))


def _default_playwright() -> AbstractAsyncContextManager[_Playwright]:
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    return cast("AbstractAsyncContextManager[_Playwright]", async_playwright())


def _received_http_url(url: str) -> bool:
    """Keep received queries intact while applying the existing destination guard."""
    try:
        if not isinstance(url, str) or len(url.encode("utf-8")) > 8192:
            return False
        if any(ord(character) <= 32 or ord(character) == 127 for character in url):
            return False
        parsed = urlsplit(url)
        require_site_url(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")))
    except (ValueError, UnicodeError):
        return False
    return True


def _origin(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        scheme = {"wss": "https", "ws": "http"}.get(parsed.scheme, parsed.scheme)
        if scheme not in {"http", "https"} or parsed.hostname is None:
            return None
        return scheme, parsed.hostname, parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None


async def readonly_request_guard(
    route: _Route, *, page_url: str = "", main_frame: _Frame | None = None
) -> bool:
    """Permit normal page reads and same-page Queue-it status transport.

    The observer creates no API request or URL. A received Queue-it page may
    run its own fetch/XHR POST to its exact origin; document/form POSTs and
    every Boca or unrelated write remain blocked. This is a single waiting
    room session, never a reservation or purchase transport.
    """
    request = route.request
    allowed = False
    if _received_http_url(request.url):
        allowed = request.method in {"GET", "HEAD"}
        if request.method in {"POST", "OPTIONS"}:
            queue_origin = ("https", _QUEUE_BRIDGE_HOST, 443)
            allowed = (
                _origin(request.url) == _origin(page_url) == queue_origin
                and request.resource_type in {"xhr", "fetch"}
                and request.is_navigation_request() is False
            )
            if allowed:
                try:
                    frame = request.frame
                    allowed = (
                        main_frame is not None
                        and frame is main_frame
                        and _origin(frame.url) == queue_origin
                    )
                except Exception:
                    # Some browser requests have no accessible frame. A
                    # missing initiator cannot authorize the POST exception.
                    allowed = False
    if allowed:
        await route.continue_()
    else:
        await route.abort()
    return allowed


@asynccontextmanager
async def isolated_automatic_browser(
    *,
    playwright_factory: PlaywrightFactory | None = None,
    boundary_check: Callable[[], None] = validate_worker_boundary,
) -> AsyncIterator[_Browser]:
    """Ordinary Chromium; the legacy start_engine and its flags are never called."""
    boundary_check()
    factory = _default_playwright if playwright_factory is None else playwright_factory
    emit_chromium_event("launch_requested")
    async with factory() as api:
        browser = await api.chromium.launch(
            headless=True,
            chromium_sandbox=True,
            timeout=12_000,
            args=["--disable-background-networking"],
        )
        emit_chromium_event("launched")
        try:
            yield browser
        finally:
            try:
                await _bounded_close(browser, 3.0)
            except SyntheticIPCError:
                raise SyntheticIPCError("automatic_observer_teardown_unverified") from None
            emit_chromium_event("browser_closed")


class _DiscardOutput:
    """Discard legacy URL/cookie prints immediately; never retain their text."""

    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        return


class _PageFacade:
    def __init__(self, owner: _BrowserFacade) -> None:
        self._owner = owner

    async def goto(self, url: str, *, wait_until: str) -> None:
        owner = self._owner
        if owner.navigated or url != owner.destination or owner.page is None:
            raise SyntheticIPCError("automatic_navigation_unverified")
        owner.navigated = True
        # A queue may continuously poll; waiting for networkidle can time out
        # despite a fully received page. This integration boundary waits only
        # for DOM readiness and leaves later reads on the same live page.
        response = await owner.page.goto(url, wait_until="domcontentloaded", timeout=12_000)
        owner.http_status = response.status if response is not None else None
        owner.navigation_completed = True


class _ContextFacade:
    def __init__(self, owner: _BrowserFacade) -> None:
        self._owner = owner

    async def new_page(self) -> _PageFacade:
        owner = self._owner
        if owner.context is None or owner.page is not None:
            raise SyntheticIPCError("automatic_page_unverified")
        owner.page = await owner.context.new_page()
        return _PageFacade(owner)

    async def cookies(self) -> list[dict[str, str]]:
        # The legacy return value is ignored. No cookie is needed to classify
        # the actual delivered URL, and no bearer cookie crosses this facade.
        return []

    async def close(self) -> None:
        # The original finally closes its job context. The observer now owns
        # that lifetime so a passive poll never acquires another queue place.
        return


class _BrowserFacade:
    def __init__(self, browser: _Browser, destination: str) -> None:
        self._browser = browser
        self.destination = destination
        self.context: _Context | None = None
        self.page: _Page | None = None
        self.http_status: int | None = None
        self.navigated = False
        self.navigation_completed = False
        self.blocked_write = False

    async def _guard(self, route: _Route) -> None:
        page_url = self.page.url if self.page is not None else self.destination
        allowed = await readonly_request_guard(
            route,
            page_url=page_url,
            main_frame=self.page.main_frame if self.page is not None else None,
        )
        if not allowed and _origin(route.request.url) == _origin(page_url):
            self.blocked_write = True

    async def _deny_websocket(self, route: _WebSocketRoute) -> None:
        page_url = self.page.url if self.page is not None else self.destination
        if _origin(route.url) == _origin(page_url):
            self.blocked_write = True
        await route.close()

    async def new_context(self, **options: object) -> _ContextFacade:
        if self.context is not None:
            raise SyntheticIPCError("automatic_context_unverified")
        # Do not carry forward the legacy spoofed user agent. Preserve only
        # the one-session integration, with normal browser identity and TLS.
        self.context = await self._browser.new_context(
            java_script_enabled=True,
            service_workers="block",
            accept_downloads=False,
            ignore_https_errors=False,
        )
        await self.context.route("**/*", self._guard)
        await self.context.route_web_socket("**/*", self._deny_websocket)
        emit_chromium_event("context_ready")
        return _ContextFacade(self)


class AutomaticQueueObserver:
    """One configured destination and persistent page per explicit activation."""

    def __init__(
        self,
        site_url: str,
        *,
        browsers: BrowserFactory = isolated_automatic_browser,
        engine_factory: EngineFactory = _default_engine,
        boundary_check: Callable[[], None] = validate_worker_boundary,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        timeout_seconds: float = 15.0,
        teardown_seconds: float = 4.0,
        settle_seconds: float = 3.0,
    ) -> None:
        for value, maximum in (
            (timeout_seconds, 15.0),
            (teardown_seconds, 5.0),
            (settle_seconds, 3.0),
        ):
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= maximum:
                raise ValueError("automatic observer timeout unverified")
        self._destination = require_site_url(site_url)
        self._browsers = browsers
        self._engine_factory = engine_factory
        self._check = boundary_check
        self._now = now
        self._timeout = float(timeout_seconds)
        self._teardown = float(teardown_seconds)
        self._settle = float(settle_seconds)
        self._manager: AbstractAsyncContextManager[_Browser] | None = None
        self._facade: _BrowserFacade | None = None
        self._active: asyncio.Task[object] | None = None
        self._cleanup_lock = asyncio.Lock()
        self._closed = False
        self._stopped = False
        self._poisoned = False
        self._bridge_followed = False

    async def _start_session(self) -> None:
        manager = self._browsers()
        browser = await manager.__aenter__()
        self._manager = manager
        self._facade = _BrowserFacade(browser, self._destination)
        engine = self._engine_factory()
        engine.browser = self._facade
        discarded = _DiscardOutput()
        # Legacy prints can contain the URL or exception. Do not log, buffer
        # or replay them, and never treat its cookie/status return as access.
        with redirect_stdout(discarded), redirect_stderr(discarded):
            await engine.run_isolated_task(0, self._destination)
        if not self._facade.navigation_completed:
            raise SyntheticIPCError("automatic_navigation_unverified")

    def _failed(self) -> QueuePageObservation:
        return parse_queue_page_observation(
            final_url="",
            queue_model=None,
            markers=frozenset(),
            observed_at=self._now(),
            check_failed=True,
        )

    async def _snapshot(self) -> QueuePageObservation:
        facade = self._facade
        if facade is None or facade.page is None:
            raise SyntheticIPCError("automatic_page_unverified")
        received = await facade.page.evaluate(_SNAPSHOT_SCRIPT)
        if not isinstance(received, dict) or received.get("invalid") is True:
            return self._failed()
        text = received.get("visible_text")
        markers = received.get("markers")
        model = received.get("queue_model")
        if (
            not isinstance(text, str)
            or not isinstance(markers, list)
            or len(markers) > 7
            or not all(isinstance(marker, str) for marker in markers)
            or (model is not None and not isinstance(model, dict))
        ):
            return self._failed()
        encoded_text = text.encode("utf-8")
        bounded_text = encoded_text[:16384].decode("utf-8", errors="ignore")
        if received.get("visible_text_truncated") is True or len(encoded_text) > 16384:
            # Cutting a partial line can manufacture an exact absence phrase
            # from e.g. "No hay eventos disponibles mientras se actualiza…".
            # Retain only lines whose terminating newline was really received.
            bounded_text = bounded_text.rsplit("\n", 1)[0] if "\n" in bounded_text else ""
        observation = parse_queue_page_observation(
            final_url=facade.page.url,
            queue_model=model,
            markers=frozenset(markers),
            visible_text=bounded_text,
            http_status=facade.http_status,
            observed_at=self._now(),
            check_failed=facade.blocked_write,
        )
        links = received.get("queue_links", [])
        valid_links = (
            tuple(
                link
                for link in links
                if isinstance(link, str)
                and _received_http_url(link)
                and urlsplit(link).hostname == _QUEUE_BRIDGE_HOST
                and urlsplit(link).scheme == "https"
            )
            if isinstance(links, list) and len(links) <= 2
            else ()
        )
        if observation.outcome == "NO_EVENT_OBSERVED" and valid_links:
            return QueuePageObservation(
                outcome="UNKNOWN",
                event_state="UNRECOGNIZED",
                queue_state="UNKNOWN",
                reason="CONTRADICTORY_EVIDENCE",
                observed_at=observation.observed_at,
            )
        if (
            observation.outcome == "UNKNOWN"
            and observation.reason == "NO_RECOGNIZED_EVIDENCE"
            and model is None
            and not self._bridge_followed
            and isinstance(links, list)
            and len(links) == 1
            and len(valid_links) == 1
        ):
            link = valid_links[0]
            if link != facade.page.url:
                self._bridge_followed = True
                response = await facade.page.goto(
                    link, wait_until="domcontentloaded", timeout=12_000
                )
                facade.http_status = response.status if response is not None else None
                return await self._snapshot()
        return observation

    @staticmethod
    def _consume(task: asyncio.Task[object]) -> None:
        try:
            task.result()
        except (Exception, asyncio.CancelledError):
            return

    async def _close_session(self) -> None:
        async with self._cleanup_lock:
            deadline = monotonic() + self._teardown
            facade, manager = self._facade, self._manager
            self._facade = None
            self._manager = None
            failed = False
            if facade is not None and facade.context is not None:
                try:
                    await _bounded_close(facade.context, max(0.001, deadline - monotonic()))
                    emit_chromium_event("context_closed")
                except (Exception, asyncio.CancelledError):
                    failed = True
            if manager is not None:
                closing = asyncio.create_task(manager.__aexit__(None, None, None))
                closing.add_done_callback(self._consume)
                try:
                    _, pending = await asyncio.wait(
                        {closing}, timeout=max(0.001, deadline - monotonic())
                    )
                    if pending:
                        closing.cancel()
                        failed = True
                    else:
                        closing.result()
                except (Exception, asyncio.CancelledError):
                    closing.cancel()
                    failed = True
            if failed:
                self._poisoned = True
                raise SyntheticIPCError("automatic_observer_teardown_unverified")

    async def observe_queue(self) -> QueuePageObservation:
        if self._closed or self._poisoned:
            raise SyntheticIPCError("automatic_observer_stopped")
        if self._active is not None:
            raise SyntheticIPCError("automatic_observer_busy")
        self._check()
        active = asyncio.current_task()
        if active is None:
            raise SyntheticIPCError("automatic_observer_loop_unverified")
        self._active = active
        accepted: QueuePageObservation | None = None
        try:
            try:
                async with asyncio.timeout(self._timeout) as deadline:
                    if self._facade is None:
                        await self._start_session()
                    accepted = await self._snapshot()
                    settle_deadline = monotonic() + self._settle
                    while (
                        accepted.outcome == "UNKNOWN"
                        and accepted.reason
                        in {"NO_RECOGNIZED_EVIDENCE", "EVENT_ID_OBSERVED", "INVALID_OBSERVATION"}
                        and not self._stopped
                        and not active.cancelling()
                    ):
                        remaining = settle_deadline - monotonic()
                        if remaining <= 0:
                            break
                        # An asynchronously populated model may lag the first
                        # DOM and the legacy two-second wait. Read the same
                        # page for a finite window; never reload or click.
                        await asyncio.sleep(min(0.25, remaining))
                        accepted = await self._snapshot()
                if deadline.expired():
                    accepted = self._failed()
            except asyncio.CancelledError:
                self._closed = True
                raise
            except Exception:
                accepted = self._failed()
            if accepted.outcome not in _WAITING or self._stopped or active.cancelling():
                self._closed = True
        finally:
            try:
                if self._closed:
                    await self._close_session()
            finally:
                self._active = None
        if accepted is None or self._stopped or active.cancelling() or self._poisoned:
            raise SyntheticIPCError("automatic_observer_stopped")
        return accepted

    async def close(self) -> None:
        self._stopped = True
        self._closed = True
        active = self._active
        if active is not None and not active.done() and active is not asyncio.current_task():
            active.cancel()
            _, pending = await asyncio.wait({active}, timeout=self._teardown)
            if pending:
                self._poisoned = True
        await self._close_session()
        if self._poisoned:
            raise SyntheticIPCError("automatic_observer_teardown_unverified")
