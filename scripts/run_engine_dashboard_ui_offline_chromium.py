"""Candidate-only dashboard proof in network-none Chromium, with fixed public data.

The controller image renders the actual page; the browser image needs only this
stdlib fixture reader and Playwright. The runner verifies bounded screenshots
before publishing them. No runtime database, owner session or provider is used.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import errno
import hashlib
import json
import os
import re
import socket
import stat
import struct
import sys
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Route

ORIGIN = "http://localhost:8443"
PAGE_URL = ORIGIN + "/control"
SNAPSHOT_URL = PAGE_URL + "/motores.json"
ACTIVITY_URL = PAGE_URL + "/actividad"
ACTIVITY_SNAPSHOT_URL = ACTIVITY_URL + ".json"
ENGINES = ("queues_tokens", "browsers_members")
VIEWPORTS = (
    (800, 1280, "engines-tablet-800x1280.png"),
    (412, 915, "engines-mobile-412x915.png"),
)
POST_ORDER = (
    "queues_tokens:start",
    "browsers_members:start",
    "queues_tokens:stop",
    "browsers_members:stop",
)
CHECKS = (
    "native_forms",
    "required_member",
    "native_post_origin",
    "live_rows",
    "preserved_inputs",
    "independent_stop",
    "metadata_only",
    "minimum_controls",
    "no_horizontal_overflow",
    "csp_execution",
)
FORM_PROOF = "fixed-public-offline-proof"
_STAMP = "2020-01-01T12:00:00+00:00"
_MAX_FIXTURE = 170_000
_MAX_CAPTURE = 6_000_000
_MAX_PNG = 2_000_000
_MAX_HEIGHT = 12_000
_FAILURE_PHASES = frozenset(
    {
        "arguments",
        "fixture_render",
        "fixture_read",
        "browser_proof",
        "capture_encode",
        "capture_read",
        "artifact_verify",
    }
)
_FAILURE_TYPES = frozenset(
    {
        "AssertionError",
        "AttributeError",
        "Error",
        "FileNotFoundError",
        "ImportError",
        "JSONDecodeError",
        "KeyError",
        "ModuleNotFoundError",
        "OSError",
        "PermissionError",
        "RuntimeError",
        "TimeoutError",
        "TypeError",
        "ValueError",
        "ZoneInfoNotFoundError",
    }
)
_FAILURE_REASONS = frozenset(
    {
        "accessible_layout_unverified",
        "candidate_source_unverified",
        "duplicate_json_field",
        "existing_session_replaced",
        "explicit_offline_mode_required",
        "independent_stop_fence_unverified",
        "independent_stop_projection_unverified",
        "initial_session_unverified",
        "initial_start_unverified",
        "live_snapshot_projection_unverified",
        "native_form_unverified",
        "offline_browser_evidence_unverified",
        "offline_browser_identity_unverified",
        "offline_capture_too_large",
        "offline_capture_unverified",
        "offline_document_changed",
        "offline_file_unverified",
        "offline_fixture_unverified",
        "offline_fixture_close_unverified",
        "offline_network_namespace_unverified",
        "offline_operation_unverified",
        "offline_viewport_unverified",
        "private_metadata_projection_unverified",
        "required_member_unverified",
        "running_start_unverified",
        "running_stop_unverified",
        "screenshot_unverified",
    }
)
_PROBE_STEPS = frozenset(
    {
        "playwright_start",
        "browser_launch",
        "context_create",
        "context_setup",
        "fixture_start",
        "route_install",
        "page_create",
        "page_error_hook",
        "document_load",
        "initial_timestamp",
        "initial_live_poll",
        "initial_start",
        "required_member",
        "initial_inputs",
        "queues_start",
        "members_inputs_after_redirect",
        "members_start",
        "running_refresh",
        "activity_create",
        "activity_load",
        "running_rows",
        "initial_session",
        "running_controls",
        "preserved_inputs_prepare",
        "live_rows_poll",
        "session_preserved",
        "live_projection",
        "stop_fences",
        "private_metadata",
        "queues_stop",
        "queues_stopped_refresh",
        "queues_stopped_poll",
        "independent_stop",
        "layout",
        "screenshot",
        "screenshot_verify",
        "members_stop",
        "members_stopped_refresh",
        "members_stopped_poll",
        "final_evidence",
        "viewport_capture_encode",
        "context_close",
        "fixture_close",
        "browser_close",
        "playwright_close",
    }
)
_PROBE_COUNTER_LIMITS = {
    "snapshot_phase": 5,
    "documents": 5,
    "snapshots": 24,
    "native_posts": 4,
    "rejected": 1,
    "page_errors": 24,
}
_ERROR_KINDS = frozenset(
    {"CSP_EVAL_BLOCKED", "TARGET_CLOSED", "EXECUTION_CONTEXT_DESTROYED", "UNKNOWN"}
)


def _primary_error_kind(error: BaseException) -> str:
    """Classify only a bounded first line; never stringify an exception."""
    try:
        arguments = error.args
        if type(arguments) is not tuple or len(arguments) != 1 or type(arguments[0]) is not str:
            return "UNKNOWN"
        first_line = arguments[0][:16384].split("\n", 1)[0].lower()
    except BaseException:
        return "UNKNOWN"
    matches = {
        "CSP_EVAL_BLOCKED": all(
            marker in first_line
            for marker in (
                "refused to evaluate a string as javascript",
                "content security policy",
                "unsafe-eval",
            )
        ),
        "TARGET_CLOSED": any(
            marker in first_line
            for marker in ("target page, context or browser has been closed", "target closed")
        ),
        "EXECUTION_CONTEXT_DESTROYED": "execution context was destroyed" in first_line,
    }
    observed = [kind for kind, matched in matches.items() if matched]
    return observed[0] if len(observed) == 1 else "UNKNOWN"


def _failure_state(
    error: BaseException, browser: object = None, page: object = None
) -> dict[str, object]:
    def boolean(target: object, method: str) -> bool | str:
        try:
            value = getattr(target, method)()
        except BaseException:
            return "UNKNOWN"
        return value if type(value) is bool else "UNKNOWN"

    return {
        "error_kind": _primary_error_kind(error),
        "page_closed": boolean(page, "is_closed"),
        "browser_connected": boolean(browser, "is_connected"),
    }


def _probe_failure_report(
    step: object,
    error: BaseException,
    *,
    width: object = None,
    height: object = None,
    counts: object = None,
    failure_state: object = None,
    cleanup: object = "NOT_CREATED",
) -> str:
    """Bound proof metadata without serializing exceptions, URLs or page data."""
    safe_step = step if type(step) is str and step in _PROBE_STEPS else "UNKNOWN"
    viewport = "UNKNOWN"
    if type(width) is int and type(height) is int:
        for known_width, known_height, _ in VIEWPORTS:
            if (width, height) == (known_width, known_height):
                viewport = f"{known_width}x{known_height}"
    fields = []
    for key, maximum in _PROBE_COUNTER_LIMITS.items():
        value = counts.get(key) if type(counts) is dict else None
        bounded = "UNKNOWN"
        if type(value) is int and value >= 0:
            bounded = str(value) if value <= maximum else "OVER_LIMIT"
        fields.append(f"{key}={bounded}")
    error_type = type(error).__name__
    safe_type = error_type if error_type in _FAILURE_TYPES else "UNKNOWN"
    kind = failure_state.get("error_kind") if type(failure_state) is dict else None
    safe_kind = kind if type(kind) is str and kind in _ERROR_KINDS else "UNKNOWN"
    observations = []
    for name in ("page_closed", "browser_connected"):
        value = failure_state.get(name) if type(failure_state) is dict else None
        observations.append(f"{name}={str(value).lower() if type(value) is bool else 'UNKNOWN'}")
    safe_cleanup = (
        cleanup
        if type(cleanup) is str and cleanup in {"NOT_CREATED", "CLOSED", "FAILED"}
        else "UNKNOWN"
    )
    return (
        f"BOCA_ENGINE_UI_PROBE state=NO_GO step={safe_step} viewport={viewport} "
        + " ".join(fields)
        + f" error_type={safe_type} error_kind={safe_kind} "
        + " ".join(observations)
        + f" cleanup={safe_cleanup}"
    )


def _failure_report(phase: str, error: Exception) -> str:
    """Emit only closed categories, never exception/browser/fixture contents."""
    safe_phase = phase if phase in _FAILURE_PHASES else "unknown"
    error_type = type(error).__name__
    safe_type = error_type if error_type in _FAILURE_TYPES else "UNKNOWN"
    reason = "offline_proof_failed"
    if safe_type == "ZoneInfoNotFoundError":
        reason = "timezone_unavailable"
    elif type(error) in {ValueError, RuntimeError} and len(error.args) == 1:
        candidate = error.args[0]
        if type(candidate) is str and candidate in _FAILURE_REASONS:
            reason = candidate
    return (
        f"BOCA_ENGINE_UI_OFFLINE state=NO_GO phase={safe_phase} "
        f"reason={reason} error_type={safe_type}"
    )


def _identity(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


_MEMBERS = (_identity(401), _identity(402))
_ACTIVATIONS = dict(zip(ENGINES, (_identity(201), _identity(202)), strict=True))
_GENERATIONS = dict(zip(ENGINES, (3, 7), strict=True))
_OPERATIONS = {name: _identity(101 + index) for index, name in enumerate(POST_ORDER)}


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _source(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{40}", value) is None:
        raise ValueError("candidate_source_unverified")


def _session(number: int, browser: str, *, member: bool = False) -> dict[str, object]:
    return {
        "session_id": _identity(number),
        "browser": browser,
        "state": "ACTIVE",
        "phase": "AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED" if member else "QUEUE_ACTIVE",
        "observed_at": _STAMP,
        "outcome": "Observación ficticia de CI",
        "queue_state": "UNKNOWN" if member else "QUEUE_ACTIVE",
        "queue_id": None if member else "cola-ficticia-compartida",
        "position": None if member else 235,
        "ahead": None if member else 234,
        "countdown": None,
        "has_target_url": False,
        "has_auth": member,
        "display_url": "https://example.invalid/sesion"
        if member
        else "https://example.invalid/cola",
    }


def _snapshots() -> list[dict[str, Any]]:
    initial: dict[str, Any] = {
        "version": 1,
        "observed_at": _STAMP,
        "context_limit": 50,
        "engines": [
            {
                "engine": engine,
                "state": "STOPPED",
                "can_start": True,
                "activation_id": None,
                "generation": 0,
                "member_id": None,
                "requested_contexts": 0,
                "counts": {"chromium": 0, "firefox": 0, "webkit": 0},
                "created": 0,
                "active": 0,
                "closed": 0,
                "failed": 0,
                "phase": "COLD",
                "updated_at": _STAMP,
                "sessions": [],
            }
            for engine in ENGINES
        ],
    }
    running = copy.deepcopy(initial)
    for index, engine in enumerate(ENGINES):
        running["engines"][index].update(
            state="RUNNING",
            can_start=False,
            activation_id=_ACTIVATIONS[engine],
            generation=_GENERATIONS[engine],
            member_id=_MEMBERS[1] if index else None,
            requested_contexts=25,
            counts=dict(
                zip(
                    ("chromium", "firefox", "webkit"),
                    (12, 7, 6) if index else (17, 4, 4),
                    strict=True,
                )
            ),
            created=1,
            active=1,
            phase="UNKNOWN" if index else "QUEUE_ACTIVE",
            sessions=[
                _session(
                    303 if index else 301, "webkit" if index else "chromium", member=bool(index)
                )
            ],
        )
    added = copy.deepcopy(running)
    added["engines"][0].update(created=2, active=2)
    added["engines"][0]["sessions"].append(_session(302, "firefox"))
    stopped_a = copy.deepcopy(added)
    stopped_a["engines"][0].update(
        state="STOPPED", can_start=True, active=0, closed=2, phase="STOPPED"
    )
    for session in stopped_a["engines"][0]["sessions"]:
        session.update(state="CLOSED", phase="STOPPED")
    stopped_both = copy.deepcopy(stopped_a)
    stopped_both["engines"][1].update(
        state="STOPPED", can_start=True, active=0, closed=1, phase="STOPPED"
    )
    for session in stopped_both["engines"][1]["sessions"]:
        session.update(state="CLOSED", phase="STOPPED")
    a_only = copy.deepcopy(initial)
    a_only["engines"][0] = copy.deepcopy(running["engines"][0])
    return [initial, a_only, running, added, stopped_a, stopped_both]


def make_fixture(source_sha: str) -> dict[str, Any]:
    _source(source_sha)
    from boca_socios.panel import engine_view
    from boca_socios.panel.members import MemberView
    from boca_socios.panel.private_ui import worker_activity
    from boca_socios.panel.worker_activity import WorkerActivitySnapshot

    snapshots = _snapshots()
    members = (
        MemberView(_MEMBERS[0], "Socio ficticio Uno", "u•••@example.invalid", True),
        MemberView(_MEMBERS[1], "Socio ficticio Dos", "d•••@example.invalid", True),
    )
    body = engine_view.page(snapshots[0], FORM_PROOF, _OPERATIONS, members, site_url_ready=True)
    redirect_documents = []
    for phase in (1, 2, 4, 5):
        redirected = engine_view.page(
            snapshots[phase], FORM_PROOF, _OPERATIONS, members, site_url_ready=True
        )
        redirect_documents.append(
            {
                "snapshot_phase": phase,
                "html": redirected.decode(),
                "html_sha256": hashlib.sha256(redirected).hexdigest(),
            }
        )
    activity = worker_activity(
        WorkerActivitySnapshot(_STAMP, "fixed_stages_only", "missing", ()),
        engine_snapshot=snapshots[2],
        members=members,
    )
    fixture = {
        "schema": 3,
        "source_sha": source_sha,
        "html": body.decode(),
        "csp": engine_view.csp(),
        "html_sha256": hashlib.sha256(body).hexdigest(),
        "snapshots": snapshots,
        "redirect_documents": redirect_documents,
        "activity_document": {
            "snapshot_phase": 2,
            "html": activity.decode(),
            "html_sha256": hashlib.sha256(activity).hexdigest(),
        },
    }
    validate_fixture(fixture, source_sha)
    return fixture


def validate_fixture(value: object, source_sha: str) -> dict[str, Any]:
    _source(source_sha)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "source_sha",
            "html",
            "csp",
            "html_sha256",
            "snapshots",
            "redirect_documents",
            "activity_document",
        }
        or type(value["schema"]) is not int
        or value["schema"] != 3
        or value["source_sha"] != source_sha
        or not isinstance(value["html"], str)
        or not 1 <= len(value["html"].encode()) <= 100_000
        or value["html_sha256"] != hashlib.sha256(value["html"].encode()).hexdigest()
        or not isinstance(value["csp"], str)
        or not 1 <= len(value["csp"]) <= 8000
        or any(
            part not in value["csp"]
            for part in (
                "default-src 'none'",
                "frame-ancestors 'none'",
                "connect-src 'self'",
                "form-action 'self'",
            )
        )
        # Exact fixed snapshots also exclude bearer fields, URL queries and
        # runtime/member/event input. They are never read from the host.
        or value["snapshots"] != _snapshots()
        or not isinstance(value["redirect_documents"], list)
        or len(value["redirect_documents"]) != 4
    ):
        raise ValueError("offline_fixture_unverified")
    for document, phase in zip(
        [*value["redirect_documents"], value["activity_document"]], (1, 2, 4, 5, 2), strict=True
    ):
        if (
            not isinstance(document, dict)
            or set(document) != {"snapshot_phase", "html", "html_sha256"}
            or type(document["snapshot_phase"]) is not int
            or document["snapshot_phase"] != phase
            or not isinstance(document["html"], str)
            or not 1 <= len(document["html"].encode()) <= 100_000
            or document["html_sha256"] != hashlib.sha256(document["html"].encode()).hexdigest()
        ):
            raise ValueError("offline_fixture_unverified")
    if len(_json(value)) > _MAX_FIXTURE:
        raise ValueError("offline_fixture_unverified")
    return value


def fixture_digest(fixture: dict[str, Any]) -> str:
    return hashlib.sha256(_json(fixture)).hexdigest()


def post_url(operation: str) -> str:
    if operation not in POST_ORDER:
        raise ValueError("offline_operation_unverified")
    engine, action = operation.split(":")
    return f"{PAGE_URL}/motores/{engine}/{'iniciar' if action == 'start' else 'detener'}"


def expected_post_fields(operation: str) -> dict[str, str]:
    post_url(operation)
    engine, action = operation.split(":")
    fields = {"csrf": FORM_PROOF, "operation_id": _OPERATIONS[operation]}
    if action == "start":
        counts = (17, 4, 4) if engine == ENGINES[0] else (12, 7, 6)
        fields.update(zip(("chromium", "firefox", "webkit"), map(str, counts), strict=True))
        if engine == ENGINES[1]:
            fields["member_id"] = _MEMBERS[1]
    else:
        fields.update(activation_id=_ACTIVATIONS[engine], generation=str(_GENERATIONS[engine]))
    return fields


def verify_post(url: str, origin: str | None, data: str | None) -> str:
    operation = next((item for item in POST_ORDER if post_url(item) == url), None)
    if operation is None or origin != ORIGIN or not isinstance(data, str) or len(data) > 2048:
        raise ValueError("native_form_unverified")
    pairs = parse_qsl(data, keep_blank_values=True, strict_parsing=True, max_num_fields=6)
    fields = dict(pairs)
    if len(fields) != len(pairs) or fields != expected_post_fields(operation):
        raise ValueError("native_form_unverified")
    return operation


def _offline_identity() -> None:
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10002,) * 4:
        raise RuntimeError("offline_browser_identity_unverified")
    interfaces = socket.if_nameindex()
    if len(interfaces) != 1 or interfaces[0][1] != "lo":
        raise RuntimeError("offline_network_namespace_unverified")


class _FixtureRejected(ValueError):
    def __init__(self, status: int = 400) -> None:
        super().__init__("offline_fixture_unverified")
        self.status = status


class _BoundedRequestReader:
    """Bound the real stdlib parser before it can consume unbounded headers."""

    def __init__(self, reader: Any) -> None:
        self.reader = reader
        self.total = 0
        self.header_lines = 0
        self.first = True

    def readline(self, _limit: int = -1) -> bytes:
        line = self.reader.readline(2049)
        self.total += len(line)
        if len(line) > 2048 or self.total > 8192:
            raise _FixtureRejected()
        if self.first:
            self.first = False
            if line and re.fullmatch(rb"[A-Z]+ [^\x00-\x20\x7f]+ HTTP/1\.[01]\r\n", line) is None:
                raise _FixtureRejected()
        elif line != b"\r\n":
            self.header_lines += 1
            if (
                self.header_lines > 64
                or not line.endswith(b"\r\n")
                or re.fullmatch(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+:[^\r\n]*\r\n", line) is None
            ):
                raise _FixtureRejected()
        return line

    def read(self, size: int) -> bytes:
        if not 0 <= size <= 2048:
            raise _FixtureRejected()
        return self.reader.read(size)

    def close(self) -> None:
        self.reader.close()


class _FixtureService:
    """One disposable loopback fixture, with no application or owner state."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture
        self.lock = Lock()
        self.stopping = Event()
        self.phase = 0
        self.documents = self.snapshots = self.rejected = 0
        self.activity_documents = self.activity_snapshots = 0
        self.posts: list[str] = []
        self.active: socket.socket | None = None
        self.server: _FixtureHTTPServer | None = None
        self.thread: Thread | None = None

    def counters(self) -> dict[str, int]:
        with self.lock:
            return {
                "snapshot_phase": self.phase,
                "documents": self.documents,
                "snapshots": self.snapshots,
                "native_posts": len(self.posts),
                "rejected": self.rejected,
                "activity_documents": self.activity_documents,
                "activity_snapshots": self.activity_snapshots,
            }

    def operations(self) -> list[str]:
        with self.lock:
            return list(self.posts)

    def reject(self) -> None:
        with self.lock:
            if not self.stopping.is_set():
                self.rejected = 1
                self.stopping.set()

    def advance_poll(self) -> None:
        with self.lock:
            if self.stopping.is_set() or (self.phase, self.documents, len(self.posts)) != (2, 3, 2):
                raise RuntimeError("offline_fixture_unverified")
            self.phase = 3

    def respond(
        self, method: str, path: str, headers: Any, body: bytes
    ) -> tuple[int, dict[str, str], bytes]:
        with self.lock:
            if self.stopping.is_set():
                raise _FixtureRejected(503)
            if self.documents + self.activity_documents + self.snapshots + len(self.posts) >= 34:
                raise _FixtureRejected(429)
            if headers.get("origin") not in (None, ORIGIN):
                raise _FixtureRejected(403)
            if method == "GET" and path == "/control":
                if self.documents != len(self.posts) or self.documents >= 5:
                    raise _FixtureRejected()
                document = (
                    self.fixture
                    if not self.posts
                    else self.fixture["redirect_documents"][len(self.posts) - 1]
                )
                self.documents += 1
                return (
                    200,
                    {
                        "Content-Type": "text/html; charset=utf-8",
                        "Content-Security-Policy": self.fixture["csp"],
                        "Referrer-Policy": "same-origin",
                    },
                    document["html"].encode(),
                )
            if method == "GET" and path == "/control/actividad":
                if self.phase != 2 or self.documents != 3 or self.activity_documents != 0:
                    raise _FixtureRejected()
                self.activity_documents += 1
                return (
                    200,
                    {
                        "Content-Type": "text/html; charset=utf-8",
                        "Content-Security-Policy": self.fixture["csp"],
                        "Referrer-Policy": "same-origin",
                    },
                    self.fixture["activity_document"]["html"].encode(),
                )
            if method == "GET" and path in {"/control/motores.json", "/control/actividad.json"}:
                if self.snapshots >= 24:
                    raise _FixtureRejected(429)
                if not self.documents:
                    raise _FixtureRejected()
                self.snapshots += 1
                if path == "/control/actividad.json":
                    if self.activity_documents != 1:
                        raise _FixtureRejected()
                    self.activity_snapshots += 1
                    return (
                        200,
                        {"Content-Type": "application/json"},
                        _json(
                            {
                                "observed_at": _STAMP,
                                "browser_detail": "fixed_stages_only",
                                "chromium_telemetry": "missing",
                                "events": [],
                            }
                        ),
                    )
                return (
                    200,
                    {"Content-Type": "application/json"},
                    _json(self.fixture["snapshots"][self.phase]),
                )
            if method == "POST":
                if headers.get("origin") != ORIGIN:
                    raise _FixtureRejected(403)
                if headers.get("content-type") != "application/x-www-form-urlencoded":
                    raise _FixtureRejected()
                try:
                    operation = verify_post(
                        ORIGIN + path, headers.get("origin"), body.decode("ascii")
                    )
                except (UnicodeError, ValueError):
                    raise _FixtureRejected() from None
                if (
                    len(self.posts) >= 4
                    or operation != POST_ORDER[len(self.posts)]
                    or self.documents != len(self.posts) + 1
                    or self.phase != (0, 1, 3, 4)[len(self.posts)]
                ):
                    raise _FixtureRejected()
                self.posts.append(operation)
                self.phase = (1, 2, 4, 5)[len(self.posts) - 1]
                return 303, {"Location": "/control"}, b""
            raise _FixtureRejected(405 if method not in {"GET", "POST"} else 400)

    def start(self) -> None:
        # Never create a listener outside the approved non-root, network-none
        # CI container. Binding is local to that disposable namespace only.
        _offline_identity()
        validate_fixture(self.fixture, self.fixture["source_sha"])
        if self.server is not None or self.thread is not None or self.stopping.is_set():
            raise RuntimeError("offline_fixture_unverified")
        self.server = _FixtureHTTPServer(self)
        self.server.server_bind()
        self.server.server_activate()
        if self.server.socket.getsockname() != ("127.0.0.1", 8443):
            raise RuntimeError("offline_fixture_unverified")
        self.thread = Thread(target=self._serve, name="offline-engine-fixture", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        try:
            while not self.stopping.is_set():
                assert self.server is not None
                self.server.handle_request()
        except Exception:
            self.reject()

    def close(self) -> None:
        with self.lock:
            self.stopping.set()
            active, server, thread = self.active, self.server, self.thread
        failed = False
        if active is not None:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError as error:
                # shutdown_request() may have just closed this accepted
                # socket. Only these two shutdown results can be benign;
                # descriptor closure and a dead thread remain mandatory.
                if error.errno not in {errno.EBADF, errno.ENOTCONN}:
                    failed = True
            except Exception:
                failed = True
            try:
                active.close()
            except Exception:
                failed = True
        if server is not None:
            try:
                server.server_close()
            except Exception:
                failed = True
        if thread is not None:
            try:
                if thread.ident is not None:
                    thread.join(timeout=5)
                if thread.is_alive():
                    failed = True
            except Exception:
                failed = True
        # socket.makefile() retains a reference after socket.close(). The
        # handler releases that reference while draining, so certify the final
        # descriptors only after the bounded join, even if another close failed.
        if active is not None:
            try:
                if active.fileno() != -1:
                    failed = True
            except Exception:
                failed = True
        if server is not None:
            try:
                if server.socket.fileno() != -1:
                    failed = True
            except Exception:
                failed = True
        if failed:
            raise RuntimeError("offline_fixture_close_unverified")


class _FixtureHTTPServer(HTTPServer):
    allow_reuse_address = True
    timeout = 0.05

    def __init__(self, service: _FixtureService) -> None:
        self.service = service
        super().__init__(("127.0.0.1", 8443), _FixtureRequestHandler, bind_and_activate=False)

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        try:
            connection.settimeout(5)
            with self.service.lock:
                if self.service.stopping.is_set():
                    raise OSError("offline_fixture_unverified")
                self.service.active = connection
        except Exception:
            self.service.reject()
            connection.close()
            raise
        return connection, address

    def shutdown_request(self, request: socket.socket) -> None:
        try:
            super().shutdown_request(request)
        finally:
            with self.service.lock:
                if self.service.active is request:
                    self.service.active = None

    def handle_error(self, _request: Any, _address: Any) -> None:
        # The stdlib default prints the traceback, which could contain a URL.
        self.service.reject()


class _FixtureRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 5

    def setup(self) -> None:
        super().setup()
        self.rfile = _BoundedRequestReader(self.rfile)

    def handle(self) -> None:
        # Establish a safe response version even when the bounded reader
        # rejects the request line before stdlib parse_request() is called.
        self.request_version = "HTTP/1.1"
        self.command = None
        if self.server.service.stopping.is_set():
            self.send_error(503)
            return
        try:
            super().handle()
        except _FixtureRejected as error:
            self.send_error(error.status)
        except Exception:
            self.send_error(400)

    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def log_error(self, _format: str, *_args: Any) -> None:
        # handle_one_request() catches a socket timeout itself. Its normal
        # logging path must also close admission, without printing arguments.
        self.server.service.reject()

    def send_error(self, code: int, _message: Any = None, _explain: Any = None) -> None:
        status = 405 if code == 501 else code if code in {400, 403, 405, 429, 503} else 400
        self.server.service.reject()
        try:
            self._emit(
                status,
                {"Content-Type": "text/plain; charset=utf-8"},
                b"Fixture request rejected.\n",
            )
        except Exception:
            self.close_connection = True

    def _emit(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.close_connection = True
        self.send_response_only(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _respond(self) -> None:
        for name in (
            "host",
            "origin",
            "content-length",
            "content-type",
            "transfer-encoding",
            "expect",
        ):
            if len(self.headers.get_all(name, [])) > 1:
                raise _FixtureRejected()
        if (
            self.headers.get("host") != "localhost:8443"
            or self.headers.get("transfer-encoding") is not None
            or self.headers.get("expect") is not None
            or self.requestline.split(" ")[1] != self.path
        ):
            raise _FixtureRejected()
        size = self.headers.get("content-length")
        if size is None:
            if self.command == "POST":
                raise _FixtureRejected()
            size = "0"
        if re.fullmatch(r"0|[1-9][0-9]{0,3}", size) is None or int(size) > 2048:
            raise _FixtureRejected()
        if self.command == "GET" and size != "0":
            raise _FixtureRejected()
        body = self.rfile.read(int(size))
        if len(body) != int(size):
            raise _FixtureRejected()
        status, headers, output = self.server.service.respond(
            self.command, self.path, self.headers, body
        )
        self._emit(status, headers, output)

    def do_GET(self) -> None:
        self._respond()

    def do_POST(self) -> None:
        self._respond()


async def _submit(page: Page, operation: str) -> None:
    target = post_url(operation)
    async with (
        page.expect_response(
            lambda response: (
                response.url == target
                and response.request.method == "POST"
                and response.request.is_navigation_request()
            )
        ) as posted,
        page.expect_response(
            lambda response: (
                response.url == PAGE_URL
                and response.request.method == "GET"
                and response.request.is_navigation_request()
                and response.request.redirected_from is not None
                and response.request.redirected_from.url == target
                and response.request.redirected_from.method == "POST"
            )
        ) as redirected,
    ):
        await page.locator("#" + operation.replace(":", "-") + "-button").click()
    response, landing = await posted.value, await redirected.value
    if (
        response.status != 303
        or response.headers.get("location") != "/control"
        or landing.status != 200
        or landing.request.redirected_from is not response.request
    ):
        raise RuntimeError("native_form_unverified")
    await page.wait_for_load_state("load")
    await page.wait_for_function(
        "() => document.getElementById('engines-live').textContent !== 'Último estado disponible.'"
    )
    if page.url != PAGE_URL:
        raise RuntimeError("offline_document_changed")


async def _refresh(page: Page) -> None:
    async with page.expect_response(
        lambda response: response.url == SNAPSHOT_URL and response.request.method == "GET"
    ) as refreshed:
        await page.locator("#engines-refresh").click()
    response = await refreshed.value
    if response.status != 200:
        raise RuntimeError("live_snapshot_projection_unverified")
    # Response.body() waits for completion without Response.finished()'s
    # uncancelled target-close task in the pinned Python Playwright 1.64.1.
    await response.body()


async def _viewport(
    browser: Browser, fixture: dict[str, Any], width: int, height: int
) -> dict[str, Any]:

    service = _FixtureService(fixture)
    errors: list[object] = []
    context: BrowserContext | None = None
    page: Page | None = None
    activity: Page | None = None
    failure: BaseException | None = None
    failure_counts: dict[str, int] | None = None
    failure_state: dict[str, object] | None = None
    step = "context_create"

    def counters() -> dict[str, int]:
        return {**service.counters(), "page_errors": len(errors)}

    try:
        context = await browser.new_context(
            accept_downloads=False,
            service_workers="block",
            viewport={"width": width, "height": height},
        )
        step = "context_setup"
        context.set_default_timeout(5000)
        step = "fixture_start"
        service.start()

        async def route_document(route: Route) -> None:
            request = route.request
            allowed = request.method == "GET" and request.url in {
                PAGE_URL,
                SNAPSHOT_URL,
                ACTIVITY_URL,
                ACTIVITY_SNAPSHOT_URL,
            }
            allowed |= (
                request.url in {post_url(operation) for operation in POST_ORDER}
                and request.method == "POST"
                and request.is_navigation_request()
                and request.resource_type == "document"
            )
            if allowed and not service.stopping.is_set():
                # Native redirects bypass Chromium's route interception. Both
                # the intercepted request and its redirect reach the same
                # bounded loopback handler inside the network-none container.
                await route.continue_()
            else:
                service.reject()
                await route.abort()

        step = "route_install"
        await context.route("**/*", route_document)
        step = "page_create"
        page = await context.new_page()

        def record_page_error(error: object) -> None:
            errors.append(error)

        step = "page_error_hook"
        page.on("pageerror", record_page_error)
        step = "document_load"
        await page.goto(PAGE_URL, wait_until="load", timeout=10_000)
        step = "initial_timestamp"
        await page.wait_for_function(
            "() => document.getElementById('engines-checked').textContent.includes('2020-01-01')"
        )
        step = "initial_live_poll"
        await page.wait_for_function(
            "() => document.getElementById('engines-live').textContent !== 'Último estado disponible.'"
        )
        step = "initial_start"
        for engine in ENGINES:
            if await page.locator(f"#{engine}-start-button").is_disabled():
                raise RuntimeError("initial_start_unverified")
        step = "required_member"
        await page.locator("#browsers_members-start-button").click()
        if service.operations() or not await page.locator("#browsers_members-member").evaluate(
            "node => node.matches(':invalid')"
        ):
            raise RuntimeError("required_member_unverified")
        step = "initial_inputs"
        for engine in ENGINES:
            await page.locator(f"#{engine}-start details > summary").click()
            fields = expected_post_fields(engine + ":start")
            for browser_name in ("chromium", "firefox", "webkit"):
                await page.locator(f"#{engine}-{browser_name}").fill(fields[browser_name])
        await page.locator("#browsers_members-member").select_option(_MEMBERS[1])
        step = "queues_start"
        await _submit(page, POST_ORDER[0])
        # A real POST/303/GET replaces the document, as the controller does.
        # Enter B's values on that new document before submitting its form.
        step = "members_inputs_after_redirect"
        await page.locator("#browsers_members-start details > summary").click()
        for browser_name in ("chromium", "firefox", "webkit"):
            await page.locator(f"#browsers_members-{browser_name}").fill(
                expected_post_fields(POST_ORDER[1])[browser_name]
            )
        await page.locator("#browsers_members-member").select_option(_MEMBERS[1])
        step = "members_start"
        await _submit(page, POST_ORDER[1])

        step = "running_refresh"
        await _refresh(page)
        step = "activity_create"
        activity = await context.new_page()
        activity.on("pageerror", record_page_error)
        step = "activity_load"
        await activity.goto(ACTIVITY_URL, wait_until="load", timeout=10_000)
        await activity.wait_for_function(
            "() => document.getElementById('engines-live').textContent !== 'Último estado disponible.'"
        )
        step = "running_rows"
        await activity.wait_for_function(
            "() => document.querySelectorAll('[data-session-id]').length === 2"
        )
        step = "initial_session"
        original_row = await activity.locator(
            f'[data-session-id="{_identity(301)}"]'
        ).element_handle()
        if original_row is None:
            raise RuntimeError("initial_session_unverified")
        step = "running_controls"
        for engine in ENGINES:
            if not await page.locator(f"#{engine}-start-button").is_disabled():
                raise RuntimeError("running_start_unverified")
            if await page.locator(f"#{engine}-stop-button").is_disabled():
                raise RuntimeError("running_stop_unverified")
        # Edits for the next activation must survive the genuine 5-second poll.
        step = "preserved_inputs_prepare"
        for engine in ENGINES:
            await page.locator(f"#{engine}-start details > summary").click()
        await page.locator("#queues_tokens-chromium").fill("19")
        await page.locator("#browsers_members-chromium").fill("11")
        await page.locator("#browsers_members-member").select_option(_MEMBERS[0])
        service.advance_poll()
        await _refresh(page)
        step = "live_rows_poll"
        await activity.bring_to_front()
        await activity.wait_for_function(
            "() => document.querySelectorAll('[data-session-id]').length === 3", timeout=7000
        )
        step = "session_preserved"
        if (
            not await original_row.evaluate("node => node.isConnected")
            or service.counters()["documents"] != 3
            or service.counters()["activity_documents"] != 1
        ):
            raise RuntimeError("existing_session_replaced")
        step = "live_projection"
        if (
            await page.locator("#queues_tokens-chromium").input_value() != "19"
            or await page.locator("#browsers_members-chromium").input_value() != "11"
            or await page.locator("#browsers_members-member").input_value() != _MEMBERS[0]
            or await page.locator("#browsers_members-current-member").get_attribute(
                "data-member-id"
            )
            != _MEMBERS[1]
            or await activity.locator("#engines-total-requested_contexts").inner_text() != "50"
            or await activity.locator("#engines-total-created").inner_text() != "3"
            or await activity.locator("#engines-total-active").inner_text() != "3"
            or await activity.locator("#queues_tokens-queues").inner_text() != "1"
        ):
            raise RuntimeError("live_snapshot_projection_unverified")
        step = "stop_fences"
        for engine in ENGINES:
            for name in ("activation_id", "generation"):
                actual = await page.locator(f'#{engine}-stop input[name="{name}"]').input_value()
                if actual != expected_post_fields(engine + ":stop")[name]:
                    raise RuntimeError("independent_stop_fence_unverified")
        step = "private_metadata"
        if (
            not await activity.locator("[data-field=inspect]").evaluate_all(
                "nodes => nodes.length === 3 && nodes.every(node => /^\\/control\\/sesiones\\/[0-9a-f-]{36}$/.test(node.getAttribute('href')))"
            )
            or await page.locator('input[type="password"]').count() != 0
            or await activity.locator('input[type="password"], form').count() != 0
        ):
            raise RuntimeError("private_metadata_projection_unverified")

        step = "queues_stop"
        await _submit(page, POST_ORDER[2])
        step = "queues_stopped_refresh"
        await _refresh(page)
        await _refresh(activity)
        await activity.wait_for_function(
            "() => document.getElementById('engines-total-active').textContent === '1'"
        )
        step = "queues_stopped_poll"
        await page.wait_for_function(
            "() => document.getElementById('queues_tokens-stop-button').disabled"
        )
        step = "independent_stop"
        if (
            await page.locator("#browsers_members-stop-button").is_disabled()
            or await page.locator("#queues_tokens-start-button").is_disabled()
            or not await page.locator("#browsers_members-start-button").is_disabled()
            or await activity.locator("#browsers_members-active").inner_text() != "1"
            or await activity.locator("#engines-total-active").inner_text() != "1"
        ):
            raise RuntimeError("independent_stop_projection_unverified")
        step = "layout"
        # Native details hide optional inputs/secondary links intentionally;
        # validate every visible target on both pages, including summaries.
        for view in (page, activity):
            await view.locator("body > details > summary").click()
            if view is page:
                for engine in ENGINES:
                    await view.locator(f"#{engine}-start details > summary").click()
            layout = await view.evaluate("""() => {
          const controls = Array.from(document.querySelectorAll('button, input:not([type=hidden]), select, a, summary'))
            .filter(node => node.getClientRects().length > 0);
          return {targets: controls.length > 12 && controls.every(node => {
            const box = node.getBoundingClientRect();
            return box.height >= 52 && box.left >= 0 && box.right <= innerWidth;
          }), overflow: document.documentElement.scrollWidth > innerWidth,
          height: document.documentElement.scrollHeight};
        }""")
            if not layout["targets"] or layout["overflow"] or layout["height"] > _MAX_HEIGHT:
                raise RuntimeError("accessible_layout_unverified")
        step = "screenshot"
        screenshot = await activity.screenshot(type="png", full_page=True, animations="disabled")
        step = "screenshot_verify"
        _png_dimensions(screenshot, width, height)
        step = "members_stop"
        await _submit(page, POST_ORDER[3])
        step = "members_stopped_refresh"
        await _refresh(page)
        await _refresh(activity)
        await activity.wait_for_function(
            "() => document.getElementById('engines-total-active').textContent === '0'"
        )
        step = "members_stopped_poll"
        await page.wait_for_function(
            "() => document.getElementById('browsers_members-stop-button').disabled"
        )
        step = "final_evidence"
        evidence = service.counters()
        posts = service.operations()
        if (
            evidence["documents"] != 5
            or evidence["activity_documents"] != 1
            or evidence["activity_snapshots"] < 1
            or not 9 <= evidence["snapshots"] <= 24
            or posts != list(POST_ORDER)
            or evidence["rejected"]
            or errors
        ):
            raise RuntimeError("offline_browser_evidence_unverified")
        step = "viewport_capture_encode"
        return {
            "width": width,
            "height": height,
            "document_requests": evidence["documents"] + evidence["activity_documents"],
            "snapshot_requests": evidence["snapshots"],
            "native_posts": posts,
            "other_requests": evidence["rejected"],
            "page_errors": len(errors),
            "checks": dict.fromkeys(CHECKS, True),
            "png_base64": base64.b64encode(screenshot).decode("ascii"),
        }
    except BaseException as error:
        failure = error
        failure_counts = counters()
        failure_state = _failure_state(error, browser, page)
        raise
    finally:
        cleanup = "NOT_CREATED"
        cleanup_error: BaseException | None = None
        try:
            if context is not None:
                await context.close()
                cleanup = "CLOSED"
        except BaseException as error:
            cleanup = "FAILED"
            if failure is None:
                failure = error
                failure_counts = counters()
                failure_state = _failure_state(error, browser, page)
                step = "context_close"
                cleanup_error = error
        try:
            service.close()
        except BaseException as error:
            cleanup = "FAILED"
            if failure is None:
                failure = error
                failure_counts = counters()
                failure_state = _failure_state(error, browser, page)
                step = "fixture_close"
                cleanup_error = error
        if failure is not None:
            print(
                _probe_failure_report(
                    step,
                    failure,
                    width=width,
                    height=height,
                    counts=failure_counts,
                    failure_state=failure_state,
                    cleanup=cleanup,
                ),
                file=sys.stderr,
            )
        if cleanup_error is not None:
            raise cleanup_error


async def run_offline(fixture: dict[str, Any], source_sha: str) -> dict[str, Any]:
    _offline_identity()
    validate_fixture(fixture, source_sha)
    from playwright.async_api import async_playwright

    failure: BaseException | None = None
    step = "playwright_start"
    try:
        async with async_playwright() as api:
            browser = None
            try:
                step = "browser_launch"
                browser = await api.chromium.launch(
                    headless=True,
                    chromium_sandbox=True,
                    timeout=10_000,
                    args=["--disable-background-networking"],
                )
                step = "browser_proof"
                viewports = [
                    await _viewport(browser, fixture, width, height)
                    for width, height, _ in VIEWPORTS
                ]
            except BaseException as error:
                failure = error
                if step == "browser_launch":
                    print(_probe_failure_report(step, error), file=sys.stderr)
                raise
            finally:
                try:
                    if browser is not None:
                        await browser.close()
                except BaseException as error:
                    print(
                        _probe_failure_report("browser_close", error, cleanup="FAILED"),
                        file=sys.stderr,
                    )
                    if failure is None:
                        failure = error
                        raise
                finally:
                    step = "playwright_close"
    except BaseException as error:
        if failure is not None and error is not failure:
            print(
                _probe_failure_report("playwright_close", error, cleanup="FAILED"),
                file=sys.stderr,
            )
            raise failure from None
        if failure is None:
            print(
                _probe_failure_report(
                    step,
                    error,
                    cleanup="FAILED" if step == "playwright_close" else "NOT_CREATED",
                ),
                file=sys.stderr,
            )
        raise
    return {
        "schema": 1,
        "mode": "OFFLINE_SYNTHETIC_ENGINE_UI",
        "source_sha": source_sha,
        "fixture_sha256": fixture_digest(fixture),
        "state": "PASS",
        "network": "none",
        "host_checked": False,
        "physical_device_checked": False,
        "viewports": viewports,
    }


def _png_dimensions(raw: bytes, width: int, minimum_height: int) -> tuple[int, int]:
    if not 57 <= len(raw) <= _MAX_PNG or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("screenshot_unverified")
    offset = 8
    kinds: list[bytes] = []
    dimensions = None
    while offset + 12 <= len(raw):
        size = struct.unpack(">I", raw[offset : offset + 4])[0]
        kind = raw[offset + 4 : offset + 8]
        end = offset + size + 12
        if end > len(raw) or kind not in {
            b"IHDR",
            b"IDAT",
            b"IEND",
            b"sRGB",
            b"iCCP",
            b"gAMA",
            b"cHRM",
            b"pHYs",
        }:
            raise ValueError("screenshot_unverified")
        data = raw[offset + 8 : end - 4]
        if zlib.crc32(kind + data) != struct.unpack(">I", raw[end - 4 : end])[0]:
            raise ValueError("screenshot_unverified")
        if kind == b"IHDR":
            if kinds or size != 13:
                raise ValueError("screenshot_unverified")
            actual_width, actual_height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            if (
                actual_width != width
                or not minimum_height <= actual_height <= _MAX_HEIGHT
                or depth != 8
                or color not in (2, 6)
                or (compression, filtering, interlace) != (0, 0, 0)
            ):
                raise ValueError("screenshot_unverified")
            dimensions = (actual_width, actual_height)
        if kind == b"IEND" and (size or end != len(raw)):
            raise ValueError("screenshot_unverified")
        kinds.append(kind)
        offset = end
    if (
        offset != len(raw)
        or not kinds
        or kinds[-1] != b"IEND"
        or b"IDAT" not in kinds
        or dimensions is None
    ):
        raise ValueError("screenshot_unverified")
    return dimensions


def write_artifacts(
    capture: object, fixture: dict[str, Any], source_sha: str, output: Path
) -> dict[str, Any]:
    validate_fixture(fixture, source_sha)
    if (
        not isinstance(capture, dict)
        or set(capture)
        != {
            "schema",
            "mode",
            "source_sha",
            "fixture_sha256",
            "state",
            "network",
            "host_checked",
            "physical_device_checked",
            "viewports",
        }
        or type(capture["schema"]) is not int
        or capture["schema"] != 1
        or capture["mode"] != "OFFLINE_SYNTHETIC_ENGINE_UI"
        or capture["state"] != "PASS"
        or capture["source_sha"] != source_sha
        or capture["fixture_sha256"] != fixture_digest(fixture)
        or capture["network"] != "none"
        or capture["host_checked"] is not False
        or capture["physical_device_checked"] is not False
        or not isinstance(capture["viewports"], list)
        or len(capture["viewports"]) != 2
    ):
        raise ValueError("offline_capture_unverified")
    report = {key: value for key, value in capture.items() if key != "viewports"}
    report.update(
        html_sha256=fixture["html_sha256"], captured_state="A_STOPPED_B_RUNNING", viewports=[]
    )
    images = []
    for view, (width, height, filename) in zip(capture["viewports"], VIEWPORTS, strict=True):
        if (
            not isinstance(view, dict)
            or set(view)
            != {
                "width",
                "height",
                "document_requests",
                "snapshot_requests",
                "native_posts",
                "other_requests",
                "page_errors",
                "checks",
                "png_base64",
            }
            or type(view["width"]) is not int
            or view["width"] != width
            or type(view["height"]) is not int
            or view["height"] != height
            or type(view["document_requests"]) is not int
            or view["document_requests"] != 6
            or type(view["snapshot_requests"]) is not int
            or not 9 <= view["snapshot_requests"] <= 24
            or view["native_posts"] != list(POST_ORDER)
            or any(
                type(view[key]) is not int or view[key] != 0
                for key in ("other_requests", "page_errors")
            )
            or not isinstance(view["checks"], dict)
            or set(view["checks"]) != set(CHECKS)
            or any(value is not True for value in view["checks"].values())
            or not isinstance(view["png_base64"], str)
            or len(view["png_base64"]) > 4 * ((_MAX_PNG + 2) // 3)
        ):
            raise ValueError("offline_viewport_unverified")
        raw = base64.b64decode(view["png_base64"], validate=True)
        _, actual_height = _png_dimensions(raw, width, height)
        images.append((filename, raw))
        verified = {key: value for key, value in view.items() if key != "png_base64"}
        verified.update(
            screenshot=filename,
            screenshot_height=actual_height,
            screenshot_bytes=len(raw),
            screenshot_sha256=hashlib.sha256(raw).hexdigest(),
        )
        report["viewports"].append(verified)
    # No filesystem output is created before every field and both PNGs pass.
    output.mkdir(mode=0o700)
    for filename, raw in [*images, ("report.json", _json(report) + b"\n")]:
        with (output / filename).open("xb") as stream:
            stream.write(raw)
    return report


def _unique(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in entries:
        if key in result:
            raise ValueError("duplicate_json_field")
        result[key] = value
    return result


def _read(path: Path, maximum: int) -> Any:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
            raise ValueError("offline_file_unverified")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) != info.st_size:
            raise ValueError("offline_file_unverified")
    finally:
        os.close(fd)
    return json.loads(raw, object_pairs_hook=_unique)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    phase = "arguments"
    try:
        if len(argv) == 2 and argv[0] == "--make-fixture":
            phase = "fixture_render"
            sys.stdout.buffer.write(_json(make_fixture(argv[1])) + b"\n")
        elif len(argv) == 3 and argv[0] == "--run-offline-fixture":
            phase = "fixture_read"
            fixture = validate_fixture(_read(Path(argv[1]), _MAX_FIXTURE), argv[2])
            phase = "browser_proof"
            capture = asyncio.run(asyncio.wait_for(run_offline(fixture, argv[2]), timeout=75))
            phase = "capture_encode"
            raw = _json(capture)
            if len(raw) > _MAX_CAPTURE:
                raise ValueError("offline_capture_too_large")
            sys.stdout.buffer.write(raw + b"\n")
        elif len(argv) == 5 and argv[0] == "--verify-capture":
            phase = "fixture_read"
            fixture = validate_fixture(_read(Path(argv[2]), _MAX_FIXTURE), argv[3])
            phase = "capture_read"
            capture = _read(Path(argv[1]), _MAX_CAPTURE)
            phase = "artifact_verify"
            write_artifacts(capture, fixture, argv[3], Path(argv[4]))
            print(
                f"BOCA_ENGINE_UI_OFFLINE state=PASS source_sha={argv[3]} viewports=2 network=none host=UNTOUCHED device=UNVERIFIED"
            )
        else:
            raise ValueError("explicit_offline_mode_required")
    except Exception as error:
        print(_failure_report(phase, error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
