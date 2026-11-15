"""Offline visual evidence must stay tied to fixed fixtures and the candidate SHA."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
import struct
import sys
import types
import zlib
from urllib.parse import urlencode

import pytest

SOURCE_SHA = "a" * 40


def _module():
    from scripts import run_engine_dashboard_ui_offline_chromium

    return run_engine_dashboard_ui_offline_chromium


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\xff\xff" * width) * height))
        + chunk(b"IEND", b"")
    )


def _capture(module, fixture):
    return {
        "schema": 1,
        "mode": "OFFLINE_SYNTHETIC_ENGINE_UI",
        "source_sha": SOURCE_SHA,
        "fixture_sha256": module.fixture_digest(fixture),
        "state": "PASS",
        "network": "none",
        "host_checked": False,
        "physical_device_checked": False,
        "viewports": [
            {
                "width": width,
                "height": height,
                "document_requests": 1,
                "snapshot_requests": 4,
                "native_posts": list(module.POST_ORDER),
                "other_requests": 0,
                "page_errors": 0,
                "checks": dict.fromkeys(module.CHECKS, True),
                "png_base64": base64.b64encode(_png(width, height)).decode("ascii"),
            }
            for width, height, _ in module.VIEWPORTS
        ],
    }


def test_fixed_fixture_uses_actual_renderer_and_ignores_runtime_environment(monkeypatch):
    module = _module()
    from boca_socios.panel import engine_view

    rendered = []
    original = engine_view.page

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        rendered.append(result)
        return result

    monkeypatch.setattr(engine_view, "page", record)
    fixture = module.make_fixture(SOURCE_SHA)
    monkeypatch.setenv("BOCA_DB_PATH", "/must-not-open/runtime.sqlite3")
    monkeypatch.setenv("BOCA_SITE_URL", "https://must-not-contact.invalid/private")
    monkeypatch.setenv("BOCA_OWNER_SUBJECT", "must-not-appear-in-artifact")
    assert module.make_fixture(SOURCE_SHA) == fixture
    assert fixture["html"] == rendered[0].decode("utf-8")
    assert fixture["csp"] == engine_view.csp()
    assert fixture["html_sha256"] == hashlib.sha256(rendered[0]).hexdigest()
    assert "must-not-" not in json.dumps(fixture)
    module.validate_fixture(fixture, SOURCE_SHA)


@pytest.mark.parametrize("change", ["source", "token", "url", "html", "extra"])
def test_fixture_rejects_source_drift_private_metadata_and_unreviewed_inputs(change):
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    if change == "source":
        fixture["source_sha"] = "b" * 40
    elif change == "token":
        fixture["snapshots"][1]["engines"][0]["sessions"][0]["access_token"] = "forbidden"
    elif change == "url":
        fixture["snapshots"][1]["engines"][0]["sessions"][0]["display_url"] += "?pass=forbidden"
    elif change == "html":
        fixture["html"] += "<p>unexpected</p>"
    else:
        fixture["database"] = "/runtime.sqlite3"
    with pytest.raises(ValueError):
        module.validate_fixture(fixture, SOURCE_SHA)


def test_native_post_requires_exact_origin_fields_and_engine_fence():
    module = _module()
    for operation in module.POST_ORDER:
        url = module.post_url(operation)
        fields = module.expected_post_fields(operation)
        assert module.verify_post(url, module.ORIGIN, urlencode(fields)) == operation
        for origin in (None, "null", "https://other.invalid", module.ORIGIN + "/"):
            with pytest.raises(ValueError):
                module.verify_post(url, origin, urlencode(fields))
        with pytest.raises(ValueError):
            module.verify_post(url, module.ORIGIN, urlencode(fields) + "&csrf=duplicate")
        with pytest.raises(ValueError):
            module.verify_post(url + "?unexpected=1", module.ORIGIN, urlencode(fields))

    fields = module.expected_post_fields("queues_tokens:stop")
    other = module.expected_post_fields("browsers_members:stop")
    fields["activation_id"] = other["activation_id"]
    with pytest.raises(ValueError):
        module.verify_post(module.post_url("queues_tokens:stop"), module.ORIGIN, urlencode(fields))
    fields = module.expected_post_fields("browsers_members:start")
    fields.pop("member_id")
    with pytest.raises(ValueError):
        module.verify_post(
            module.post_url("browsers_members:start"), module.ORIGIN, urlencode(fields)
        )


def test_page_error_callback_accepts_playwright_wrapper_cache_before_navigation():
    """Playwright 1.64.1 caches its wrapper on non-method callback objects."""
    module = _module()

    class StopBeforeNavigation(Exception):
        pass

    class Page:
        def on(self, event, callback):
            assert event == "pageerror"
            assert not inspect.ismethod(callback)
            # The pinned mapper caches its wrapper on functions and built-ins.
            # list.append is a built-in and cannot hold this attribute.
            callback._pw_impl_instance_ = object()
            self.callback = callback

        async def goto(self, *args, **kwargs):
            self.callback(RuntimeError("fixed offline page error"))
            raise StopBeforeNavigation

    class Context:
        closed = False

        def set_default_timeout(self, timeout):
            assert timeout == 5000

        async def route(self, *_args):
            pass

        async def new_page(self):
            return Page()

        async def close(self):
            self.closed = True

    context = Context()

    class Browser:
        async def new_context(self, **_kwargs):
            return context

    with pytest.raises(StopBeforeNavigation):
        asyncio.run(module._viewport(Browser(), module.make_fixture(SOURCE_SHA), 800, 1280))
    assert context.closed


class _InertViewportBrowser:
    """Only the browser boundary is inert; routing and proof steps stay real."""

    def __init__(self, module, fault, error, close_error=None):
        self.module = module
        self.fault = fault
        self.error = error
        self.close_error = close_error
        self.closed = False
        self.waits = 0
        self.pending_post = False
        self.url = module.PAGE_URL

    async def new_context(self, **kwargs):
        assert kwargs == {
            "accept_downloads": False,
            "service_workers": "block",
            "viewport": {"width": 800, "height": 1280},
        }
        if self.fault == "context_create":
            raise self.error
        return self

    def set_default_timeout(self, timeout):
        assert timeout == 5000

    async def route(self, pattern, handler):
        assert pattern == "**/*"
        self.handler = handler

    async def new_page(self):
        return self

    def on(self, event, callback):
        assert event == "pageerror"
        self.page_error = callback

    async def dispatch(self, url, *, method="GET", headers=None, body=None):
        async def all_headers():
            return headers or {}

        async def fulfill(**_kwargs):
            pass

        async def abort():
            pass

        request = types.SimpleNamespace(
            url=url,
            method=method,
            resource_type="document",
            is_navigation_request=lambda: True,
            all_headers=all_headers,
            post_data=body,
        )
        await self.handler(types.SimpleNamespace(request=request, fulfill=fulfill, abort=abort))

    async def goto(self, url, **kwargs):
        assert url == self.module.PAGE_URL
        assert kwargs == {"wait_until": "load", "timeout": 10_000}
        await self.dispatch(url)
        if self.fault == "document_load":
            raise self.error
        await self.dispatch(self.module.SNAPSHOT_URL)
        self.page_error(RuntimeError("private-page-error-must-not-be-logged"))

    async def wait_for_function(self, _expression):
        self.waits += 1
        if (self.fault, self.waits) in {("initial_timestamp", 1), ("initial_live_poll", 2)}:
            raise self.error

    def locator(self, selector):
        browser = self

        class Locator:
            async def is_disabled(self):
                return False

            async def click(self):
                if browser.pending_post:
                    assert selector == "#queues_tokens-start-button"
                    await browser.dispatch(
                        browser.module.post_url("queues_tokens:start"),
                        method="POST",
                        headers={
                            "content-type": "application/x-www-form-urlencoded",
                            "origin": "https://private-invalid-origin.invalid",
                        },
                        body=urlencode(browser.module.expected_post_fields("queues_tokens:start")),
                    )

            async def evaluate(self, expression):
                assert selector == "#browsers_members-member"
                assert expression == "node => node.matches(':invalid')"
                return True

            async def fill(self, _value):
                pass

            async def select_option(self, _value):
                pass

        return Locator()

    def expect_response(self, _predicate):
        browser = self

        class ResponseWait:
            async def __aenter__(self):
                browser.pending_post = True

            async def __aexit__(self, kind, _error, _traceback):
                if kind is None:
                    raise browser.error

        return ResponseWait()

    async def close(self):
        self.closed = True
        if self.close_error is not None:
            # Teardown observations must not replace the failure-time counts.
            await self.dispatch(self.module.SNAPSHOT_URL)
            self.page_error(RuntimeError("private-cleanup-page-error"))
            raise self.close_error


@pytest.mark.parametrize(
    ("fault", "documents", "snapshots", "rejected", "page_errors", "cleanup"),
    [
        ("context_create", "0", "0", "0", "0", "NOT_CREATED"),
        ("document_load", "1", "0", "0", "0", "CLOSED"),
        ("initial_timestamp", "1", "1", "0", "1", "CLOSED"),
        ("initial_live_poll", "1", "1", "0", "1", "CLOSED"),
        ("queues_start", "1", "1", "1", "1", "CLOSED"),
    ],
)
def test_viewport_failure_reports_actual_step_and_route_counts_without_payloads(
    capsys, fault, documents, snapshots, rejected, page_errors, cleanup
):
    module = _module()
    error = TimeoutError("private-url-token-dom-fixture-must-not-be-logged")
    browser = _InertViewportBrowser(module, fault, error)
    with pytest.raises(TimeoutError) as caught:
        asyncio.run(module._viewport(browser, module.make_fixture(SOURCE_SHA), 800, 1280))
    assert caught.value is error
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"BOCA_ENGINE_UI_PROBE state=NO_GO step={fault} viewport=800x1280 "
        f"snapshot_phase=0 documents={documents} snapshots={snapshots} native_posts=0 "
        f"rejected={rejected} page_errors={page_errors} error_type=TimeoutError "
        f"cleanup={cleanup}\n"
    )


def test_viewport_cleanup_cannot_mask_primary_error_or_change_failure_time_counts(capsys):
    module = _module()
    primary = TimeoutError("private-primary-error")
    browser = _InertViewportBrowser(
        module, "initial_live_poll", primary, RuntimeError("private-cleanup-error")
    )
    with pytest.raises(TimeoutError) as caught:
        asyncio.run(module._viewport(browser, module.make_fixture(SOURCE_SHA), 800, 1280))
    assert caught.value is primary
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "BOCA_ENGINE_UI_PROBE state=NO_GO step=initial_live_poll viewport=800x1280 "
        "snapshot_phase=0 documents=1 snapshots=1 native_posts=0 rejected=0 "
        "page_errors=1 error_type=TimeoutError cleanup=FAILED\n"
    )


def test_probe_formatter_bounds_counts_and_rejects_untrusted_categories():
    module = _module()

    class PrivateDiagnosticObject:
        def __str__(self):
            raise AssertionError("untrusted diagnostic content was stringified")

    error_type = type("PrivateBrowserExceptionName", (Exception,), {})
    result = module._probe_failure_report(
        ["private-step"],
        error_type("private-exception-content"),
        width=True,
        height=1280,
        counts={
            "snapshot_phase": 5,
            "documents": 2,
            "snapshots": 10**1000,
            "native_posts": True,
            "rejected": -1,
            "page_errors": PrivateDiagnosticObject(),
            "private_extra": "private-url-token",
        },
        cleanup=["private-cleanup"],
    )
    assert result == (
        "BOCA_ENGINE_UI_PROBE state=NO_GO step=UNKNOWN viewport=UNKNOWN "
        "snapshot_phase=OVER_LIMIT documents=OVER_LIMIT snapshots=OVER_LIMIT "
        "native_posts=UNKNOWN rejected=UNKNOWN page_errors=UNKNOWN "
        "error_type=UNKNOWN cleanup=UNKNOWN"
    )
    assert len(result) < 512


@pytest.mark.parametrize(
    ("body_fails", "browser_close_fails", "driver_close_fails", "steps"),
    [
        (True, True, False, ["browser_close"]),
        (True, False, True, ["playwright_close"]),
        (True, True, True, ["browser_close", "playwright_close"]),
        (False, True, False, ["browser_close"]),
        (False, False, True, ["playwright_close"]),
        (False, True, True, ["browser_close", "playwright_close"]),
    ],
)
def test_offline_cleanup_preserves_first_fault_and_never_passes_failed_cleanup(
    monkeypatch, capsys, body_fails, browser_close_fails, driver_close_fails, steps
):
    module = _module()
    primary = TimeoutError("private-browser-proof-content")
    browser_error = RuntimeError("private-browser-close-content")
    driver_error = RuntimeError("private-driver-close-content")

    async def close():
        if browser_close_fails:
            raise browser_error

    async def launch(**_kwargs):
        return types.SimpleNamespace(close=close)

    class Manager:
        async def __aenter__(self):
            return types.SimpleNamespace(chromium=types.SimpleNamespace(launch=launch))

        async def __aexit__(self, *_args):
            if driver_close_fails:
                raise driver_error

    async def viewport(*_args):
        if body_fails:
            raise primary
        return {}

    playwright = types.ModuleType("playwright.async_api")
    playwright.async_playwright = Manager
    monkeypatch.setitem(sys.modules, "playwright.async_api", playwright)
    monkeypatch.setattr(module, "_offline_identity", lambda: None)
    monkeypatch.setattr(module, "_viewport", viewport)
    expected = primary if body_fails else browser_error if browser_close_fails else driver_error
    with pytest.raises(type(expected)) as caught:
        asyncio.run(module.run_offline(module.make_fixture(SOURCE_SHA), SOURCE_SHA))
    assert caught.value is expected
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private" not in captured.err
    assert captured.err.splitlines() == [
        f"BOCA_ENGINE_UI_PROBE state=NO_GO step={step} viewport=UNKNOWN "
        "snapshot_phase=UNKNOWN documents=UNKNOWN snapshots=UNKNOWN native_posts=UNKNOWN "
        "rejected=UNKNOWN page_errors=UNKNOWN error_type=RuntimeError cleanup=FAILED"
        for step in steps
    ]


def test_verified_capture_writes_only_bounded_named_pngs_and_public_report(tmp_path):
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    capture = _capture(module, fixture)
    destination = tmp_path / "artifacts"
    report = module.write_artifacts(capture, fixture, SOURCE_SHA, destination)
    assert {path.name for path in destination.iterdir()} == {
        "engines-tablet-800x1280.png",
        "engines-mobile-412x915.png",
        "report.json",
    }
    assert report["source_sha"] == SOURCE_SHA
    assert report["host_checked"] is report["physical_device_checked"] is False
    assert report["html_sha256"] == fixture["html_sha256"]
    assert "png_base64" not in (destination / "report.json").read_text()
    for view in report["viewports"]:
        raw = (destination / view["screenshot"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == view["screenshot_sha256"]
        assert len(raw) == view["screenshot_bytes"]


@pytest.mark.parametrize("change", ["sha", "fixture", "check", "post", "network", "png", "extra"])
def test_capture_rejects_unproven_or_tampered_evidence_before_creating_artifacts(tmp_path, change):
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    capture = _capture(module, fixture)
    if change == "sha":
        capture["source_sha"] = "b" * 40
    elif change == "fixture":
        capture["fixture_sha256"] = "0" * 64
    elif change == "check":
        capture["viewports"][0]["checks"][module.CHECKS[0]] = False
    elif change == "post":
        capture["viewports"][0]["native_posts"].pop()
    elif change == "network":
        capture["viewports"][0]["other_requests"] = 1
    elif change == "png":
        capture["viewports"][0]["png_base64"] = base64.b64encode(_png(1, 1)).decode()
    else:
        capture["viewports"][0]["screenshot"] = "../../escape.png"
    destination = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        module.write_artifacts(capture, fixture, SOURCE_SHA, destination)
    assert not destination.exists()


def test_cli_failure_does_not_print_fixture_contents_or_create_an_output(tmp_path, capsys):
    module = _module()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"unexpected": "private-content-must-not-be-logged"}))
    output = tmp_path / "output"
    assert module.main(["--verify-capture", str(bad), str(bad), SOURCE_SHA, str(output)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-content" not in captured.err
    assert "NO_GO" in captured.err
    assert not output.exists()


def test_renderer_timezone_failure_reports_its_phase_without_exception_contents(
    monkeypatch, capsys
):
    from zoneinfo import ZoneInfoNotFoundError

    from boca_socios.panel import engine_view

    module = _module()

    def missing_zone(_name):
        raise ZoneInfoNotFoundError("private-zone-data-must-not-be-logged")

    monkeypatch.setattr(engine_view, "ZoneInfo", missing_zone)
    assert module.main(["--make-fixture", SOURCE_SHA]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "BOCA_ENGINE_UI_OFFLINE state=NO_GO phase=fixture_render "
        "reason=timezone_unavailable error_type=ZoneInfoNotFoundError\n"
    )


def test_browser_assertion_reports_only_its_allowlisted_reason(monkeypatch, tmp_path, capsys):
    module = _module()
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(module.make_fixture(SOURCE_SHA)))

    async def rejected(_fixture, _source):
        raise RuntimeError("required_member_unverified")

    monkeypatch.setattr(module, "run_offline", rejected)
    assert module.main(["--run-offline-fixture", str(fixture), SOURCE_SHA]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "BOCA_ENGINE_UI_OFFLINE state=NO_GO phase=browser_proof "
        "reason=required_member_unverified error_type=RuntimeError\n"
    )


@pytest.mark.parametrize("unknown_type", [False, True])
def test_failure_diagnostics_never_echo_unrecognized_reason_or_exception_type(
    monkeypatch, capsys, unknown_type
):
    module = _module()
    error_type = (
        type("PrivateExceptionNameMustNotBeLogged", (Exception,), {})
        if unknown_type
        else RuntimeError
    )

    def rejected(_source):
        raise error_type("private-runtime-or-browser-content-must-not-be-logged")

    monkeypatch.setattr(module, "make_fixture", rejected)
    assert module.main(["--make-fixture", SOURCE_SHA]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    expected_type = "UNKNOWN" if unknown_type else "RuntimeError"
    assert captured.err == (
        "BOCA_ENGINE_UI_OFFLINE state=NO_GO phase=fixture_render "
        f"reason=offline_proof_failed error_type={expected_type}\n"
    )
