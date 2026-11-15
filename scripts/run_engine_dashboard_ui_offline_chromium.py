"""Candidate-only dashboard proof in network-none Chromium, with fixed public data.

The controller image renders the actual page; the browser image needs only this
stdlib fixture reader and Playwright. The runner verifies bounded screenshots
before publishing them. No runtime database, owner session or provider is used.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import os
import re
import socket
import stat
import struct
import sys
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Route

ORIGIN = "http://localhost:8443"
PAGE_URL = ORIGIN + "/control"
SNAPSHOT_URL = PAGE_URL + "/motores.json"
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
_MAX_FIXTURE = 160_000
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
    return [initial, running, added, stopped_a, stopped_both]


def make_fixture(source_sha: str) -> dict[str, Any]:
    _source(source_sha)
    from boca_socios.panel import engine_view
    from boca_socios.panel.members import MemberView

    snapshots = _snapshots()
    members = (
        MemberView(_MEMBERS[0], "Socio ficticio Uno", "u•••@example.invalid", True),
        MemberView(_MEMBERS[1], "Socio ficticio Dos", "d•••@example.invalid", True),
    )
    body = engine_view.page(snapshots[0], FORM_PROOF, _OPERATIONS, members, site_url_ready=True)
    fixture = {
        "schema": 1,
        "source_sha": source_sha,
        "html": body.decode(),
        "csp": engine_view.csp(),
        "html_sha256": hashlib.sha256(body).hexdigest(),
        "snapshots": snapshots,
    }
    validate_fixture(fixture, source_sha)
    return fixture


def validate_fixture(value: object, source_sha: str) -> dict[str, Any]:
    _source(source_sha)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "source_sha", "html", "csp", "html_sha256", "snapshots"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
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
    ):
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


async def _submit(page: Page, operation: str) -> None:
    async with page.expect_response(
        lambda response: response.url == post_url(operation) and response.request.method == "POST"
    ):
        await page.locator("#" + operation.replace(":", "-") + "-button").click()
    if page.url != PAGE_URL:
        raise RuntimeError("offline_document_changed")


async def _viewport(
    browser: Browser, fixture: dict[str, Any], width: int, height: int
) -> dict[str, Any]:

    phase = 0
    documents = snapshots = rejected = 0
    posts: list[str] = []
    errors: list[object] = []
    context = await browser.new_context(
        accept_downloads=False, service_workers="block", viewport={"width": width, "height": height}
    )
    context.set_default_timeout(5000)
    try:

        async def route_document(route: Route) -> None:
            nonlocal documents, snapshots, rejected
            request = route.request
            if request.url == PAGE_URL and request.method == "GET" and documents == 0:
                documents += 1
                await route.fulfill(
                    status=200,
                    body=fixture["html"],
                    headers={
                        "Content-Type": "text/html; charset=utf-8",
                        "Content-Security-Policy": fixture["csp"],
                        "Cache-Control": "no-store",
                        "Referrer-Policy": "same-origin",
                    },
                )
                return
            if request.url == SNAPSHOT_URL and request.method == "GET" and snapshots < 24:
                snapshots += 1
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=_json(fixture["snapshots"][phase]),
                )
                return
            if (
                request.method == "POST"
                and request.is_navigation_request()
                and request.resource_type == "document"
            ):
                try:
                    headers = await request.all_headers()
                    if headers.get("content-type") != "application/x-www-form-urlencoded":
                        raise ValueError("native_content_type_unverified")
                    operation = verify_post(request.url, headers.get("origin"), request.post_data)
                    if len(posts) >= len(POST_ORDER) or operation != POST_ORDER[len(posts)]:
                        raise ValueError("native_operation_order_unverified")
                    posts.append(operation)
                    # 204 preserves the current DOM so all four actual native
                    # forms can be exercised without manufacturing a backend.
                    await route.fulfill(status=204, body="")
                    return
                except ValueError:
                    pass
            rejected += 1
            await route.abort()

        await context.route("**/*", route_document)
        page = await context.new_page()
        page.on("pageerror", errors.append)
        await page.goto(PAGE_URL, wait_until="load", timeout=10_000)
        await page.wait_for_function(
            "document.getElementById('engines-checked').textContent.includes('2020-01-01')"
        )
        await page.wait_for_function(
            "document.getElementById('engines-live').textContent !== 'Último estado disponible.'"
        )
        for engine in ENGINES:
            if await page.locator(f"#{engine}-start-button").is_disabled():
                raise RuntimeError("initial_start_unverified")
        await page.locator("#browsers_members-start-button").click()
        if posts or not await page.locator("#browsers_members-member").evaluate(
            "node => node.matches(':invalid')"
        ):
            raise RuntimeError("required_member_unverified")
        for engine in ENGINES:
            fields = expected_post_fields(engine + ":start")
            for browser_name in ("chromium", "firefox", "webkit"):
                await page.locator(f"#{engine}-{browser_name}").fill(fields[browser_name])
        await page.locator("#browsers_members-member").select_option(_MEMBERS[1])
        await _submit(page, POST_ORDER[0])
        await _submit(page, POST_ORDER[1])

        phase = 1
        await page.locator("#engines-refresh").click()
        await page.wait_for_function("document.querySelectorAll('[data-session-id]').length === 2")
        original_row = await page.locator(f'[data-session-id="{_identity(301)}"]').element_handle()
        if original_row is None:
            raise RuntimeError("initial_session_unverified")
        for engine in ENGINES:
            if not await page.locator(f"#{engine}-start-button").is_disabled():
                raise RuntimeError("running_start_unverified")
            if await page.locator(f"#{engine}-stop-button").is_disabled():
                raise RuntimeError("running_stop_unverified")
        # Edits for the next activation must survive the genuine 5-second poll.
        await page.locator("#queues_tokens-chromium").fill("19")
        await page.locator("#browsers_members-chromium").fill("11")
        await page.locator("#browsers_members-member").select_option(_MEMBERS[0])
        phase = 2
        await page.wait_for_function(
            "document.querySelectorAll('[data-session-id]').length === 3", timeout=7000
        )
        if not await original_row.evaluate("node => node.isConnected"):
            raise RuntimeError("existing_session_replaced")
        if (
            await page.locator("#queues_tokens-chromium").input_value() != "19"
            or await page.locator("#browsers_members-chromium").input_value() != "11"
            or await page.locator("#browsers_members-member").input_value() != _MEMBERS[0]
            or await page.locator("#browsers_members-current-member").get_attribute(
                "data-member-id"
            )
            != _MEMBERS[1]
            or await page.locator("#engines-total-requested_contexts").inner_text() != "50"
            or await page.locator("#engines-total-created").inner_text() != "3"
            or await page.locator("#engines-total-active").inner_text() != "3"
            or await page.locator("#queues_tokens-queues").inner_text() != "1"
        ):
            raise RuntimeError("live_snapshot_projection_unverified")
        for engine in ENGINES:
            for name in ("activation_id", "generation"):
                actual = await page.locator(f'#{engine}-stop input[name="{name}"]').input_value()
                if actual != expected_post_fields(engine + ":stop")[name]:
                    raise RuntimeError("independent_stop_fence_unverified")
        if (
            not await page.locator("[data-field=inspect]").evaluate_all(
                "nodes => nodes.length === 3 && nodes.every(node => /^\\/control\\/sesiones\\/[0-9a-f-]{36}$/.test(node.getAttribute('href')))"
            )
            or await page.locator('input[type="password"]').count() != 0
        ):
            raise RuntimeError("private_metadata_projection_unverified")

        await _submit(page, POST_ORDER[2])
        phase = 3
        await page.locator("#engines-refresh").click()
        await page.wait_for_function(
            "document.getElementById('queues_tokens-stop-button').disabled"
        )
        if (
            await page.locator("#browsers_members-stop-button").is_disabled()
            or await page.locator("#queues_tokens-start-button").is_disabled()
            or not await page.locator("#browsers_members-start-button").is_disabled()
            or await page.locator("#browsers_members-active").inner_text() != "1"
            or await page.locator("#engines-total-active").inner_text() != "1"
        ):
            raise RuntimeError("independent_stop_projection_unverified")
        layout = await page.evaluate("""() => {
          const controls = Array.from(document.querySelectorAll('button, input:not([type=hidden]), select, a'));
          return {targets: controls.length > 12 && controls.every(node => {
            const box = node.getBoundingClientRect();
            return box.height >= 52 && box.left >= 0 && box.right <= innerWidth;
          }), overflow: document.documentElement.scrollWidth > innerWidth,
          height: document.documentElement.scrollHeight};
        }""")
        if not layout["targets"] or layout["overflow"] or layout["height"] > _MAX_HEIGHT:
            raise RuntimeError("accessible_layout_unverified")
        screenshot = await page.screenshot(type="png", full_page=True, animations="disabled")
        _png_dimensions(screenshot, width, height)
        await _submit(page, POST_ORDER[3])
        phase = 4
        await page.locator("#engines-refresh").click()
        await page.wait_for_function(
            "document.getElementById('browsers_members-stop-button').disabled"
        )
        if (
            documents != 1
            or not 4 <= snapshots <= 24
            or posts != list(POST_ORDER)
            or rejected
            or errors
        ):
            raise RuntimeError("offline_browser_evidence_unverified")
        return {
            "width": width,
            "height": height,
            "document_requests": documents,
            "snapshot_requests": snapshots,
            "native_posts": posts,
            "other_requests": rejected,
            "page_errors": len(errors),
            "checks": dict.fromkeys(CHECKS, True),
            "png_base64": base64.b64encode(screenshot).decode("ascii"),
        }
    finally:
        await context.close()


async def run_offline(fixture: dict[str, Any], source_sha: str) -> dict[str, Any]:
    _offline_identity()
    validate_fixture(fixture, source_sha)
    from playwright.async_api import async_playwright

    async with async_playwright() as api:
        browser = await api.chromium.launch(
            headless=True,
            chromium_sandbox=True,
            timeout=10_000,
            args=["--disable-background-networking"],
        )
        try:
            viewports = [
                await _viewport(browser, fixture, width, height) for width, height, _ in VIEWPORTS
            ]
        finally:
            await browser.close()
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
            or view["document_requests"] != 1
            or type(view["snapshot_requests"]) is not int
            or not 4 <= view["snapshot_requests"] <= 24
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
