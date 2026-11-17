"""Runner-only Chromium QA of the real Boca WSGI panel with synthetic custody.

This is an offline loopback fixture, NOT the droplet, Queue-it or Boca site.
The only emitted evidence is a fixed PASS/NO_GO category, never DOM or secrets.
"""

from __future__ import annotations

import secrets
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

GUEST_PAGES = ("/", "/control", "/control/actividad", "/configuracion")
PRIMARY_LINKS = (
    ("/control", "Control"),
    ("/control/actividad", "Actividad"),
    ("/configuracion", "Configuración"),
)
SECONDARY_LINKS = (
    ("/socios", "Socios"),
    ("/comandos", "Simulación"),
    ("/telegram", "Telegram"),
    ("/estado", "Estado"),
    ("/avisos", "Avisos"),
    ("/avisos-oficiales", "Eventos oficiales"),
    ("/monitor/tokens", "Monitor de tokens"),
)
WIDTHS = (412, 800)


def allow_boca_qa_request(url: str, method: str, origin: str, *, owner: bool) -> bool:
    """Allow only exact synthetic-loopback GET URLs; no external destinations."""
    if method != "GET":
        return False
    try:
        base = urlsplit(origin)
        target = urlsplit(url)
        paths = GUEST_PAGES + (("/control/motores.json",) if owner else ())
        return (
            base.scheme == target.scheme == "http"
            and base.hostname == target.hostname == "127.0.0.1"
            and base.port == target.port
            and base.username is None
            and target.username is None
            and target.password is None
            and not target.query
            and not target.fragment
            and target.path in paths
            and url == origin + target.path
        )
    except ValueError:
        return False


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass


