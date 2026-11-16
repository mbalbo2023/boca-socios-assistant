"""Offline visual evidence must stay tied to fixed fixtures and the candidate SHA."""

from __future__ import annotations

import ast
import asyncio
import base64
import errno
import hashlib
import inspect
import io
import json
import shutil
import struct
import subprocess
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
                "document_requests": 6,
                "snapshot_requests": 9,
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


def test_activity_fixture_has_real_readonly_renderer_and_separate_bounded_gets():
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    service = module._FixtureService(fixture)
    _http_exchange(module, service, _request())
    for operation in module.POST_ORDER[:2]:
        body = urlencode(module.expected_post_fields(operation)).encode()
        assert _http_exchange(
            module,
            service,
            _request(
                "POST",
                module.post_url(operation).removeprefix(module.ORIGIN),
                headers=(
                    "Origin: " + module.ORIGIN,
                    "Content-Type: application/x-www-form-urlencoded",
                    f"Content-Length: {len(body)}",
                ),
                body=body,
            ),
        ).startswith(b"HTTP/1.0 303 ")
        _http_exchange(module, service, _request())
    activity = _http_exchange(module, service, _request(path="/control/actividad"))
    assert activity.startswith(b"HTTP/1.0 200 ")
    assert b'id="queues_tokens-sessions"' in activity and b'id="worker-events"' in activity
    assert b"<form" not in activity
    assert fixture["activity_document"]["html"].encode() in activity
    assert service.counters()["activity_documents"] == 1
    assert service.counters()["documents"] == 3
    timeline = _http_exchange(module, service, _request(path="/control/actividad.json"))
    assert timeline.startswith(b"HTTP/1.0 200 ") and b'"events"' in timeline
    service.advance_poll()
    snapshot = _http_exchange(module, service, _request(path="/control/motores.json"))
    assert b'"session_id":"00000000-0000-4000-8000-000000000302"' in snapshot
    assert service.counters()["activity_documents"] == 1
    assert len(module._json(fixture)) <= 170_000
    repeated = _http_exchange(module, service, _request(path="/control/actividad"))
    assert not repeated.startswith(b"HTTP/1.0 200 ")


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "token",
        "url",
        "html",
        "redirect_html",
        "redirect_phase",
        "fixture_size",
        "extra",
        "old_schema",
        "activity_html",
        "activity_phase",
        "activity_extra",
        "activity_missing",
    ],
)
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
    elif change == "redirect_html":
        fixture["redirect_documents"][0]["html"] += "<p>unexpected</p>"
    elif change == "redirect_phase":
        fixture["redirect_documents"][0]["snapshot_phase"] = 3
    elif change == "fixture_size":
        fixture["html"] += " " * 60_000
        fixture["html_sha256"] = hashlib.sha256(fixture["html"].encode()).hexdigest()
    elif change == "old_schema":
        fixture["schema"] = 2
    elif change == "activity_html":
        fixture["activity_document"]["html"] += "<p>unreviewed</p>"
    elif change == "activity_phase":
        fixture["activity_document"]["snapshot_phase"] = 3
    elif change == "activity_extra":
        fixture["activity_document"]["url"] = "https://other.invalid"
    elif change == "activity_missing":
        del fixture["activity_document"]
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


