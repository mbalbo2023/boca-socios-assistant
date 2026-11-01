"""Safety contract for one opt-in observation of the anonymous public home."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def observer():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[1] / "scripts" / "observe_public_home.py"
    spec = importlib.util.spec_from_file_location("public_observer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "url,kind,allowed",
    [
        ("https://bocasocios.bocajuniors.com.ar/auth/login", "document", True),
        ("https://bocasocios.bocajuniors.com.ar/", "document", False),
        ("https://bocasocios.bocajuniors.com.ar/_next/static/a.js", "script", False),
        ("https://bocasocios.bocajuniors.com.ar/auth/login", "document", False),
        ("https://bocasocios.bocajuniors.com.ar/login", "document", False),
        ("https://bocasocios.bocajuniors.com.ar/?unexpected=1", "document", False),
        ("https://bocasocios.bocajuniors.com.ar/_next/image?a=1", "image", False),
        ("https://queue-it.net/?q=x", "document", False),
        ("http://bocasocios.bocajuniors.com.ar/", "document", False),
        ("https://bocasocios.bocajuniors.com.ar.evil.test/", "document", False),
    ],
)
def test_request_allowlist_is_exact_and_one_document(url: str, kind: str, allowed: bool) -> None:
    module = observer()
    previous = url == module.LOGIN_URL and kind == "document" and not allowed
    assert module.allow_request(url, "GET", kind, int(previous)) is allowed
    assert not module.allow_request(url, "POST", kind, 0)


@pytest.mark.parametrize(
    "status,url,text,expected",
    [
        (
            200,
            "https://bocasocios.bocajuniors.com.ar/auth/login",
            "Ingresá a Boca Socios. Iniciar sesión",
            "login_visible",
        ),
        (
            403,
            "https://bocasocios.bocajuniors.com.ar/auth/login",
            "Ingresá a Boca Socios",
            "blocked",
        ),
        (
            200,
            "https://bocasocios.bocajuniors.com.ar/auth/login",
            "Ingresá a Boca Socios. CAPTCHA",
            "challenge",
        ),
        (
            200,
            "https://bocasocios.bocajuniors.com.ar/auth/login",
            "Sala de espera. Iniciar sesión",
            "challenge",
        ),
        (200, "https://bocasocios.bocajuniors.com.ar/auth/login", "Unknown page", "unknown"),
        (200, "https://bocasocios.bocajuniors.com.ar/", "Ingresá a Boca Socios", "blocked"),
        (200, "https://bocasocios.bocajuniors.com.ar/login", "Ingresá a Boca Socios", "blocked"),
    ],
)
def test_classification_stops_before_claiming_any_reservation(
    status: int, url: str, text: str, expected: str
) -> None:
    assert observer().classify(status, url, text) == expected


@pytest.mark.parametrize(
    "status,url,text,expected",
    [
        (200, "https://bocasocios.bocajuniors.com.ar/auth/login", "New heading", None),
        (200, "https://bocasocios.bocajuniors.com.ar/", "New heading", "blocked"),
        (403, "https://bocasocios.bocajuniors.com.ar/auth/login", "New heading", "blocked"),
        (200, "https://bocasocios.bocajuniors.com.ar/auth/login", "Queue-it", "challenge"),
        (200, "https://bocasocios.bocajuniors.com.ar/auth/login", "CAPTCHA", "challenge"),
    ],
)
def test_dom_document_gate_precedes_any_copy_or_form_interpretation(
    status: int, url: str, text: str, expected: str | None
) -> None:
    assert observer().document_gate(status, url, text) == expected


@pytest.mark.parametrize(
    "url,method,kind,expected",
    [
        ("https://bocasocios.bocajuniors.com.ar/_next/static/app.css", "GET", "stylesheet", True),
        ("https://bocasocios.bocajuniors.com.ar/_next/image?width=48", "GET", "image", True),
        ("https://bocasocios.bocajuniors.com.ar/favicon.ico", "GET", "other", True),
        ("https://bocasocios.bocajuniors.com.ar/", "GET", "document", False),
        ("https://bocasocios.bocajuniors.com.ar/_next/static/app.js", "POST", "script", False),
        ("https://assets.other.example/app.css", "GET", "stylesheet", False),
        ("https://bocasocios.bocajuniors.com.ar/queue", "GET", "image", False),
    ],
)
def test_only_same_origin_display_assets_are_expected_discards(
    url: str, method: str, kind: str, expected: bool
) -> None:
    assert observer().expected_discarded_asset(url, method, kind) is expected


def test_opt_in_gate_rejects_arguments_and_disabled_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    module = observer()
    monkeypatch.delenv("BOCA_PUBLIC_OBSERVATION", raising=False)
    assert module.main([]) == 2
    monkeypatch.setenv("BOCA_PUBLIC_OBSERVATION", "one-shot")
    assert module.main(["--url", "https://example.invalid"]) == 2
    assert module.main(["--check-public-login-dom"]) == 2


def test_dom_cli_is_explicit_and_offline_mocked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = observer()
    calls: list[bool] = []

    class AsyncPlaywright:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            pass

    fake_playwright = ModuleType("playwright")
    fake_async_api = ModuleType("playwright.async_api")
    fake_async_api.async_playwright = AsyncPlaywright  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)

    async def fake_observe(_api: object, *, check_dom: bool = False) -> str:
        calls.append(check_dom)
        return "login_form_disabled" if check_dom else "login_visible"

    monkeypatch.setattr(module, "observe", fake_observe)
    monkeypatch.setenv("BOCA_PUBLIC_OBSERVATION", "one-shot")
    monkeypatch.setenv("BOCA_OBSERVER_STOP", "0")

    assert module.main(["--ack-one-public-visit", "--check-public-login-dom"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "mode": "public_login_only",
        "state": "login_form_disabled",
    }
    assert module.main(["--ack-one-public-visit"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "login_visible"
    assert calls == [True, False]

    async def csr_shell(_api: object, *, check_dom: bool = False) -> str:
        assert check_dom
        return "unknown"

    monkeypatch.setattr(module, "observe", csr_shell)
    assert module.main(["--ack-one-public-visit", "--check-public-login-dom"]) == 1
    stopped = capsys.readouterr()
    assert stopped.out == ""
    assert stopped.err == "public_observer_stopped: unknown\n"


@pytest.mark.parametrize(
    "visible_text,form_count,expected",
    [
        ("Ingresá a Boca Socios. Iniciar sesión", 1, "login_form_disabled"),
        ("", 0, "unknown"),  # Next.js CSR shell, JS and assets intentionally disabled.
        ("Bienvenidos a la cuenta del club", 1, "login_form_disabled"),
        ("CAPTCHA", 1, "challenge"),
    ],
    ids=["original_copy", "csr_empty_shell", "copy_changed", "challenge_preempts_dom"],
)
def test_browser_context_closes_on_block_and_never_navigates_again(
    visible_text: str, form_count: int, expected: str
) -> None:
    module = observer()

    class Response:
        status = 200

    class Page:
        url = module.LOGIN_URL

        def __init__(self) -> None:
            self.visits: list[str] = []

        async def goto(self, url: str, **_kwargs: object) -> Response:
            self.visits.append(url)

            class Request:
                method = "GET"

                def __init__(self, target: str, kind: str) -> None:
                    self.url = target
                    self.resource_type = kind

            class Route:
                def __init__(self, target: str, kind: str) -> None:
                    self.request = Request(target, kind)
                    self.fulfilled = False
                    self.aborted = False

                async def fetch(self, *, max_redirects: int, timeout: float) -> Response:
                    assert max_redirects == 0 and timeout == 5_000
                    return Response()

                async def fulfill(self, *, response: Response) -> None:
                    assert response.status == 200
                    self.fulfilled = True

                async def abort(self) -> None:
                    self.aborted = True

            document = Route(url, "document")
            await context.handler(document)
            assert document.fulfilled and not document.aborted
            asset = Route(module.HOME_URL + "_next/static/app.css", "stylesheet")
            await context.handler(asset)
            assert asset.aborted and not asset.fulfilled
            return Response()

        async def inner_text(self, _selector: str) -> str:
            return visible_text

        def locator(self, selector: str) -> object:
            assert visible_text != "CAPTCHA", "challenge must stop before DOM reads"
            selectors = {
                "form",
                'form input[type="email"]',
                'form input[type="password"]',
                'form button[type="submit"], form input[type="submit"]',
            }
            assert selector in selectors

            class Field:
                async def count(self) -> int:
                    return form_count

                async def is_visible(self) -> bool:
                    return True

                async def is_disabled(self) -> bool:
                    return True

            return Field()

    page = Page()

    class Context:
        closed = False

        async def route(self, _pattern: str, handler: object) -> None:
            self.handler = handler

        async def new_page(self) -> Page:
            return page

        async def close(self) -> None:
            self.closed = True

    context = Context()

    class Browser:
        closed = False

        async def new_context(self, **kwargs: object) -> Context:
            assert kwargs == {
                "accept_downloads": False,
                "service_workers": "block",
                "java_script_enabled": False,
            }
            return context

        async def close(self) -> None:
            self.closed = True

    browser = Browser()

    class Chromium:
        async def launch(self, **kwargs: object) -> Browser:
            assert kwargs["chromium_sandbox"] is True
            return browser

    class API:
        chromium = Chromium()

    assert asyncio.run(module.observe(API(), check_dom=True)) == expected
    assert page.visits == [module.LOGIN_URL]
    assert browser.closed and context.closed


@pytest.mark.parametrize(
    "form_count,email_count,password_count,button_count,disabled,visible,expected",
    [
        (1, 1, 1, 1, True, True, True),
        (0, 0, 0, 0, False, False, False),  # Next.js shell lacking server-rendered inputs.
        (2, 1, 1, 1, True, True, False),
        (1, 0, 1, 1, True, True, False),
        (1, 1, 0, 1, True, True, False),
        (1, 2, 1, 1, True, True, False),
        (1, 1, 1, 2, True, True, False),
        (1, 1, 1, 1, False, True, False),
        (1, 1, 1, 1, True, False, False),  # Hidden controls cannot prove visible login.
    ],
)
def test_login_dom_inspection_is_read_only_and_fails_closed(
    form_count: int,
    email_count: int,
    password_count: int,
    button_count: int,
    disabled: bool,
    visible: bool,
    expected: bool,
) -> None:
    module = observer()
    read_methods: list[str] = []

    class Field:
        def __init__(self, label: str, count: int) -> None:
            self.label = label
            self.count_value = count

        async def count(self) -> int:
            read_methods.append(f"count:{self.label}")
            return self.count_value

        async def is_visible(self) -> bool:
            read_methods.append(f"is_visible:{self.label}")
            return visible

        async def is_disabled(self) -> bool:
            read_methods.append("is_disabled:login")
            return disabled

    class Page:
        def locator(self, selector: str) -> Field:
            mapping = {
                "form": Field("form", form_count),
                'form input[type="email"]': Field("email", email_count),
                'form input[type="password"]': Field("password", password_count),
                'form button[type="submit"], form input[type="submit"]': Field(
                    "login", button_count
                ),
            }
            return mapping[selector]

    assert asyncio.run(module.inspect_login_dom(Page())) is expected
    assert all(
        method.startswith(("count:", "is_visible:", "is_disabled:")) for method in read_methods
    )
    assert not any(method.startswith("is_disabled:") for method in read_methods) or (
        form_count == 1 and button_count == 1 and email_count == 1 and password_count == 1
    )


def test_redirect_response_is_aborted_without_followup_navigation() -> None:
    module = observer()
    requests: list[str] = []

    class Route:
        class Request:
            url = module.LOGIN_URL
            method = "GET"
            resource_type = "document"

        request = Request()
        aborted = False

        async def fetch(self, *, max_redirects: int, timeout: float) -> object:
            assert max_redirects == 0 and timeout == 5_000
            requests.append(self.request.url)

            class Redirect:
                status = 302

            return Redirect()

        async def abort(self) -> None:
            self.aborted = True

        async def fulfill(self, **_kwargs: object) -> None:
            raise AssertionError("redirect must not be served to Chromium")

    route = Route()

    class Page:
        url = module.LOGIN_URL

        async def goto(self, _url: str, **_kwargs: object) -> None:
            await context.handler(route)
            return None

    class Context:
        async def route(self, _pattern: str, handler: object) -> None:
            self.handler = handler

        async def new_page(self) -> Page:
            return Page()

        async def close(self) -> None:
            pass

    context = Context()

    class Browser:
        async def new_context(self, **_kwargs: object) -> Context:
            return context

        async def close(self) -> None:
            pass

    class Chromium:
        async def launch(self, **_kwargs: object) -> Browser:
            return Browser()

    class API:
        chromium = Chromium()

    assert asyncio.run(module.observe(API())) == "blocked"
    assert route.aborted
    assert requests == [module.LOGIN_URL]


@pytest.mark.parametrize(
    "url,method,kind",
    [
        ("https://bocasocios.bocajuniors.com.ar/", "GET", "document"),
        ("https://bocasocios.bocajuniors.com.ar/auth/login", "GET", "document"),
        ("https://bocasocios.bocajuniors.com.ar/auth/login", "POST", "fetch"),
        ("https://assets.other.example/app.css", "GET", "stylesheet"),
    ],
)
def test_second_navigation_post_and_foreign_domain_stop_observation(
    url: str, method: str, kind: str
) -> None:
    module = observer()
    fetched: list[str] = []

    class Response:
        status = 200

    class Route:
        def __init__(self, target: str, verb: str, resource: str) -> None:
            self.request = type(
                "Request", (), {"url": target, "method": verb, "resource_type": resource}
            )()
            self.aborted = False

        async def fetch(self, *, max_redirects: int, timeout: float) -> Response:
            fetched.append(self.request.url)
            return Response()

        async def fulfill(self, *, response: Response) -> None:
            assert response.status == 200

        async def abort(self) -> None:
            self.aborted = True

    class Page:
        url = module.LOGIN_URL

        async def goto(self, _url: str, **_kwargs: object) -> Response:
            await context.handler(Route(module.LOGIN_URL, "GET", "document"))
            unsafe = Route(url, method, kind)
            await context.handler(unsafe)
            assert unsafe.aborted
            return Response()

        async def inner_text(self, _selector: str) -> str:
            return "Ingresá a Boca Socios. Iniciar sesión"

    class Context:
        async def route(self, _pattern: str, handler: object) -> None:
            self.handler = handler

        async def new_page(self) -> Page:
            return Page()

        async def close(self) -> None:
            pass

    context = Context()

    class Browser:
        async def new_context(self, **_kwargs: object) -> Context:
            return context

        async def close(self) -> None:
            pass

    class Chromium:
        async def launch(self, **_kwargs: object) -> Browser:
            return Browser()

    class API:
        chromium = Chromium()

    assert asyncio.run(module.observe(API())) == "blocked"
    assert fetched == [module.LOGIN_URL]
