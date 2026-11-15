"""Owner-started, single-session observation through the existing engine boundary.

The legacy navigation modules stay byte-for-byte intact. Only their one-job
entry point is reused, behind an ordinary sandboxed browser and a facade that
owns the lifetime of the page. The ordinary observation does not collect cookies.
An explicit correlated login continuation uses that same context and the fixed
supervised authentication transport. No form is submitted, challenge interacted
with, additional queue session created, or ticket action performed.
Import and construction are inert; the explicit private IPC starts work.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    redirect_stderr,
    redirect_stdout,
)
from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from math import isfinite
from time import monotonic
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from boca_socios.browser.activity_events import emit_chromium_event
from boca_socios.browser.boca_auth_protocol import (
    BocaAuthReadiness,
    BocaAuthReply,
    BocaAuthRequest,
    operation_id,
)
from boca_socios.browser.boca_login_process import LOGIN_URL, normalize_cookies, run_login
from boca_socios.browser.engine_protocol import (
    NavigationAttempt,
    NavigationPurpose,
    Scalar,
    SessionInspection,
)
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from boca_socios.browser.offline_fixture import _bounded_close
from boca_socios.browser.queue_page_observation import (
    QueuePageObservation,
    _model_is_valid,
    parse_queue_page_observation,
)
from boca_socios.browser.site_url_runtime import require_site_url
from boca_socios.browser.worker_health import validate_worker_boundary

_QUEUE_BRIDGE_HOST = "bocajuniors.queue-it.net"
_WAITING = {"QUEUE_ACTIVE", "PREQUEUE"}

_LOGIN_READY_SCRIPT = r"""() => {
  // boca_login_ready: structural evidence only, never read input values.
  const visible = e => !!e && !!e.getClientRects().length &&
    getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
  const enabled = e => visible(e) && !e.disabled && e.getAttribute('aria-disabled') !== 'true';
  const blocked = '[id*="captcha" i], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], ' +
    '#challenge-form, #challenge-running, iframe[src*="challenges.cloudflare.com"], ' +
    '#MainPart_divPreQueue, #MainPart_divProgressbar, #queueId, #MainPart_lbQueueNumber';
  if ([...document.querySelectorAll(blocked)].some(visible) || window.queueViewModel) return [];
  const forms = [...document.querySelectorAll('form')].filter(visible).filter(form =>
    [...form.querySelectorAll('input[type="password"]')].some(enabled));
  if (forms.length !== 1) return [];
  return forms.map(form => {
    const emails = [...form.querySelectorAll('input[type="email"]')].filter(enabled);
    const passwords = [...form.querySelectorAll('input[type="password"]')].filter(enabled);
    const submits = [...form.querySelectorAll('button, input[type="submit"]')].filter(enabled);
    const login = submits.filter(e => /^(ingresar|iniciar sesión|iniciar sesion|acceder|entrar|login|log in|sign in)$/i
      .test((e.innerText || e.value || e.getAttribute('aria-label') || '').trim()));
    const headings = [...form.querySelectorAll('h1, h2, h3, legend')].filter(visible);
    const ambiguous = [...submits, ...headings].some(e =>
      /registr|crear cuenta|restablecer|reset|recuperar contraseña|cambiar contraseña/i
      .test(e.innerText || e.value || ''));
    return {emails: emails.length, passwords: passwords.length, login_buttons: login.length,
      ambiguous, new_password: passwords.some(e => e.autocomplete === 'new-password')};
  });
}"""


def _login_form_ready(value: object) -> bool:
    """Require one visible form with an unambiguous existing-account login action."""
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        return False
    form = value[0]
    if set(form) != {"emails", "passwords", "login_buttons", "ambiguous", "new_password"}:
        return False
    return (
        all(
            type(form[key]) is int and form[key] == 1
            for key in ("emails", "passwords", "login_buttons")
        )
        and form["ambiguous"] is False
        and form["new_password"] is False
    )


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


class _Navigate(Protocol):
    async def __call__(
        self, page: _Page, url: str, *, purpose: NavigationPurpose
    ) -> int | None: ...


class _Context(Protocol):
    async def cookies(self, urls: str) -> object: ...

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
    firefox: _Chromium
    webkit: _Chromium


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
        if owner.closing or owner.navigated or url != owner.destination or owner.page is None:
            raise SyntheticIPCError("automatic_navigation_unverified")
        owner.navigated = True
        # A queue may continuously poll; waiting for networkidle can time out
        # despite a fully received page. This integration boundary waits only
        # for DOM readiness and leaves later reads on the same live page.
        owner.http_status = await owner.navigate(owner.page, url, purpose="SITE_URL")
        owner.navigation_completed = True


class _ContextFacade:
    def __init__(self, owner: _BrowserFacade) -> None:
        self._owner = owner

    async def new_page(self) -> _PageFacade:
        owner = self._owner
        if owner.closing or owner.context is None or owner.page is not None:
            raise SyntheticIPCError("automatic_page_unverified")
        owner.page = await owner.context.new_page()
        if owner.closing:
            raise SyntheticIPCError("automatic_observer_stopped")
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
    def __init__(
        self,
        browser: _Browser,
        destination: str,
        *,
        navigate: _Navigate,
        chromium_activity: bool = True,
    ) -> None:
        self._browser = browser
        self._chromium_activity = chromium_activity
        self.destination = destination
        self.navigate = navigate
        self.context: _Context | None = None
        self.context_creation: asyncio.Task[_Context] | None = None
        self.closing = False
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
        if self.closing or self.context is not None or self.context_creation is not None:
            raise SyntheticIPCError("automatic_context_unverified")
        # Do not carry forward the legacy spoofed user agent. Preserve only
        # the one-session integration, with normal browser identity and TLS.
        self.context_creation = asyncio.create_task(
            self._browser.new_context(
                java_script_enabled=True,
                service_workers="block",
                accept_downloads=False,
                ignore_https_errors=False,
            )
        )
        self.context_creation.add_done_callback(self._remember_context)
        # Remote allocation may happen before its response. Caller cancellation
        # must not erase the only task capable of receiving that handle.
        self.context = await asyncio.shield(self.context_creation)
        if self.closing:
            raise SyntheticIPCError("automatic_observer_stopped")
        await self.context.route("**/*", self._guard)
        await self.context.route_web_socket("**/*", self._deny_websocket)
        if self._chromium_activity:
            emit_chromium_event("context_ready")
        return _ContextFacade(self)

    def _remember_context(self, task: asyncio.Task[_Context]) -> None:
        try:
            self.context = task.result()
        except (Exception, asyncio.CancelledError):
            return


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
        initialization_lock: asyncio.Lock | None = None,
        retain_until_closed: bool = False,
        retain_after_auth: bool = False,
        chromium_activity: bool = True,
    ) -> None:
        for value, maximum in (
            (timeout_seconds, 15.0),
            (teardown_seconds, 5.0),
            (settle_seconds, 3.0),
        ):
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= maximum:
                raise ValueError("automatic observer timeout unverified")
        if (
            type(retain_until_closed) is not bool
            or type(retain_after_auth) is not bool
            or type(chromium_activity) is not bool
        ):
            raise ValueError("automatic observer retention unverified")
        self._destination = require_site_url(site_url)
        self._browsers = browsers
        self._engine_factory = engine_factory
        self._check = boundary_check
        self._now = now
        self._timeout = float(timeout_seconds)
        self._teardown = float(teardown_seconds)
        self._settle = float(settle_seconds)
        self._initialization_lock = initialization_lock or asyncio.Lock()
        self._retain_until_closed = retain_until_closed
        self._retain_after_auth = retain_after_auth
        self._chromium_activity = chromium_activity
        self._auth_response_received = False
        self._inspection = SessionInspection()
        self._navigation_attempt: NavigationAttempt | None = None
        self._manager: AbstractAsyncContextManager[_Browser] | None = None
        self._facade: _BrowserFacade | None = None
        self._active: asyncio.Task[object] | None = None
        self._cleanup_lock = asyncio.Lock()
        self._closed = False
        self._stopped = False
        self._poisoned = False
        self._bridge_followed = False
        self._auth_operation: str | None = None
        self._auth_preparing = False
        self._auth_nonce: str | None = None
        self._auth_deadline = 0.0
        self._auth_used = False
        self._auth_page_url: str | None = None
        self._auth_context: _Context | None = None
        self._auth_page: _Page | None = None
        self._target_followed = False
        self._last_received: dict[str, object] = {}
        self._ready_observation: QueuePageObservation | None = None
        self._login_runner = run_login

    async def _navigate(self, page: _Page, url: str, *, purpose: NavigationPurpose) -> int | None:
        parts = urlsplit(url)
        attempt = NavigationAttempt(
            sequence=self._navigation_attempt.sequence + 1 if self._navigation_attempt else 1,
            purpose=purpose,
            display_url=urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
            started_at=self._now(),
            result="STARTED",
        )
        self._navigation_attempt = attempt
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=12_000)
        except asyncio.CancelledError:
            self._navigation_attempt = replace(attempt, result="CANCELLED")
            raise
        except BaseException:
            self._navigation_attempt = replace(attempt, result="FAILED")
            raise
        status = response.status if response is not None else None
        self._navigation_attempt = replace(attempt, result="RETURNED", http_status=status)
        return status

    async def _start_session(self) -> None:
        manager = self._browsers()
        browser = await manager.__aenter__()
        self._manager = manager
        self._facade = _BrowserFacade(
            browser,
            self._destination,
            navigate=self._navigate,
            chromium_activity=self._chromium_activity,
        )
        engine = self._engine_factory()
        engine.browser = self._facade
        discarded = _DiscardOutput()
        # Legacy prints can contain the URL or exception. Do not log, buffer
        # or replay them, and never treat its cookie/status return as access.
        async with self._initialization_lock:
            if self._closed or self._stopped:
                raise SyntheticIPCError("automatic_observer_stopped")
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
        self._last_received = received
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
        # Project only the last received model already checked by the canonical
        # parser; inspection itself does not evaluate, reload or navigate.
        valid_model = model if isinstance(model, dict) and _model_is_valid(model) else {}
        ticket = valid_model.get("ticket")
        fields = ticket if isinstance(ticket, dict) else {}
        final_url = facade.page.url if _received_http_url(facade.page.url) else None
        try:
            self._inspection = SessionInspection(
                final_url=final_url,
                queue_id=cast(str | None, valid_model.get("queueId")) or None,
                queue_number=cast(Scalar, fields.get("queueNumber")),
                users_ahead=cast(Scalar, fields.get("usersInLineAheadOfYou")),
                users_in_queue=cast(Scalar, fields.get("usersInQueue")),
                expected_service_time=cast(Scalar, fields.get("expectedServiceTime")),
                observed_at=observation.observed_at,
                context_open=True,
            )
        except SyntheticIPCError:
            self._inspection = SessionInspection(
                final_url=final_url, observed_at=observation.observed_at, context_open=True
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
                facade.http_status = await self._navigate(facade.page, link, purpose="QUEUE_BRIDGE")
                return await self._snapshot()
        return observation

    @staticmethod
    def _consume(task: asyncio.Task[object]) -> None:
        try:
            task.result()
        except (Exception, asyncio.CancelledError):
            return

    def _close_late_context(self, task: asyncio.Task[_Context]) -> None:
        """Reclaim a late handle without reopening its retired observer identity."""
        try:
            context = task.result()
        except (Exception, asyncio.CancelledError):
            return
        closing = asyncio.create_task(_bounded_close(context, self._teardown))
        closing.add_done_callback(self._consume)

    async def _close_session(self, *, deadline: float | None = None) -> None:
        async with self._cleanup_lock:
            deadline = (
                min(deadline, monotonic() + self._teardown)
                if deadline is not None
                else monotonic() + self._teardown
            )
            facade, manager = self._facade, self._manager
            self._facade = None
            self._manager = None
            failed = False
            if facade is not None:
                facade.closing = True
                creation = facade.context_creation
                if creation is not None:
                    try:
                        _, pending_creation = await asyncio.wait(
                            {creation}, timeout=max(0.001, deadline - monotonic())
                        )
                        if pending_creation:
                            # Keep the in-flight allocation alive to recover a
                            # late handle. Its slot stays held and the worker is
                            # poisoned; returning the browser loan proves no
                            # remote context was released.
                            creation.add_done_callback(self._close_late_context)
                            failed = True
                        else:
                            creation.result()
                    except (Exception, asyncio.CancelledError):
                        creation.add_done_callback(self._close_late_context)
                        failed = True
            if facade is not None and facade.context is not None:
                try:
                    await _bounded_close(facade.context, max(0.001, deadline - monotonic()))
                    if self._chromium_activity:
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
            except SyntheticIPCError as exc:
                if str(exc) in {
                    "engine_browser_unavailable",
                    "engine_launch_unverified",
                    "engine_pool_closed",
                }:
                    self._closed = True
                    raise
                accepted = self._failed()
            except Exception:
                accepted = self._failed()
            retained_for_auth = self._auth_preparing and accepted.outcome in {
                "UNKNOWN",
                "TARGET_OBSERVED",
            }
            if (
                (
                    accepted.outcome not in _WAITING
                    and not retained_for_auth
                    and not self._retain_until_closed
                    and not (self._retain_after_auth and self._auth_response_received)
                )
                or self._stopped
                or active.cancelling()
            ):
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

    async def _login_ready(self) -> bool:
        facade = self._facade
        if facade is None or facade.page is None or facade.context is None:
            return False
        url = facade.page.url
        if (
            not _received_http_url(url)
            or _origin(url) != ("https", "bocasocios.bocajuniors.com.ar", 443)
            or facade.http_status != 200
            or facade.blocked_write
        ):
            return False
        received = self._last_received
        if received.get("markers") or received.get("queue_links"):
            return False
        # A token query may remain on the portal URL. A live queue model may not.
        if received.get("queue_model") is not None:
            return False
        ready = await facade.page.evaluate(_LOGIN_READY_SCRIPT)
        return (
            _login_form_ready(ready)
            and facade is self._facade
            and facade.page.url == url
            and not self._stopped
            and not self._closed
        )

    async def prepare_boca_login(self, operation: str) -> BocaAuthReadiness:
        operation_id(operation)
        if (
            self._auth_used
            or self._stopped
            or self._closed
            or self._poisoned
            or self._auth_preparing
            or self._active is not None
            or self._auth_operation not in {None, operation}
        ):
            raise SyntheticIPCError("boca_auth_session_unverified")
        self._auth_operation = operation
        if self._auth_nonce is not None:
            remaining = self._auth_deadline - monotonic()
            if remaining <= 0 or self._ready_observation is None:
                await self.close()
                raise SyntheticIPCError("boca_auth_readiness_expired")
            return BocaAuthReadiness(
                operation, self._ready_observation, self._auth_nonce, remaining
            )
        self._auth_preparing = True
        try:
            observed = await self.observe_queue()
            self._active = asyncio.current_task()
            async with asyncio.timeout(self._timeout):
                facade = self._facade
                if (
                    observed.outcome == "TARGET_OBSERVED"
                    and facade is not None
                    and facade.page is not None
                    and observed.target_url is not None
                    and facade.page.url != observed.target_url
                    and not self._target_followed
                    and _origin(observed.target_url)
                    == ("https", "bocasocios.bocajuniors.com.ar", 443)
                ):
                    self._target_followed = True
                    facade.http_status = await self._navigate(
                        facade.page, observed.target_url, purpose="RECEIVED_TARGET"
                    )
                    current = await self._snapshot()
                else:
                    current = observed
                if (
                    current.outcome not in {"CHALLENGE", "CHECK_FAILED", *_WAITING}
                    and current.reason not in {"INVALID_OBSERVATION", "CONTRADICTORY_EVIDENCE"}
                    and await self._login_ready()
                ):
                    assert facade is not None and facade.page is not None
                    self._auth_nonce = secrets.token_hex(32)
                    self._auth_deadline = monotonic() + 15.0
                    self._auth_page_url = facade.page.url
                    self._auth_context = facade.context
                    self._auth_page = facade.page
                    self._ready_observation = observed
                    self._bridge_followed = True
                    return BocaAuthReadiness(operation, observed, self._auth_nonce, 15.0)
            if observed.outcome not in _WAITING:
                self._closed = True
                await self._close_session()
            return BocaAuthReadiness(operation, observed, None, 0)
        except BaseException:
            self._closed = True
            await self._close_session()
            raise
        finally:
            self._auth_preparing = False
            self._active = None

    async def login_boca(self, request: BocaAuthRequest) -> BocaAuthReply:
        facade = self._facade
        if (
            self._auth_used
            or self._closed
            or self._stopped
            or self._poisoned
            or self._active is not None
            or request.operation_id != self._auth_operation
            or request.nonce != self._auth_nonce
            or self._auth_nonce is None
            or monotonic() >= self._auth_deadline
            or facade is None
            or facade.page is None
            or facade.context is not self._auth_context
            or facade.page is not self._auth_page
            or facade.page.url != self._auth_page_url
        ):
            raise SyntheticIPCError("boca_auth_readiness_unverified")
        # Single use is consumed before any await, including revalidation.
        self._auth_used = True
        self._auth_nonce = None
        active = asyncio.current_task()
        self._active = active
        raw: bytes | None = None
        try:
            async with asyncio.timeout_at(self._auth_deadline):
                self._check()
                current = await self._snapshot()
                if (
                    current.outcome in {"CHALLENGE", "CHECK_FAILED", *_WAITING}
                    or current.reason in {"INVALID_OBSERVATION", "CONTRADICTORY_EVIDENCE"}
                    or not await self._login_ready()
                ):
                    raise SyntheticIPCError("boca_auth_page_changed")
                assert facade.context is not None
                cookies = normalize_cookies(await facade.context.cookies(LOGIN_URL))
                if (
                    facade is not self._facade
                    or facade.context is not self._auth_context
                    or facade.page is not self._auth_page
                    or facade.page.url != self._auth_page_url
                    or self._stopped
                    or not await self._login_ready()
                ):
                    raise SyntheticIPCError("boca_auth_session_changed")
                raw = await self._login_runner(request, cookies, deadline=self._auth_deadline)
                if (
                    facade is not self._facade
                    or facade.context is not self._auth_context
                    or facade.page is not self._auth_page
                    or facade.page.url != self._auth_page_url
                    or self._stopped
                ):
                    raise SyntheticIPCError("boca_auth_session_changed")
        finally:
            self._auth_response_received = raw is not None
            self._closed = not (
                self._retain_after_auth
                and raw is not None
                and not self._stopped
                and active is not None
                and not active.cancelling()
                and monotonic() < self._auth_deadline
            )
            try:
                if self._closed:
                    await self._close_session(deadline=self._auth_deadline)
            finally:
                self._active = None
        if (
            raw is None
            or self._stopped
            or self._poisoned
            or active is None
            or active.cancelling()
            or monotonic() >= self._auth_deadline
        ):
            raise SyntheticIPCError("boca_auth_result_expired")
        return BocaAuthReply(request.operation_id, request.nonce, raw)

    async def inspect(self) -> SessionInspection:
        """Return cached private evidence; an HTTP auth response never proves DOM login."""
        facade = self._facade
        return replace(
            self._inspection,
            context_open=(
                facade is not None
                and facade.context is not None
                and not self._closed
                and not self._stopped
            ),
            auth_response_received=self._auth_response_received,
            configured_url=self._destination,
            navigation_attempt=self._navigation_attempt,
        )

    async def close(self) -> None:
        self._auth_nonce = None
        self._stopped = True
        self._closed = True
        if self._facade is not None:
            self._facade.closing = True
        active = self._active
        if active is not None and not active.done() and active is not asyncio.current_task():
            # A registry STOP may already have cancelled this task. Repeated
            # cancellation would interrupt its bounded context cleanup.
            if not active.cancelling():
                active.cancel()
            _, pending = await asyncio.wait({active}, timeout=self._teardown)
            if pending:
                self._poisoned = True
        await self._close_session()
        if self._poisoned:
            raise SyntheticIPCError("automatic_observer_teardown_unverified")
