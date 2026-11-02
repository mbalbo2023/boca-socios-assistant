"""No-network regressions for the approved capture and private byte boundary."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import signal
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "boca_capture_scripts",
    ROOT / "scripts/__init__.py",
    submodule_search_locations=[str(ROOT / "scripts")],
)
assert SPEC and SPEC.loader
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)
from boca_capture_scripts import public_observer_bundle as bundle  # noqa: E402
from boca_capture_scripts import public_observer_capture as capture  # noqa: E402
from boca_capture_scripts import public_observer_render as render  # noqa: E402


def html(extra: str = "") -> bytes:
    refs = "".join(
        f'<script src="{path}"></script>'
        if path.endswith(".js")
        else f'<link href="{path}" rel="preload">'
        for path in bundle.ASSETS
    )
    return (f"<!doctype html><html><body>{refs}{extra}</body></html>").encode()


def test_exact_raw_inventory_rejects_changed_or_sensitive_urls() -> None:
    assert set(bundle.inventory(html())) == set(bundle.ASSETS)
    for extra in (
        '<img src="/new.png">',
        '<img src="//evil.invalid/x">',
        '<base href="/">',
        '<meta http-equiv="refresh" content="0;url=/">',
        '<img srcset="/new.png 2x">',
    ):
        with pytest.raises(ValueError):
            bundle.inventory(html(extra))
    for suffix in ("?secret=yes", "#fragment", "?", "#"):
        changed = html().replace(
            next(iter(bundle.ASSETS)).encode(), (next(iter(bundle.ASSETS)) + suffix).encode(), 1
        )
        with pytest.raises(ValueError):
            bundle.inventory(changed)
    with pytest.raises(ValueError):
        bundle.inventory(b"<html>captcha</html>")


def test_bundle_revalidates_content_paths_counts_sizes_and_hashes() -> None:
    value = bundle.fixture_bundle()
    encoded = bundle.encode_bundle(value)
    assert bundle.decode_bundle(io.BytesIO(encoded), fixture=True) == value
    with pytest.raises(ValueError):
        bundle.decode_bundle(io.BytesIO(encoded), fixture=False)
    for key, bad in (
        ("path", "/new"),
        ("sha256", "0" * 64),
        ("body", "%%%"),
        ("headers", {"Set-Cookie": "private"}),
    ):
        changed = json.loads(encoded)
        changed["entries"][0][key] = bad
        with pytest.raises(ValueError):
            bundle.decode_bundle(io.BytesIO(json.dumps(changed).encode()), fixture=True)


def test_capture_rejects_redirect_cookie_reuse_and_stream_overflow() -> None:
    class Response:
        status = 302
        headers = {"Content-Type": "text/html", "Set-Cookie": "private"}

        def getheader(self, name: str, default: str = "") -> str:
            return self.headers.get(name, default)

        def read(self, size: int) -> bytes:
            return b"x" * size

    with pytest.raises(ValueError):
        capture.read_response(Response(), bundle.LOGIN_PATH, 100)
    Response.status = 200
    with pytest.raises(ValueError):
        capture.read_response(Response(), bundle.LOGIN_PATH, 100)


def test_capture_wire_headers_have_no_cookie_authorization_or_compression() -> None:
    assert capture.REQUEST_HEADERS == {
        "Host": bundle.HOST,
        "Connection": "close",
        "Accept-Encoding": "identity",
        "User-Agent": "BocaSociosPublicDiagnostic/1.0",
        "Accept": "*/*",
    }
    assert capture.request_budget(119, 120) == 1
    assert capture.request_budget(1, 120) == 8
    with pytest.raises(TimeoutError):
        capture.request_budget(120, 120)


def test_trusted_http_client_uses_fresh_verified_tunnel_without_redirect_or_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Connection:
        def __init__(self, host: str, port: int, *, timeout: float, context: object) -> None:
            assert host == "172.18.0.3" and port == 18080 and timeout == 8
            assert context.check_hostname and context.verify_mode == 2

        def set_tunnel(self, host: str, port: int) -> None:
            calls.append(("tunnel", host, port))

        def request(self, method: str, path: str, *, headers: dict) -> None:
            calls.append((method, path, headers))
            raise OSError("no network fixture")

        def close(self) -> None:
            calls.append(("close",))

    monkeypatch.setattr(capture.http.client, "HTTPSConnection", Connection)
    with pytest.raises(OSError):
        capture.fetch(bundle.LOGIN_PATH, "172.18.0.3", 8, 1024)
    assert calls == [
        ("tunnel", bundle.HOST, 443),
        ("GET", bundle.LOGIN_PATH, capture.REQUEST_HEADERS),
        ("close",),
    ]


def test_capture_serial_spacing_exact_paths_counters_and_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    attempts = []
    finishes = []
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        capture.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(
        bundle, "save_bundle", lambda value, **kwargs: bundle.validate_bundle(value, fixture=False)
    )
    monkeypatch.setattr(
        capture, "finish_proxy", lambda address, count: finishes.append((address, count))
    )

    def fetch(path: str, _proxy: str, timeout: float, _remaining: int) -> bytes:
        attempts.append((path, clock[0], timeout))
        return html() if path == bundle.LOGIN_PATH else b"fixture"

    monkeypatch.setattr(capture, "fetch", fetch)
    receipt = {"http_get_attempts": 0, "completed": []}
    assert capture.capture("172.18.0.3", receipt)["mode"] == "public_capture"
    assert [item[0] for item in attempts] == [bundle.LOGIN_PATH, *bundle.ASSETS]
    assert all(
        second[1] - first[1] >= 0.5 for first, second in zip(attempts, attempts[1:], strict=False)
    )
    assert receipt["http_get_attempts"] == len(receipt["completed"]) == 25
    assert finishes == [("172.18.0.3", 25)]


def test_total_capture_deadline_stops_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        capture.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    def fetch(path: str, *_args: object) -> bytes:
        clock[0] += 8
        return html() if path == bundle.LOGIN_PATH else b"fixture"

    monkeypatch.setattr(capture, "fetch", fetch)
    receipt = {"http_get_attempts": 0, "completed": []}
    with pytest.raises(TimeoutError):
        capture.capture("172.18.0.3", receipt)
    assert receipt["http_get_attempts"] == 15
    assert clock[0] == 120


def test_streaming_body_cannot_extend_wall_clock_alarm() -> None:
    class Streaming:
        status = 200

        def getheader(self, name: str, default: str = "") -> str:
            return "text/html" if name == "Content-Type" else default

        def read(self, _size: int) -> bytes:
            time.sleep(0.02)
            return b"x"

    previous = signal.signal(signal.SIGALRM, capture.alarm)
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.03)
        with pytest.raises(TimeoutError):
            capture.read_response(Streaming(), bundle.LOGIN_PATH, 1024)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize(
    "url,method,kind,headers",
    [
        (bundle.ORIGIN + bundle.LOGIN_PATH, "POST", "document", {}),
        (bundle.ORIGIN + bundle.ASSETS[7], "GET", "fetch", {}),
        (bundle.ORIGIN + bundle.ASSETS[7], "GET", "xhr", {}),
        (bundle.ORIGIN + bundle.ASSETS[7], "GET", "script", {"Cookie": "private"}),
        (bundle.ORIGIN + bundle.ASSETS[7] + "?private=yes", "GET", "script", {}),
        (bundle.ORIGIN + "/favicon.ico", "GET", "other", {}),
        ("https://evil.invalid/x.js", "GET", "script", {}),
        ("data:text/html,fixture", "GET", "document", {}),
    ],
)
def test_renderer_refuses_any_dynamic_or_unmapped_request(url, method, kind, headers) -> None:
    guard = render.RenderGuard(bundle.fixture_bundle())
    assert guard.allow(url, method, kind, headers) is None
    assert guard.blocked


def test_renderer_document_once_and_maximum_64_responses() -> None:
    guard = render.RenderGuard(bundle.fixture_bundle())
    assert guard.allow(bundle.ORIGIN + bundle.LOGIN_PATH, "GET", "document", {})
    assert guard.allow(bundle.ORIGIN + bundle.LOGIN_PATH, "GET", "document", {}) is None
    guard = render.RenderGuard(bundle.fixture_bundle())
    for _ in range(64):
        assert guard.allow(bundle.ORIGIN + bundle.ASSETS[7], "GET", "script", {})
    assert guard.allow(bundle.ORIGIN + bundle.ASSETS[7], "GET", "script", {}) is None
    assert guard.reason == "request_budget"


def test_denied_navigation_identifies_only_sanitized_cause_and_separates_prior_stop() -> None:
    guard = render.RenderGuard(bundle.fixture_bundle())
    url = bundle.ORIGIN + "/favicon.ico?token=fixture-secret#private-fragment"
    assert guard.allow(url, "GET", "document", {}) is None
    assert guard.reason == "resource_outside_map"
    diagnostic = guard.diagnostics()
    assert diagnostic["denied_requests"] == [
        {
            "cause": "resource_outside_map",
            "method": "GET",
            "kind": "document",
            "same_origin": True,
            "path": "/favicon.ico",
            "path_class": "known",
            "query_redacted": True,
            "fragment_redacted": True,
            "userinfo_redacted": False,
            "scheme": "https",
            "authority": bundle.HOST,
            "host_kind": "dns_syntax",
        }
    ]
    # A request aborted because the guard already stopped is not a newly
    # discovered dependency, even when its URL itself is outside the map.
    assert guard.allow(bundle.ORIGIN + bundle.ASSETS[0], "GET", "stylesheet", {}) is None
    assert guard.allow(bundle.ORIGIN + "/second-unknown", "GET", "image", {}) is None
    guard.stop("resource_failure")  # requestfailed emitted by our own abort
    assert guard.reason == "resource_outside_map"
    assert guard.diagnostics()["denied_requests"] == diagnostic["denied_requests"]
    assert guard.diagnostics()["cancelled_after_stop"] == 2
    assert "fixture-secret" not in json.dumps(guard.diagnostics())
    assert "private-fragment" not in json.dumps(guard.diagnostics())


@pytest.mark.parametrize(
    "url",
    [
        bundle.ORIGIN + "/account/fixture-secret/avatar.png?token=fixture-secret#fixture-secret",
        "https://person:fixture-secret@" + bundle.HOST + "/favicon.ico?fixture-secret",
        "https://external.invalid/fixture-secret?fixture-secret#fixture-secret",
        bundle.ORIGIN + "/_next/static/chunks/fixture-secret-0123456789abcdef.js",
        bundle.ORIGIN + "/_next/static/chunks/1234-0123456789abcdef.js%3Ffixture-secret",
        "data:text/plain,fixture-secret",
        "blob:" + bundle.ORIGIN + "/fixture-secret",
        bundle.ORIGIN + "/fixture-secret" * 1000,
    ],
)
def test_denied_metadata_never_exports_arbitrary_paths_userinfo_or_values(url: str) -> None:
    value = render.denied_metadata(url, "fixture-secret", "fixture-secret", "resource_outside_map")
    assert value["path"] is None
    assert "fixture-secret" not in json.dumps(value)
    assert value["method"] == "OTHER" and value["kind"] == "other"


def test_safe_static_diagnostic_identity_never_expands_the_render_map() -> None:
    path = "/_next/static/chunks/1234-0123456789abcdef.js"
    guard = render.RenderGuard(bundle.fixture_bundle())
    assert guard.allow(bundle.ORIGIN + path, "GET", "script", {}) is None
    assert guard.reason == "resource_outside_map"
    assert guard.diagnostics()["denied_requests"][0]["path"] == path
    assert guard.diagnostics()["denied_requests"][0]["path_class"] == "next_static"


def test_denied_authority_exposes_only_canonical_host_and_port_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("diagnostic must not resolve a host")

    monkeypatch.setattr(render.socket, "getaddrinfo", forbidden_lookup)
    value = render.authority_metadata(
        "https://fixture-user:fixture-secret@CDN.Example.org:443/private-path?secret=yes#private"
    )
    assert value == {
        "scheme": "https",
        "authority": "cdn.example.org:443",
        "host_kind": "dns_syntax",
    }
    assert all(
        secret not in json.dumps(value)
        for secret in ("fixture-user", "fixture-secret", "private", "secret=yes")
    )
    assert render.authority_metadata("wss://cdn.example.org./x") == {
        "scheme": "wss",
        "authority": "cdn.example.org",
        "host_kind": "dns_syntax",
    }


@pytest.mark.parametrize(
    "authority",
    [
        "localhost",
        "host.local",
        "host.internal",
        "host.home.arpa",
        "host.invalid",
        "host.test",
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "192.0.2.1",
        "224.0.0.1",
        "0.0.0.0",  # noqa: S104 - rejected metadata fixture, no bind or network call
        "[::1]",
        "[fe80::1]",
        "[ff02::1]",
        "[2001:db8::1]",
        "[::ffff:127.0.0.1]",
        "[2001:4860:4860::8888%eth0]",
        "127.1",
        "2130706433",
        "0x7f000001",
        "0177.0.0.1",
        "0x7f.0.0.1",
        "example.0x1",
        "cdn.example.org:0",
        "cdn.example.org:65536",
        "cdn.example.org:",
        "cdn.example.org:00443",
        "cdn.example.org:443:80",
        "cdn%2eexample.org",
        "cdn.example.org\\@example.net",
        "a@b@cdn.example.org",
        "cdn.example.org\r\nX-Header:private",
        "cdn.example.org\x7f",
        "cdñ.example.org",
        "-cdn.example.org",
        "cdn-.example.org",
        "cdn..example.org",
        "a" * 64 + ".example.org",
        ".".join(["a" * 63] * 4),
    ],
)
def test_denied_authority_redacts_nonpublic_ambiguous_or_malformed_hosts(authority: str) -> None:
    value = render.authority_metadata("https://" + authority + "/private?token=private#private")
    assert value["authority"] is None and value["host_kind"] == "redacted"
    assert "private" not in json.dumps(value)


@pytest.mark.parametrize(
    "url,authority,kind",
    [
        ("https://8.8.8.8/x", "8.8.8.8", "global_ipv4"),
        ("https://[2001:4860:4860::8888]:8443/x", "[2001:4860:4860::8888]:8443", "global_ipv6"),
        ("https://xn--bcher-kva.example.org/x", "xn--bcher-kva.example.org", "dns_syntax"),
        (
            "https://bocasocios-gw.bocajuniors.com.ar/x",
            "bocasocios-gw.bocajuniors.com.ar",
            "dns_syntax",
        ),
        (
            "https://bocasocios.bocajuniors.com.ar.evil.com/x",
            "bocasocios.bocajuniors.com.ar.evil.com",
            "dns_syntax",
        ),
        ("http://bocasocios.bocajuniors.com.ar/x", "bocasocios.bocajuniors.com.ar", "dns_syntax"),
    ],
)
def test_denied_authority_classification_is_syntax_not_destination_permission(
    url: str, authority: str, kind: str
) -> None:
    guard = render.RenderGuard(bundle.fixture_bundle())
    assert guard.allow(url, "GET", "script", {}) is None
    denial = guard.diagnostics()["denied_requests"][0]
    assert denial["authority"] == authority and denial["host_kind"] == kind
    assert guard.reason == "resource_outside_map" and denial["same_origin"] is False
    assert render.valid_diagnostics(guard.diagnostics())


def test_denied_authority_supervisor_revalidates_framing_types_and_origin() -> None:
    good = render.denied_metadata(
        "https://cdn.example.org/script?private", "GET", "script", "resource_outside_map"
    )
    assert render.valid_diagnostics({"denied_requests": [good], "cancelled_after_stop": 0})
    for field, value in (
        ("authority", "user:private@cdn.example.org"),
        ("authority", "cdn.example.org/private?secret#private"),
        ("authority", "CDN.EXAMPLE.ORG"),
        ("authority", "127.1"),
        ("authority", "cdn.example.org:00443"),
        ("authority", ["cdn.example.org"]),
        ("scheme", "javascript"),
        ("scheme", True),
        ("host_kind", "public_dns"),
        ("host_kind", "global_ipv4"),
        ("same_origin", True),
    ):
        assert not render.valid_diagnostics(
            {"denied_requests": [{**good, field: value}], "cancelled_after_stop": 0}
        )
    long_host = ".".join(["a" * 63] * 3 + ["a" * 61])
    item = render.denied_metadata(
        "https://" + long_host + ":65535/x", "GET", "script", "resource_outside_map"
    )
    value = {"denied_requests": [item] * 8, "cancelled_after_stop": 0}
    assert len(json.dumps(value, separators=(",", ":")).encode("ascii")) > 4096
    assert not render.valid_diagnostics(value)


def test_supervisor_rejects_diagnostic_schema_privacy_and_size_violations() -> None:
    item = render.denied_metadata(
        bundle.ORIGIN + "/favicon.ico?private", "GET", "document", "resource_outside_map"
    )
    good = {"denied_requests": [item], "cancelled_after_stop": 0}
    assert render.valid_diagnostics(good)
    for field, value in (
        ("query_redacted", 1),
        ("same_origin", "true"),
        ("path", "/account/fixture-secret"),
        ("method", "fixture-secret"),
        ("kind", "fixture-secret"),
        ("headers", {"Cookie": "fixture-secret"}),
    ):
        bad = {"denied_requests": [{**item, field: value}], "cancelled_after_stop": 0}
        assert not render.valid_diagnostics(bad)
    assert not render.valid_diagnostics({"denied_requests": [item] * 9, "cancelled_after_stop": 0})
    assert not render.valid_diagnostics({"denied_requests": [item], "cancelled_after_stop": True})
    assert not render.valid_diagnostics(
        {"denied_requests": [{**item, "path": "/" + "x" * 4096}], "cancelled_after_stop": 0}
    )


def test_late_browser_cleanup_failure_invalidates_provisional_dom(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        bundle, "open_bundle", lambda: io.BytesIO(bundle.encode_bundle(bundle.fixture_bundle()))
    )

    async def late_error(_value: dict, receipt: dict) -> None:
        receipt.update(state="DOM_OBSERVED", blocked_reason="none")
        raise RuntimeError("close failed")

    monkeypatch.setattr(render, "render", late_error)
    assert render.child(True) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["state"] == "UNKNOWN" and receipt["blocked_reason"] == "runtime_failure"
    assert receipt["connected_site"] is False


def test_private_bundle_refuses_symlink_and_removes_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "private"
    monkeypatch.setattr(bundle, "PRIVATE_DIR", private)
    monkeypatch.setattr(bundle, "BUNDLE_PATH", private / "bundle.json")
    bundle.save_bundle(bundle.fixture_bundle(), fixture=True)
    assert private.stat().st_mode & 0o777 == 0o700
    assert bundle.BUNDLE_PATH.stat().st_mode & 0o777 == 0o600
    with bundle.open_bundle() as stream:
        assert bundle.decode_bundle(stream, fixture=True)["mode"] == "synthetic_fixture"
    bundle.remove_bundle()
    assert not private.exists()
    private.mkdir(mode=0o700)
    bundle.BUNDLE_PATH.symlink_to(tmp_path / "unrelated")
    with pytest.raises(OSError):
        bundle.open_bundle()


@pytest.mark.parametrize(
    "text,worker,denied,close_error,expected",
    [
        ("Public login", False, False, False, "DOM_OBSERVED"),
        ("captcha", False, False, False, "UNKNOWN"),
        ("Public login", True, False, False, "UNKNOWN"),
        ("Public login", False, True, False, "UNKNOWN"),
        ("Public login", False, True, True, "UNKNOWN"),
    ],
)
def test_renderer_runs_full_adapter_and_challenge_gate_without_network(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    worker: bool,
    denied: bool,
    close_error: bool,
    expected: str,
) -> None:
    fulfilled = []
    closed = []

    class Route:
        request = SimpleNamespace(
            url=bundle.ORIGIN
            + ("/favicon.ico?token=fixture-secret" if denied else bundle.LOGIN_PATH),
            method="GET",
            resource_type="document",
            headers={},
        )

        async def abort(self) -> None:
            assert denied, "positive document must use captured bytes"
            page.handlers["requestfailed"](None)

        async def fulfill(self, **kwargs) -> None:
            fulfilled.append(kwargs)

    class Page:
        main_frame = object()
        handlers = {}

        def on(self, event, handler) -> None:
            self.handlers[event] = handler

        async def goto(self, url, **_kwargs) -> None:
            assert url == bundle.ORIGIN + bundle.LOGIN_PATH
            await context.handler(Route())
            if denied:
                secondary = Route()
                secondary.request = SimpleNamespace(
                    url=bundle.ORIGIN + bundle.ASSETS[0],
                    method="GET",
                    resource_type="stylesheet",
                    headers={},
                )
                await context.handler(secondary)
            if worker:
                self.handlers["worker"](None)

        async def inner_text(self, selector) -> str:
            assert selector == "body"
            return text

    page = Page()

    class Context:
        async def route(self, pattern, handler) -> None:
            assert pattern == "**/*"
            self.handler = handler

        async def route_web_socket(self, pattern, handler) -> None:
            assert pattern == "**/*" and handler

        async def new_page(self) -> Page:
            return page

        def on(self, *_args) -> None:
            pass

        async def cookies(self) -> list:
            return []

        async def close(self) -> None:
            closed.append("context")
            if close_error:
                raise RuntimeError("synthetic close failure")

    context = Context()

    class Browser:
        async def new_context(self, **kwargs) -> Context:
            assert kwargs == {
                "accept_downloads": False,
                "service_workers": "block",
                "java_script_enabled": True,
            }
            return context

        async def close(self) -> None:
            closed.append("browser")

    class API:
        async def __aenter__(self):
            self.chromium = self
            return self

        async def __aexit__(self, *_args) -> None:
            closed.append("playwright")

        async def launch(self, **kwargs) -> Browser:
            assert kwargs["chromium_sandbox"] is True
            return Browser()

    module = ModuleType("playwright.async_api")
    module.async_playwright = API
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    monkeypatch.setattr(render, "require_network_none", lambda: None)
    times = iter([0, 15])
    monkeypatch.setattr(render, "time", SimpleNamespace(monotonic=lambda: next(times)))

    async def inspect(_page) -> bool:
        return True

    monkeypatch.setattr(render, "inspect_rendered_login_dom", inspect)
    receipt = {}
    if close_error:
        with pytest.raises(RuntimeError):
            asyncio.run(render.render(bundle.fixture_bundle(), receipt))
    else:
        asyncio.run(render.render(bundle.fixture_bundle(), receipt))
    assert receipt["state"] == expected
    assert closed == (
        ["context", "context", "browser", "playwright"]
        if close_error
        else ["context", "browser", "playwright"]
    )
    if denied:
        assert not fulfilled
        assert receipt["blocked_reason"] == "resource_outside_map"
        assert receipt["diagnostics"]["cancelled_after_stop"] == 1
        assert receipt["diagnostics"]["denied_requests"][0]["path"] == "/favicon.ico"
        assert "fixture-secret" not in json.dumps(receipt)
        return
    assert len(fulfilled) == 1
    assert fulfilled[0]["headers"] == {
        "Content-Type": "text/html",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    assert b"fixture-root" in fulfilled[0]["body"]


@pytest.mark.parametrize(
    "state,cancelled,cause",
    [
        ("DOM_OBSERVED", 0, "resource_outside_map"),
        ("DOM_OBSERVED", 1, None),
        ("UNKNOWN", 0, "resource_outside_map"),
    ],
)
def test_supervisor_refuses_positive_or_inconsistent_denial_receipts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: str,
    cancelled: int,
    cause: str | None,
) -> None:
    item = render.denied_metadata(
        bundle.ORIGIN + "/favicon.ico?private", "GET", "document", "resource_outside_map"
    )
    child_value = {
        "mode": "offline_capture_render",
        "state": state,
        "connected_site": False,
        "provenance": "synthetic_fixture",
        "internal_requests": 2,
        "blocked_reason": "none",
        "diagnostics": {
            "denied_requests": [item] if cause else [],
            "cancelled_after_stop": cancelled,
        },
    }
    monkeypatch.setattr(render.sys, "argv", ["render", "--fixture-render"])
    monkeypatch.setattr(render, "require_network_none", lambda: None)
    monkeypatch.setattr(bundle, "save_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bundle, "remove_bundle", lambda: None)
    monkeypatch.setattr(render.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(render.signal, "setitimer", lambda *_args: None)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(child_value), returncode=0),
    )
    assert render.main() == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["state"] == "UNKNOWN"
    assert receipt["diagnostics"] == {"denied_requests": [], "cancelled_after_stop": 0}
    assert "private" not in json.dumps(receipt)


def test_many_post_stop_cancellations_preserve_causal_diagnostic_through_supervisor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    guard = render.RenderGuard(bundle.fixture_bundle())
    assert (
        guard.allow(bundle.ORIGIN + "/favicon.ico?token=fixture-secret", "GET", "document", {})
        is None
    )
    for _ in range(70):
        assert guard.allow(bundle.ORIGIN + bundle.ASSETS[0], "GET", "stylesheet", {}) is None
    assert guard.requests == 1
    assert guard.cancelled_after_stop == 70
    value = {
        "mode": "offline_capture_render",
        "state": "UNKNOWN",
        "connected_site": False,
        "provenance": "synthetic_fixture",
        "internal_requests": guard.requests,
        "blocked_reason": guard.reason,
        "diagnostics": guard.diagnostics(),
    }
    monkeypatch.setattr(render.sys, "argv", ["render", "--fixture-render"])
    monkeypatch.setattr(render, "require_network_none", lambda: None)
    monkeypatch.setattr(bundle, "save_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bundle, "remove_bundle", lambda: None)
    monkeypatch.setattr(render.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(render.signal, "setitimer", lambda *_args: None)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(value), returncode=1),
    )
    assert render.main() == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["state"] == "UNKNOWN" and receipt["blocked_reason"] == "resource_outside_map"
    assert receipt["diagnostics"]["cancelled_after_stop"] == 70
    assert receipt["diagnostics"]["denied_requests"][0]["path"] == "/favicon.ico"
    assert "fixture-secret" not in json.dumps(receipt)