def test_dom_waits_keep_conditions_when_later_eval_is_blocked():
    module = _module()
    calls = [
        item
        for item in ast.walk(ast.parse(inspect.getsource(module)))
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "wait_for_function"
    ]
    expressions = [ast.literal_eval(call.args[0]) for call in calls]
    assert len(expressions) == 10
    node = shutil.which("node")
    assert node is not None
    harness = r"""
const vm = require('node:vm');
const expressions = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const results = expressions.map(expression => {
  let ready = false;
  let evaluations = 0;
  const count = Number((expression.match(/length === ([23])/) || [])[1]);
  const document = {
    getElementById(id) {
      if (id === 'engines-checked') return {textContent: ready ? '2020-01-01' : ''};
      if (id === 'engines-live') return {textContent: ready ? 'Actualizado.' : 'Último estado disponible.'};
      if (id === 'engines-total-active') return {textContent: ready ? expression.match(/=== '([01])'/)[1] : ''};
      if (['queues_tokens-stop-button', 'browsers_members-stop-button'].includes(id))
        return {disabled: ready};
      throw new Error('unexpected fixed DOM lookup');
    },
    querySelectorAll(selector) {
      if (selector !== '[data-session-id]' || ![2, 3].includes(count))
        throw new Error('unexpected fixed DOM selector');
      return {length: ready ? count : 0};
    }
  };
  const context = vm.createContext({document, expression}, {codeGeneration: {strings: false, wasm: false}});
  // Pinned Playwright 1.64.1 frames.ts1619-1638 caches functions, while a
  // boolean expression is evaluated again by later RAF callbacks. The first
  // invocation uses the driver boundary; deferred eval has no such privilege.
  let cached;
  function predicate() {
    let result = cached;
    if (result === undefined) {
      evaluations++;
      result = evaluations === 1 ? vm.runInContext(expression, context) : vm.runInContext('eval(expression)', context);
    }
    if (typeof result === 'function') {
      cached = result;
      result = result();
    }
    return result;
  }
  try {
    const before = [predicate(), predicate()];
    ready = true;
    return {before, after: predicate(), evaluations};
  } catch (error) {
    return {error: error.name};
  }
});
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(  # noqa: S603 - fixed runner expressions in an inert VM, no browser
        [node, "-e", harness],
        input=json.dumps(expressions),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == [
        {"before": [False, False], "after": True, "evaluations": 1} for _expression in expressions
    ]


@pytest.mark.parametrize("body_fails", [False, True])
def test_refresh_waits_for_body_without_orphaned_finished_task(body_fails):
    module = _module()

    async def exercise():
        body_ready = asyncio.get_running_loop().create_future()
        events = []
        primary = RuntimeError("PRIVATE_BODY_FAILURE")

        class Response:
            status = 200
            url = module.SNAPSHOT_URL
            request = types.SimpleNamespace(method="GET")

            async def body(self):
                events.append("body")
                return await body_ready

            async def finished(self):
                raise AssertionError("Response.finished can leave a target-close task pending")

        response = Response()

        class Expectation:
            async def __aenter__(self):
                self.value = asyncio.get_running_loop().create_future()
                self.value.set_result(response)
                events.append("listen")
                return self

            async def __aexit__(self, *_args):
                return False

        class Page:
            def expect_response(self, predicate):
                assert predicate(response)
                return Expectation()

            def locator(self, selector):
                assert selector == "#engines-refresh"
                return self

            async def click(self):
                events.append("click")

        task = asyncio.create_task(module._refresh(Page()))
        try:
            await asyncio.sleep(0)
            if task.done():
                await task
            assert events == ["listen", "click", "body"]
            assert not task.done(), "response headers alone must not finish the refresh proof"
            if body_fails:
                body_ready.set_exception(primary)
                with pytest.raises(RuntimeError) as caught:
                    await task
                assert caught.value is primary
            else:
                body_ready.set_result(b"{}")
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Page.wait_for_function: EvalError: Refused to evaluate a string as JavaScript "
            "because unsafe-eval is not allowed by Content Security Policy PRIVATE_CONTENT",
            "CSP_EVAL_BLOCKED",
        ),
        (
            "Page.wait_for_function: Target page, context or browser has been closed",
            "TARGET_CLOSED",
        ),
        ("Page.wait_for_function: Target closed PRIVATE_CONTENT", "TARGET_CLOSED"),
        ("Page.wait_for_function: Execution context was destroyed", "EXECUTION_CONTEXT_DESTROYED"),
        ("Refused to evaluate a string as JavaScript; Content Security Policy", "UNKNOWN"),
        ("Target closed; execution context was destroyed", "UNKNOWN"),
        ("Unclassified PRIVATE_CONTENT\nTarget closed", "UNKNOWN"),
        ("x" * 16384 + "Target closed", "UNKNOWN"),
        ("PRIVATE_CONTENT", "UNKNOWN"),
    ],
)
def test_primary_failure_classification_is_closed_bounded_and_unambiguous(message, expected):
    module = _module()
    error = RuntimeError(message)
    state = module._failure_state(error)
    assert state == {
        "error_kind": expected,
        "page_closed": "UNKNOWN",
        "browser_connected": "UNKNOWN",
    }
    receipt = module._probe_failure_report("live_rows_poll", error, failure_state=state)
    assert f"error_kind={expected}" in receipt
    assert "PRIVATE_CONTENT" not in receipt and "Refused" not in receipt


@pytest.mark.parametrize(
    "failure", ["args", "page_getter", "browser_method", "nonbool", "argument_object"]
)
def test_failure_observations_handle_untrusted_access_without_replacing_primary(failure):
    module = _module()

    class PrivateObject:
        def __str__(self):
            raise AssertionError("private diagnostic content was stringified")

        def __bool__(self):
            raise AssertionError("untrusted state was coerced to bool")

    class PrivateError(Exception):
        @property
        def args(self):
            raise RuntimeError("PRIVATE_ARGS_FAILURE")

    class Page:
        @property
        def is_closed(self):
            raise RuntimeError("PRIVATE_PAGE_FAILURE")

    def broken():
        raise RuntimeError("PRIVATE_BROWSER_FAILURE")

    error = (
        PrivateError()
        if failure == "args"
        else RuntimeError(
            PrivateObject() if failure == "argument_object" else "PRIVATE_PRIMARY_CONTENT"
        )
    )
    page = (
        Page()
        if failure == "page_getter"
        else types.SimpleNamespace(is_closed=lambda: PrivateObject())
    )
    browser = types.SimpleNamespace(
        is_connected=broken if failure == "browser_method" else lambda: 1
    )
    state = module._failure_state(error, browser, page)
    assert state == {
        "error_kind": "UNKNOWN",
        "page_closed": "UNKNOWN",
        "browser_connected": "UNKNOWN",
    }
    receipt = module._probe_failure_report("live_rows_poll", error, failure_state=state)
    assert "PRIVATE" not in receipt


@pytest.mark.parametrize("shape", ["empty", "multiple", "list", "string_subclass"])
def test_primary_failure_classification_requires_exact_single_string_arguments(shape):
    module = _module()

    class PrivateString(str):
        def lower(self):
            raise AssertionError("untrusted argument method was invoked")

    arguments = {
        "empty": (),
        "multiple": ("Target closed", "PRIVATE_CONTENT"),
        "list": ["Target closed"],
        "string_subclass": (PrivateString("Target closed"),),
    }[shape]

    class Error(Exception):
        @property
        def args(self):
            return arguments

    assert module._failure_state(Error())["error_kind"] == "UNKNOWN"


def _http_exchange(module, service, raw):
    """Run the real stdlib request handler over streams, without a socket."""
    output = bytearray()

    class Connection:
        def settimeout(self, timeout):
            assert timeout == 5

        def makefile(self, mode, _buffering):
            assert mode == "rb"
            return io.BytesIO(raw) if isinstance(raw, bytes) else raw

        def sendall(self, value):
            output.extend(value)

    server = types.SimpleNamespace(service=service)
    module._FixtureRequestHandler(Connection(), ("127.0.0.1", 12345), server)
    return bytes(output)


def _request(method="GET", path="/control", *, headers=(), body=b""):
    lines = [f"{method} {path} HTTP/1.1", "Host: localhost:8443", *headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


def test_http_fixture_models_all_native_redirects_and_preserves_poll_document():
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    service = module._FixtureService(fixture)
    initial = _http_exchange(module, service, _request())
    assert initial.startswith(b"HTTP/1.0 200 ")
    assert fixture["html"].encode() in initial
    assert fixture["csp"].encode() in initial
    assert b"Referrer-Policy: same-origin\r\n" in initial
    for number, operation in enumerate(module.POST_ORDER, 1):
        if number == 3:
            service.advance_poll()
            before = service.counters()
            snapshot = _http_exchange(module, service, _request(path="/control/motores.json"))
            assert b'"session_id":"00000000-0000-4000-8000-000000000302"' in snapshot
            assert service.counters()["documents"] == before["documents"] == 3
        body = urlencode(module.expected_post_fields(operation)).encode()
        response = _http_exchange(
            module,
            service,
            _request(
                "POST",
                module.post_url(operation).removeprefix(module.ORIGIN),
                headers=(
                    "Origin: http://localhost:8443",
                    "Content-Type: application/x-www-form-urlencoded",
                    f"Content-Length: {len(body)}",
                ),
                body=body,
            ),
        )
        assert response.startswith(b"HTTP/1.0 303 ")
        assert b"Location: /control\r\n" in response
        assert response.endswith(b"\r\n\r\n")
        document = _http_exchange(module, service, _request())
        assert document.startswith(b"HTTP/1.0 200 ")
        assert fixture["redirect_documents"][number - 1]["html"].encode() in document
        assert service.counters()["documents"] == number + 1
    assert service.counters() == {
        "snapshot_phase": 5,
        "documents": 5,
        "snapshots": 1,
        "native_posts": 4,
        "rejected": 0,
        "activity_documents": 0,
        "activity_snapshots": 0,
    }
    assert len(module._json(fixture)) <= 170_000
    assert len(fixture["snapshots"]) == 6
    assert fixture["snapshots"][1]["engines"][0]["state"] == "RUNNING"
    assert fixture["snapshots"][1]["engines"][1]["state"] == "STOPPED"


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ("origin", 403),
        ("fields", 400),
        ("order", 400),
        ("query", 400),
        ("host", 400),
        ("duplicate", 400),
        ("transfer", 400),
        ("length", 400),
        ("short_body", 400),
        ("line", 400),
        ("header_bytes", 400),
        ("header_lines", 400),
        ("method", 405),
    ],
)
def test_http_fixture_rejects_malformed_or_untrusted_requests_without_echo(capsys, change, status):
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    _http_exchange(module, service, _request())
    operation = "browsers_members:start" if change == "order" else "queues_tokens:start"
    fields = module.expected_post_fields(operation)
    if change == "fields":
        fields["operation_id"] = "PRIVATE_FIXTURE_SECRET"
    body = urlencode(fields).encode()
    path = module.post_url(operation).removeprefix(module.ORIGIN)
    origin = "https://PRIVATE_FIXTURE_SECRET.invalid" if change == "origin" else module.ORIGIN
    headers = [
        f"Origin: {origin}",
        "Content-Type: application/x-www-form-urlencoded",
        f"Content-Length: {len(body)}",
    ]
    if change == "query":
        path += "?PRIVATE_FIXTURE_SECRET=1"
    elif change in {"host", "duplicate"}:
        headers.append(
            "Host: PRIVATE_FIXTURE_SECRET.invalid" if change == "host" else "Origin: " + origin
        )
    elif change == "transfer":
        headers.append("Transfer-Encoding: chunked")
    elif change == "length":
        headers[-1] = "Content-Length: 2049"
    elif change == "short_body":
        body = body[:-1]
    elif change == "line":
        headers.append("X-Private: " + "x" * 2048)
    elif change == "header_bytes":
        headers.extend("X-Private: " + "x" * 1000 for _ in range(9))
    elif change == "header_lines":
        headers.extend(f"X-Private-{i}: x" for i in range(65))
    raw = _request("DELETE" if change == "method" else "POST", path, headers=headers, body=body)
    response = _http_exchange(module, service, raw)
    assert response.startswith(f"HTTP/1.0 {status} ".encode())
    assert b"PRIVATE_FIXTURE_SECRET" not in response
    assert service.counters()["rejected"] == 1
    assert service.stopping.is_set()
    assert service.counters()["native_posts"] == 0
    assert capsys.readouterr().err == ""


def test_http_fixture_caps_admission_and_rejected_counts():
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    _http_exchange(module, service, _request())
    for _ in range(24):
        assert _http_exchange(module, service, _request(path="/control/motores.json")).startswith(
            b"HTTP/1.0 200 "
        )
    assert _http_exchange(module, service, _request(path="/control/motores.json")).startswith(
        b"HTTP/1.0 429 "
    )
    for _ in range(3):
        assert _http_exchange(module, service, _request()).startswith(b"HTTP/1.0 503 ")
    assert service.counters()["snapshots"] == 24
    assert service.counters()["documents"] == 1
    assert service.counters()["rejected"] == 1


def test_http_fixture_refuses_extra_document_without_an_accepted_post():
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    _http_exchange(module, service, _request())
    response = _http_exchange(module, service, _request())
    assert response.startswith(b"HTTP/1.0 400 ")
    assert service.counters()["documents"] == 1
    assert service.counters()["rejected"] == 1


def test_http_handler_suppresses_private_exception_tracebacks(monkeypatch, capsys):
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))

    def broken(*_args):
        raise RuntimeError("PRIVATE_FIXTURE_SECRET")

    monkeypatch.setattr(service, "respond", broken)
    _http_exchange(module, service, _request())
    assert service.counters()["rejected"] == 1
    module._FixtureHTTPServer.handle_error(types.SimpleNamespace(service=service), None, None)
    assert capsys.readouterr().err == ""


def test_http_socket_timeout_stops_admission_without_stdlib_logging(capsys):
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))

    class Stream:
        def readline(self, _limit):
            raise TimeoutError("PRIVATE_TIMEOUT_CONTENT")

        def close(self):
            pass

    assert _http_exchange(module, service, Stream()) == b""
    assert service.counters()["rejected"] == 1
    assert service.stopping.is_set()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("already_stopping", [False, True])
def test_accepted_socket_is_registered_or_closed_under_the_stop_guard(
    monkeypatch, already_stopping
):
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    closed = []
    connection = types.SimpleNamespace(
        settimeout=lambda value: None if value == 5 else pytest.fail("socket timeout changed"),
        close=lambda: closed.append(True),
    )
    server = object.__new__(module._FixtureHTTPServer)
    server.service = service
    monkeypatch.setattr(
        module.HTTPServer, "get_request", lambda _self: (connection, ("127.0.0.1", 12345))
    )
    if already_stopping:
        service.stopping.set()
        with pytest.raises(OSError):
            server.get_request()
        assert service.active is None
        assert closed == [True]
    else:
        assert server.get_request()[0] is connection
        assert service.active is connection
        assert closed == []


@pytest.mark.parametrize("failure", [None, "socket", "server", "thread"])
def test_fixture_close_attempts_every_resource_and_requires_stopped_thread(failure):
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    events = []

    class Connection:
        closed = False

        def shutdown(self, _how):
            events.append("shutdown")
            if failure == "socket":
                raise RuntimeError("private-cleanup-failure")

        def close(self):
            events.append("socket_close")
            self.closed = True

        def fileno(self):
            return -1 if self.closed else 42

    class Server:
        socket = Connection()

        def server_close(self):
            events.append("server_close")
            if failure == "server":
                raise RuntimeError("private-cleanup-failure")
            self.socket.closed = True

    class Thread:
        ident = 1

        def join(self, timeout):
            assert timeout == 5
            events.append("join")

        def is_alive(self):
            return failure == "thread"

    service.active = Connection()
    service.server = Server()
    service.thread = Thread()
    if failure is None:
        service.close()
    else:
        with pytest.raises(RuntimeError, match="^offline_fixture_close_unverified$"):
            service.close()
    assert service.stopping.is_set()
    assert set(events) == {"shutdown", "socket_close", "server_close", "join"}


@pytest.mark.parametrize("code", [errno.EBADF, errno.ENOTCONN, errno.EIO])
@pytest.mark.parametrize("socket_closed", [True, False])
def test_fixture_close_only_accepts_shutdown_race_when_every_resource_is_closed(
    code, socket_closed
):
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    joined = []

    class Connection:
        def shutdown(self, _how):
            raise OSError(code, "PRIVATE_CLOSE_CONTENT")

        def close(self):
            pass

        def fileno(self):
            return -1 if socket_closed else 42

    service.active = Connection()
    service.server = types.SimpleNamespace(
        server_close=lambda: None,
        socket=types.SimpleNamespace(fileno=lambda: -1),
    )
    service.thread = types.SimpleNamespace(
        ident=1,
        join=lambda *, timeout: joined.append(timeout),
        is_alive=lambda: False,
    )
    if socket_closed and code in {errno.EBADF, errno.ENOTCONN}:
        service.close()
    else:
        with pytest.raises(RuntimeError, match="^offline_fixture_close_unverified$"):
            service.close()
    assert joined == [5]


@pytest.mark.parametrize("drained", [True, False])
def test_fixture_close_certifies_descriptor_after_handler_releases_makefile(drained):
    module = _module()
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    events = []

    class Connection:
        close_requested = False
        file_reference_open = True

        def shutdown(self, _how):
            events.append("shutdown")

        def close(self):
            events.append("socket_close")
            self.close_requested = True

        def fileno(self):
            events.append("accepted_descriptor_check")
            return -1 if self.close_requested and not self.file_reference_open else 42

    active = Connection()

    class Thread:
        ident = 1

        def join(self, timeout):
            assert timeout == 5
            events.append("join")
            if drained:
                active.file_reference_open = False

        def is_alive(self):
            return False

    service.active = active
    service.server = types.SimpleNamespace(
        server_close=lambda: events.append("server_close"),
        socket=types.SimpleNamespace(fileno=lambda: -1),
    )
    service.thread = Thread()
    if drained:
        service.close()
    else:
        with pytest.raises(RuntimeError, match="^offline_fixture_close_unverified$"):
            service.close()
    assert active.close_requested
    assert events.index("socket_close") < events.index("join")
    assert events.index("join") < events.index("accepted_descriptor_check")


def test_fixture_cannot_open_listener_before_offline_identity(monkeypatch):
    module = _module()
    events = []

    def denied():
        raise RuntimeError("offline_browser_identity_unverified")

    monkeypatch.setattr(module, "_offline_identity", denied)
    monkeypatch.setattr(module, "_FixtureHTTPServer", lambda *_args: events.append("socket"))
    service = module._FixtureService(module.make_fixture(SOURCE_SHA))
    with pytest.raises(RuntimeError, match="offline_browser_identity_unverified"):
        service.start()
    assert events == []


@pytest.mark.parametrize("change", [None, "post_status", "location", "get_status", "chain", "url"])
def test_native_submit_requires_correlated_303_and_new_document(change):
    module = _module()

    async def exercise():
        post = types.SimpleNamespace(
            url=module.post_url("queues_tokens:start"),
            method="POST",
            is_navigation_request=lambda: True,
        )
        landing = types.SimpleNamespace(
            url=module.PAGE_URL,
            method="GET",
            is_navigation_request=lambda: True,
            redirected_from=None if change == "chain" else post,
        )
        responses = [
            types.SimpleNamespace(
                url=post.url,
                request=post,
                status=200 if change == "post_status" else 303,
                headers={
                    "location": "https://private.invalid" if change == "location" else "/control"
                },
            ),
            types.SimpleNamespace(
                url=landing.url, request=landing, status=503 if change == "get_status" else 200
            ),
        ]
        listeners = []
        loaded = []

        class Expectation:
            def __init__(self, predicate):
                self.predicate = predicate
                self.value = asyncio.get_running_loop().create_future()

            async def __aenter__(self):
                listeners.append(self)
                return self

            async def __aexit__(self, kind, _error, _traceback):
                if kind is None and not self.value.done():
                    raise TimeoutError("private-unmatched-response")

        class Page:
            url = module.PAGE_URL if change != "url" else "https://private.invalid"

            def expect_response(self, predicate):
                return Expectation(predicate)

            def locator(self, selector):
                assert selector == "#queues_tokens-start-button"
                return self

            async def click(self, **kwargs):
                assert kwargs == {}, (
                    "native click keeps all default actionability/navigation checks"
                )
                for response in responses:
                    for listener in listeners:
                        if not listener.value.done() and listener.predicate(response):
                            listener.value.set_result(response)

            async def wait_for_load_state(self, state):
                loaded.append(state)

            async def wait_for_function(self, _expression):
                pass

        await module._submit(Page(), "queues_tokens:start")
        assert loaded == ["load"]

    if change is None:
        asyncio.run(exercise())
    else:
        with pytest.raises(TimeoutError if change == "chain" else RuntimeError):
            asyncio.run(exercise())


def test_page_error_callback_accepts_playwright_wrapper_cache_before_navigation(monkeypatch):
    """Playwright 1.64.1 caches its wrapper on non-method callback objects."""
    module = _module()
    monkeypatch.setattr(module._FixtureService, "start", lambda _service: None)

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

        async def continue_():
            request_headers = [f"{name}: {value}" for name, value in (headers or {}).items()]
            content = body.encode() if body is not None else b""
            if method == "POST":
                request_headers.append(f"Content-Length: {len(content)}")
            _http_exchange(
                self.module,
                self.service,
                _request(
                    method,
                    url.removeprefix(self.module.ORIGIN),
                    headers=request_headers,
                    body=content,
                ),
            )

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
        await self.handler(types.SimpleNamespace(request=request, continue_=continue_, abort=abort))

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
    monkeypatch, capsys, fault, documents, snapshots, rejected, page_errors, cleanup
):
    module = _module()
    error = TimeoutError("private-url-token-dom-fixture-must-not-be-logged")
    browser = _InertViewportBrowser(module, fault, error)
    monkeypatch.setattr(
        module._FixtureService, "start", lambda service: setattr(browser, "service", service)
    )
    with pytest.raises(TimeoutError) as caught:
        asyncio.run(module._viewport(browser, module.make_fixture(SOURCE_SHA), 800, 1280))
    assert caught.value is error
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"BOCA_ENGINE_UI_PROBE state=NO_GO step={fault} viewport=800x1280 "
        f"snapshot_phase=0 documents={documents} snapshots={snapshots} native_posts=0 "
        f"rejected={rejected} page_errors={page_errors} error_type=TimeoutError "
        "error_kind=UNKNOWN page_closed=UNKNOWN browser_connected=UNKNOWN "
        f"cleanup={cleanup}\n"
    )


def test_viewport_cleanup_cannot_mask_primary_error_or_change_failure_time_counts(
    monkeypatch, capsys
):
    module = _module()
    primary = TimeoutError("private-primary-error")
    browser = _InertViewportBrowser(
        module, "initial_live_poll", primary, RuntimeError("private-cleanup-error")
    )
    monkeypatch.setattr(
        module._FixtureService, "start", lambda service: setattr(browser, "service", service)
    )
    with pytest.raises(TimeoutError) as caught:
        asyncio.run(module._viewport(browser, module.make_fixture(SOURCE_SHA), 800, 1280))
    assert caught.value is primary
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "BOCA_ENGINE_UI_PROBE state=NO_GO step=initial_live_poll viewport=800x1280 "
        "snapshot_phase=0 documents=1 snapshots=1 native_posts=0 rejected=0 "
        "page_errors=1 error_type=TimeoutError error_kind=UNKNOWN "
        "page_closed=UNKNOWN browser_connected=UNKNOWN cleanup=FAILED\n"
    )


def test_viewport_freezes_primary_category_and_boolean_state_before_cleanup(monkeypatch, capsys):
    module = _module()
    primary = RuntimeError("Target closed PRIVATE_PRIMARY_CONTENT")
    reads = []

    class Browser(_InertViewportBrowser):
        def is_closed(self):
            reads.append("page_closed")
            return self.closed

        def is_connected(self):
            reads.append("browser_connected")
            return not self.closed

        async def close(self):
            primary.args = ("Execution context was destroyed PRIVATE_CLEANUP_CONTENT",)
            await super().close()

    browser = Browser(module, "initial_timestamp", primary)
    monkeypatch.setattr(
        module._FixtureService, "start", lambda service: setattr(browser, "service", service)
    )
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(module._viewport(browser, module.make_fixture(SOURCE_SHA), 800, 1280))
    assert caught.value is primary
    assert browser.closed
    assert reads == ["page_closed", "browser_connected"]
    receipt = capsys.readouterr().err
    assert "error_kind=TARGET_CLOSED page_closed=false browser_connected=true" in receipt
    assert "EXECUTION_CONTEXT_DESTROYED" not in receipt and "PRIVATE" not in receipt


@pytest.mark.parametrize("context_close_fails", [False, True])
def test_viewport_always_closes_fixture_and_preserves_first_fault(
    monkeypatch, capsys, context_close_fails
):
    module = _module()
    primary = TimeoutError("PRIVATE_PRIMARY_CONTENT")
    browser = _InertViewportBrowser(
        module,
        "initial_timestamp",
        primary,
        RuntimeError("PRIVATE_CONTEXT_CONTENT") if context_close_fails else None,
    )
    closed = []

    def close(service):
        closed.append(service)
        raise RuntimeError("offline_fixture_close_unverified")

    monkeypatch.setattr(
        module._FixtureService, "start", lambda service: setattr(browser, "service", service)
    )
    monkeypatch.setattr(module._FixtureService, "close", close)
    with pytest.raises(TimeoutError) as caught:
        asyncio.run(module._viewport(browser, module.make_fixture(SOURCE_SHA), 800, 1280))
    assert caught.value is primary
    assert browser.closed
    assert closed == [browser.service]
    receipt = capsys.readouterr().err
    assert "step=initial_timestamp" in receipt and "cleanup=FAILED" in receipt
    assert "snapshots=1" in receipt and "page_errors=1" in receipt
    assert "PRIVATE" not in receipt


def test_failed_fixture_bind_is_closed_and_does_not_mask_startup_fault(monkeypatch, capsys):
    module = _module()
    primary = OSError("PRIVATE_BIND_CONTENT")
    browser = _InertViewportBrowser(module, None, primary)
    closed = []

    class Server:
        def __init__(self, _service):
            self.socket = types.SimpleNamespace(fileno=lambda: -1 if closed else 42)

        def server_bind(self):
            raise primary

        def server_close(self):
            closed.append(True)

    monkeypatch.setattr(module, "_offline_identity", lambda: None)
    monkeypatch.setattr(module, "_FixtureHTTPServer", Server)
    with pytest.raises(OSError) as caught:
        asyncio.run(module._viewport(browser, module.make_fixture(SOURCE_SHA), 800, 1280))
    assert caught.value is primary
    assert closed == [True]
    assert browser.closed
    receipt = capsys.readouterr().err
    assert "step=fixture_start" in receipt and "cleanup=CLOSED" in receipt
    assert "documents=0" in receipt and "PRIVATE" not in receipt


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
            "snapshot_phase": 6,
            "documents": 6,
            "snapshots": 10**1000,
            "native_posts": True,
            "rejected": -1,
            "page_errors": PrivateDiagnosticObject(),
            "private_extra": "private-url-token",
        },
        failure_state={
            "error_kind": PrivateDiagnosticObject(),
            "page_closed": 1,
            "browser_connected": "true",
        },
        cleanup=["private-cleanup"],
    )
    assert result == (
        "BOCA_ENGINE_UI_PROBE state=NO_GO step=UNKNOWN viewport=UNKNOWN "
        "snapshot_phase=OVER_LIMIT documents=OVER_LIMIT snapshots=OVER_LIMIT "
        "native_posts=UNKNOWN rejected=UNKNOWN page_errors=UNKNOWN "
        "error_type=UNKNOWN error_kind=UNKNOWN "
        "page_closed=UNKNOWN browser_connected=UNKNOWN cleanup=UNKNOWN"
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
        "rejected=UNKNOWN page_errors=UNKNOWN error_type=RuntimeError "
        "error_kind=UNKNOWN page_closed=UNKNOWN browser_connected=UNKNOWN cleanup=FAILED"
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


@pytest.mark.parametrize(
    "change",
    [
        "sha",
        "fixture",
        "check",
        "post",
        "network",
        "png",
        "old_documents",
        "old_snapshots",
        "extra",
    ],
)
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
    elif change == "old_documents":
        capture["viewports"][0]["document_requests"] = 5
    elif change == "old_snapshots":
        capture["viewports"][0]["snapshot_requests"] = 4
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
    fixture.write_bytes(module._json(module.make_fixture(SOURCE_SHA)) + b"\n")
    browser_sources = []

    async def rejected(_fixture, _source):
        browser_sources.append(_source)
        raise RuntimeError("required_member_unverified")

    monkeypatch.setattr(module, "run_offline", rejected)
    assert module.main(["--run-offline-fixture", str(fixture), SOURCE_SHA]) == 1
    assert browser_sources == [SOURCE_SHA]
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