@contextmanager
def local_synthetic_panel() -> Iterator[tuple[str, Callable[[], str]]]:
    """Serve real app with an owner-header fixture, not browser passkey proof."""
    repository = Path(__file__).resolve().parents[1]
    test_directory = str(repository / "tests")
    if test_directory not in sys.path:
        sys.path.insert(0, test_directory)
    from test_private_engine_controls import panel  # noqa: PLC0415 - test-only fixture

    with TemporaryDirectory(prefix="boca-qa-guest-") as folder:
        with pytest.MonkeyPatch.context() as patcher:
            app, engines, synthetic_cookie = panel(Path(folder), patcher)
            private_origin = urlsplit(app._origin)
            approved_markers: set[str] = set()

            def mint_owner_header() -> str:
                # A distinct ephemeral bearer per owner-only browser context.
                marker = secrets.token_urlsafe(32)
                approved_markers.add(marker)
                return marker

            def local_gateway(environ, start):
                if environ.get("REQUEST_METHOD") != "GET":
                    start("405 Method Not Allowed", [("Content-Type", "text/plain")])
                    return [b"Method not allowed"]
                marker = environ.pop("HTTP_X_BOCA_QA_OWNER", None)
                if isinstance(marker, str) and any(
                    secrets.compare_digest(marker, approved) for approved in approved_markers
                ):
                    # Only this disposable WSGI adapter receives the already
                    # authenticated SYNTHETIC test session. The browser never
                    # fakes a __Host-/Secure cookie or tests real passkeys.
                    environ["HTTP_COOKIE"] = synthetic_cookie
                else:
                    environ.pop("HTTP_COOKIE", None)
                # Synthetic gateway assertions only: the listening socket is HTTP
                # on 127.0.0.1, with no deployed TLS, passkey or provider network.
                environ["wsgi.url_scheme"] = private_origin.scheme
                environ["HTTP_HOST"] = private_origin.netloc
                return app(environ, start)

            server = make_server("127.0.0.1", 0, local_gateway, handler_class=_QuietHandler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{server.server_port}", mint_owner_header
                if engines.calls:
                    raise RuntimeError("Synthetic motor must not be mutated by QA")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                if thread.is_alive():
                    raise RuntimeError("Disposable fixture failed to stop")


def _visible_focusable_navigation(page, name: str, expected: tuple[tuple[str, str], ...]):
    nav = page.get_by_role("navigation", name=name)
    assert nav.count() == 1
    links = nav.get_by_role("link").all()
    assert len(links) == len(expected)
    for link, (path, label) in zip(links, expected, strict=True):
        assert link.is_visible()
        assert link.get_attribute("href") == path
        assert link.inner_text().strip() == label
        link.focus()
        assert link.evaluate("node => document.activeElement === node")
    for current, next_link in zip(links, links[1:], strict=False):
        current.focus()
        page.keyboard.press("Tab")
        assert next_link.evaluate("node => document.activeElement === node")


def _no_horizontal_overflow(page) -> None:
    assert page.evaluate(
        "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) "
        "<= window.innerWidth + 1"
    )


def _context_route(context, origin: str, *, owner: bool) -> list[bool]:
    blocked: list[bool] = []

    def protect(route):
        request = route.request
        if allow_boca_qa_request(request.url, request.method, origin, owner=owner):
            route.continue_()
        else:
            blocked.append(True)
            route.abort()

    context.route("**/*", protect)
    return blocked


def _inspect_guest(page, origin: str) -> None:
    response = page.goto(origin + "/", wait_until="domcontentloaded", timeout=9000)
    assert response is not None and response.status == 200
    _visible_focusable_navigation(page, "Principal", PRIMARY_LINKS)
    assert page.get_by_role("navigation", name="Otras funciones").count() == 0
    assert page.locator("form").count() == 0
    assert page.locator("input").count() == 0
    _no_horizontal_overflow(page)
    for path, label in PRIMARY_LINKS:
        page.get_by_role("navigation", name="Principal").get_by_role(
            "link", name=label, exact=True
        ).click()
        assert page.url == origin + path
        assert page.locator("main h1").count() == 1
        assert page.locator("form").count() == 0
        assert page.locator("input").count() == 0
        login = page.get_by_role(
            "link", name="Ingresar para operar motores y editar configuración", exact=True
        )
        assert login.is_visible() and login.get_attribute("href") == "/ingresar"
        assert page.get_by_role("navigation", name="Otras funciones").count() == 0
        _visible_focusable_navigation(page, "Principal", PRIMARY_LINKS)
        _no_horizontal_overflow(page)


def _inspect_owner(page, origin: str) -> None:
    response = page.goto(origin + "/control", wait_until="domcontentloaded", timeout=9000)
    assert response is not None and response.status == 200
    assert page.locator('form[method="post"]').count() > 0
    _visible_focusable_navigation(page, "Principal", PRIMARY_LINKS)
    _visible_focusable_navigation(page, "Otras funciones", SECONDARY_LINKS)
    _no_horizontal_overflow(page)


def run(phase: list[str]) -> bool:
    """Fresh Chrome contexts inspect guest and owner-fixture UX, not passkeys."""
    phase[0] = "FIXTURE"
    with local_synthetic_panel() as (origin, mint_owner_header):
        phase[0] = "CHROME_START"
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 - pinned optional group

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="chrome", headless=True, args=["--disable-background-networking"]
            )
            try:
                for width in WIDTHS:
                    for owner in (False, True):
                        phase[0] = "OWNER_NAV" if owner else "GUEST_NAV"
                        context = browser.new_context(
                            viewport={"width": width, "height": 820},
                            service_workers="block",
                            accept_downloads=False,
                            ignore_https_errors=False,
                        )
                        try:
                            blocked = _context_route(context, origin, owner=owner)
                            if owner:
                                context.set_extra_http_headers(
                                    {"X-Boca-QA-Owner": mint_owner_header()}
                                )
                            page = context.new_page()
                            page.set_default_timeout(8000)
                            errors: list[bool] = []
                            page.on("pageerror", lambda _error, errors=errors: errors.append(True))
                            page.on(
                                "download", lambda _download, errors=errors: errors.append(True)
                            )
                            page.on(
                                "console",
                                lambda message, errors=errors: (
                                    errors.append(True) if message.type == "error" else None
                                ),
                            )
                            if owner:
                                _inspect_owner(page, origin)
                            else:
                                _inspect_guest(page, origin)
                                assert context.cookies() == []
                            assert not blocked and not errors
                        finally:
                            context.close()
                phase[0] = "CLEANUP"
            finally:
                browser.close()
    return True


def main() -> int:
    phase = ["FIXTURE"]
    try:
        passed = run(phase)
    except Exception:
        passed = False
    category = "COMPLETE" if passed else phase[0]
    if category not in ("COMPLETE", "FIXTURE", "CHROME_START", "GUEST_NAV", "OWNER_NAV", "CLEANUP"):
        category = "UNKNOWN"
    print(
        "BOCA_GUEST_UX_PLAYWRIGHT "
        f"state={'PASS' if passed else 'NO_GO'} phase={category} "
        "mode=OFFLINE_FIXTURE widths=412,800 "
        "guest_routes=4 owner_primary=3 owner_other=7 owner_auth=WSGI_SYNTHETIC_ONLY "
        "requests=LOCAL_GET_ONLY actions=0 screenshots=0 page_egress=ROUTE_DENIED"
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
