"""Render captured bytes in a separate network-none container; never fetch anything."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

from . import public_observer_bundle as bundle
from .observe_public_home import CHALLENGE_MARKERS, inspect_rendered_login_dom
from .public_observer_capture import alarm

DIAGNOSTIC_METHODS = {"GET", "POST", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS", "OTHER"}
DIAGNOSTIC_KINDS = {
    "document",
    "stylesheet",
    "image",
    "media",
    "font",
    "script",
    "texttrack",
    "xhr",
    "fetch",
    "eventsource",
    "websocket",
    "manifest",
    "ping",
    "other",
}
DIAGNOSTIC_CAUSES = {
    "request_budget",
    "active_or_credential_request",
    "dynamic_request",
    "resource_outside_map",
    "navigation",
    "resource_type",
    "websocket",
}
KNOWN_DIAGNOSTIC_PATHS = {*bundle.ASSETS, bundle.LOGIN_PATH, "/", "/favicon.ico"}
# Identification only: these patterns MUST NOT authorize a request or fetch.
# Arbitrary filenames, page segments and opaque path values remain redacted.
NEXT_STATIC_DIAGNOSTIC = re.compile(
    r"/_next/static/(?:chunks/(?:[0-9]{1,8}|webpack|framework|main|polyfills)-[0-9a-f]{16}\.js"
    r"|css/[0-9a-f]{16}\.css|media/[0-9a-f]{16}-s\.p\.ttf)"
)
AUTHORITY_SCHEMES = {"http", "https", "ws", "wss"}
LOCAL_DNS_SUFFIXES = {
    "localhost",
    "local",
    "localdomain",
    "internal",
    "lan",
    "home",
    "home.arpa",
    "invalid",
    "test",
    "example",
    "onion",
}


def authority_metadata(url: str) -> dict:
    """Identify a rejected network authority without resolving or contacting it."""
    result = {"scheme": None, "authority": None, "host_kind": "redacted"}
    if (
        len(url) > 2048
        or "\\" in url
        or any(ord(char) < 33 or 127 <= ord(char) <= 159 for char in url)
    ):
        return result
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in AUTHORITY_SCHEMES:
            return result
        result["scheme"] = parsed.scheme
        if parsed.netloc.count("@") > 1:
            return result
        raw = parsed.netloc.rsplit("@", 1)[-1]
        host = parsed.hostname
        if (
            host is None
            or not host.isascii()
            or not raw
            or len(raw) > 260
            or any(char in raw for char in "%/?#\\")
        ):
            return result
        if raw.startswith("["):
            tail = raw[raw.index("]") + 1 :]
            if tail and not tail.startswith(":"):
                return result
            port_text = tail[1:] if tail else None
        else:
            if raw.count(":") > 1:
                return result
            port_text = raw.rsplit(":", 1)[1] if ":" in raw else None
        if port_text is not None and (
            re.fullmatch(r"[1-9][0-9]{0,4}", port_text) is None or int(port_text) > 65535
        ):
            return result
        port = parsed.port
        if port != (int(port_text) if port_text is not None else None):
            return result
        host = host.lower().removesuffix(".")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if (
                raw.startswith("[")
                or len(host) > 253
                or len(labels) < 2
                or any(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                    for label in labels
                )
                or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", labels[-1])
                or any(
                    host == suffix or host.endswith("." + suffix) for suffix in LOCAL_DNS_SUFFIXES
                )
            ):
                return result
            host_kind = "dns_syntax"  # No assertion about DNS answers, ownership or provider role.
        else:
            if (
                not address.is_global
                or address.is_multicast
                or address.is_reserved
                or address.is_loopback
                or address.is_link_local
                or address.is_unspecified
                or address.is_private
            ):
                return result
            host_kind = "global_ipv4" if address.version == 4 else "global_ipv6"
            host = str(address) if address.version == 4 else f"[{address.compressed}]"
        result.update(
            authority=host + (f":{port}" if port is not None else ""), host_kind=host_kind
        )
    except ValueError:
        return result
    return result


def valid_authority_metadata(item: dict) -> bool:
    scheme, authority, host_kind = (item[key] for key in ("scheme", "authority", "host_kind"))
    if scheme is not None and (not isinstance(scheme, str) or scheme not in AUTHORITY_SCHEMES):
        return False
    if authority is None:
        return host_kind == "redacted"
    if (
        not isinstance(authority, str)
        or not 1 <= len(authority) <= 259
        or scheme is None
        or not isinstance(host_kind, str)
    ):
        return False
    return authority_metadata(f"{scheme}://{authority}/") == {
        "scheme": scheme,
        "authority": authority,
        "host_kind": host_kind,
    }


def diagnostic_path_class(path: str) -> str:
    if path in KNOWN_DIAGNOSTIC_PATHS:
        return "known"
    if len(path) <= 256 and NEXT_STATIC_DIAGNOSTIC.fullmatch(path):
        return "next_static"
    return "redacted"


def denied_metadata(url: str, method: str, kind: str, cause: str) -> dict:
    """Omit URL userinfo/query/fragment and arbitrary paths; expose validated host syntax."""
    item = {
        "cause": cause if cause in DIAGNOSTIC_CAUSES else "resource_outside_map",
        "method": method if method in DIAGNOSTIC_METHODS else "OTHER",
        "kind": kind if kind in DIAGNOSTIC_KINDS else "other",
        "same_origin": False,
        "path": None,
        "path_class": "invalid",
        "query_redacted": "?" in url,
        "fragment_redacted": "#" in url,
        "userinfo_redacted": False,
        **authority_metadata(url),
    }
    if len(url) > 2048 or any(ord(char) < 33 for char in url):
        return item
    try:
        parsed = urlsplit(url)
    except ValueError:
        return item
    item["userinfo_redacted"] = "@" in parsed.netloc
    if parsed.scheme != "https" or parsed.netloc != bundle.HOST:
        item["path_class"] = "external"
        return item
    item["same_origin"] = True
    item["path_class"] = diagnostic_path_class(parsed.path)
    if item["path_class"] != "redacted":
        item["path"] = parsed.path
    return item


def valid_diagnostics(value: object) -> bool:
    """Supervisor boundary: strict schema, identical path grammar and ASCII byte cap."""
    if not isinstance(value, dict) or set(value) != {"denied_requests", "cancelled_after_stop"}:
        return False
    items = value["denied_requests"]
    if (
        not isinstance(items, list)
        or len(items) > 8
        or type(value["cancelled_after_stop"]) is not int
        or not 0 <= value["cancelled_after_stop"] <= 65535
    ):
        return False
    fields = {
        "cause",
        "method",
        "kind",
        "same_origin",
        "path",
        "path_class",
        "query_redacted",
        "fragment_redacted",
        "userinfo_redacted",
        "scheme",
        "authority",
        "host_kind",
    }
    for item in items:
        if not isinstance(item, dict) or set(item) != fields:
            return False
        if not valid_authority_metadata(item):
            return False
        if any(
            type(item[field]) is not bool
            for field in ("same_origin", "query_redacted", "fragment_redacted", "userinfo_redacted")
        ):
            return False
        if (
            not isinstance(item["cause"], str)
            or item["cause"] not in DIAGNOSTIC_CAUSES
            or not isinstance(item["method"], str)
            or item["method"] not in DIAGNOSTIC_METHODS
            or not isinstance(item["kind"], str)
            or item["kind"] not in DIAGNOSTIC_KINDS
            or not isinstance(item["path_class"], str)
        ):
            return False
        path = item["path"]
        if item["same_origin"]:
            if (
                item["userinfo_redacted"]
                or item["scheme"] != "https"
                or item["authority"] != bundle.HOST
                or item["host_kind"] != "dns_syntax"
            ):
                return False
            if path is None:
                if item["path_class"] != "redacted":
                    return False
            elif (
                not isinstance(path, str)
                or diagnostic_path_class(path) == "redacted"
                or item["path_class"] != diagnostic_path_class(path)
            ):
                return False
        elif path is not None or item["path_class"] not in {"external", "invalid"}:
            return False
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 4096


class RenderGuard:
    def __init__(self, value: dict) -> None:
        self.entries = {bundle.ORIGIN + item["path"]: item for item in value["entries"]}
        self.requests = 0
        self.documents = 0
        self.blocked = False
        self.reason = "none"
        self.denied_requests: list[dict] = []
        self.cancelled_after_stop = 0

    def diagnostics(self) -> dict:
        return {
            "denied_requests": list(self.denied_requests),
            "cancelled_after_stop": self.cancelled_after_stop,
        }

    def deny(self, url: str, method: str, kind: str, reason: str) -> None:
        if not self.blocked:
            # STOP is terminal, so only the first causal rejection is retained.
            self.denied_requests.append(denied_metadata(url, method, kind, reason))
        self.stop(reason)

    def stop(self, reason: str) -> None:
        self.blocked = True
        if self.reason == "none":
            self.reason = reason

    def allow(self, url: str, method: str, kind: str, headers: dict) -> dict | None:
        if self.blocked:
            self.cancelled_after_stop = min(65535, self.cancelled_after_stop + 1)
            return None
        self.requests += 1
        item = self.entries.get(url)
        if self.requests > 64:
            self.deny(url, method, kind, "request_budget")
        elif method != "GET" or any(key.lower() in {"cookie", "authorization"} for key in headers):
            self.deny(url, method, kind, "active_or_credential_request")
        elif kind in {"fetch", "xhr", "websocket", "eventsource", "ping"}:
            self.deny(url, method, kind, "dynamic_request")
        elif item is None:
            self.deny(url, method, kind, "resource_outside_map")
        elif kind == "document":
            if url != bundle.ORIGIN + bundle.LOGIN_PATH or self.documents:
                self.deny(url, method, kind, "navigation")
            else:
                self.documents += 1
        elif (kind, item["mime"]) not in {
            ("script", "text/javascript"),
            ("stylesheet", "text/css"),
            ("font", "font/ttf"),
        }:
            self.deny(url, method, kind, "resource_type")
        return None if self.blocked else item


def require_network_none() -> None:
    if {name for _, name in socket.if_nameindex()} != {"lo"}:
        raise ValueError("renderer network interface")


async def render(value: dict, receipt: dict) -> None:
    from playwright.async_api import async_playwright

    require_network_none()
    guard = RenderGuard(value)
    dom = False
    start = time.monotonic()
    async with async_playwright() as api:
        browser = await api.chromium.launch(
            headless=True,
            chromium_sandbox=True,
            timeout=8000,
            args=["--disable-background-networking"],
        )
        try:
            context = await browser.new_context(
                accept_downloads=False,
                service_workers="block",
                java_script_enabled=True,
            )
            try:

                async def route_request(route: object) -> None:
                    request = route.request
                    item = guard.allow(
                        request.url, request.method, request.resource_type, request.headers
                    )
                    if item is None:
                        await route.abort()
                        return
                    await route.fulfill(
                        status=200,
                        body=base64.b64decode(item["body"]),
                        headers={
                            "Content-Type": item["mime"],
                            "Cache-Control": "no-store",
                            "X-Content-Type-Options": "nosniff",
                        },
                    )

                async def websocket(route: object) -> None:
                    guard.deny(route.url, "GET", "websocket", "websocket")
                    await route.close(code=1008, reason="offline observation")

                await context.route("**/*", route_request)
                await context.route_web_socket("**/*", websocket)
                page = await context.new_page()
                context.on("page", lambda _: guard.stop("popup"))
                page.on("download", lambda _: guard.stop("download"))
                page.on("worker", lambda _: guard.stop("worker"))
                page.on("pageerror", lambda _: guard.stop("script_error"))
                page.on("requestfailed", lambda _: guard.stop("resource_failure"))
                page.on(
                    "framenavigated",
                    lambda frame: (
                        guard.deny(frame.url, "OTHER", "document", "navigation")
                        if frame != page.main_frame
                        or frame.url != bundle.ORIGIN + bundle.LOGIN_PATH
                        else None
                    ),
                )
                await page.goto(bundle.ORIGIN + bundle.LOGIN_PATH, wait_until="load", timeout=8000)
                # Observe late work during a fixed bounded window. No idle state
                # can prove that arbitrary future timers will never request data.
                while time.monotonic() - start < 14 and not guard.blocked:
                    await asyncio.sleep(0.1)
                visible_text = (await page.inner_text("body")).casefold()
                if any(marker in visible_text for marker in CHALLENGE_MARKERS):
                    guard.stop("challenge")
                dom = await inspect_rendered_login_dom(page)
                if await context.cookies():
                    guard.stop("cookie_state")
                # Close before deciding: unload/lifecycle requests remain guarded.
                await context.close()
                context = None
                require_network_none()
                receipt.update(
                    {
                        "internal_requests": guard.requests,
                        "blocked_reason": guard.reason,
                        "state": "DOM_OBSERVED" if dom and not guard.blocked else "UNKNOWN",
                        "diagnostics": guard.diagnostics(),
                    }
                )
            except Exception:
                guard.stop("runtime_failure")
            finally:
                try:
                    if context is not None:
                        await context.close()
                finally:
                    receipt.update(
                        {
                            "internal_requests": guard.requests,
                            "blocked_reason": guard.reason,
                            "state": "DOM_OBSERVED" if dom and not guard.blocked else "UNKNOWN",
                            "diagnostics": guard.diagnostics(),
                        }
                    )
        finally:
            await browser.close()


def child(fixture: bool) -> int:
    receipt = {
        "mode": "offline_capture_render",
        "provenance": "synthetic_fixture" if fixture else "public_capture",
        "state": "UNKNOWN",
        "connected_site": False,
        "internal_requests": 0,
        "blocked_reason": "runtime_failure",
        "diagnostics": {"denied_requests": [], "cancelled_after_stop": 0},
    }
    try:
        with bundle.open_bundle() as stream:
            value = bundle.decode_bundle(stream, fixture=fixture)
        asyncio.run(render(value, receipt))
    except (Exception, KeyboardInterrupt):
        # A late close/Playwright failure invalidates any provisional DOM result.
        receipt["state"] = "UNKNOWN"
        if receipt["blocked_reason"] == "none":
            receipt["blocked_reason"] = "runtime_failure"
    print(json.dumps(receipt))
    return 0 if receipt["state"] == "DOM_OBSERVED" else 1


def main() -> int:
    args = sys.argv[1:]
    if args in (["--child"], ["--fixture-child"]):
        return child(args == ["--fixture-child"])
    negative_fixtures = {
        "--fixture-fetch": (b'fetch("/auth/login").catch(() => {});', "dynamic_request"),
        "--fixture-websocket": (
            b'new WebSocket("wss://bocasocios.bocajuniors.com.ar/offline-fixture");',
            "websocket",
        ),
        "--fixture-navigation": (
            b'location.href = "/favicon.ico?boca_fixture=fixture-private-value#fixture-fragment";',
            "resource_outside_map",
        ),
        "--fixture-worker": (
            b'new Worker(URL.createObjectURL(new Blob(["postMessage(1)"],'
            b'{type:"application/javascript"})));',
            "worker",
        ),
    }
    if len(args) != 1 or args[0] not in {"--render", "--fixture-render", *negative_fixtures}:
        return 2
    fixture = args != ["--render"]
    result = 1
    receipt = {
        "mode": "offline_capture_render",
        "state": "UNKNOWN",
        "connected_site": False,
        "provenance": "synthetic_fixture" if fixture else "public_capture",
        "internal_requests": 0,
        "blocked_reason": "deadline_or_transfer",
        "diagnostics": {"denied_requests": [], "cancelled_after_stop": 0},
    }
    try:
        require_network_none()
        signal.signal(signal.SIGALRM, alarm)
        signal.setitimer(signal.ITIMER_REAL, 8)
        value = (
            bundle.fixture_bundle()
            if fixture
            else bundle.decode_bundle(sys.stdin.buffer, fixture=False)
        )
        if args[0] in negative_fixtures:
            script, _ = negative_fixtures[args[0]]
            value["entries"][8] = bundle.entry(bundle.ASSETS[7], script)
        bundle.save_bundle(value, fixture=fixture)
        signal.setitimer(signal.ITIMER_REAL, 0)
        # The supervisor kills the trusted child after a real wall-clock 20 s;
        # child cleanup cannot extend that allowance. Container cleanup then
        # destroys Chromium descendants and the tmpfs even after a timeout.
        run = subprocess.run(  # noqa: S603 - fixed interpreter/module/arguments, no user input
            [
                sys.executable,
                "-m",
                "scripts.public_observer_render",
                "--fixture-child" if fixture else "--child",
            ],
            timeout=20,
            capture_output=True,
            check=False,
            text=True,
        )
        value = json.loads(run.stdout)
        if (
            set(value) != set(receipt)
            or value["mode"] != receipt["mode"]
            or value["provenance"] != receipt["provenance"]
            or value["connected_site"] is not False
            or value["state"] not in {"DOM_OBSERVED", "UNKNOWN"}
            or type(value["internal_requests"]) is not int
            or not 0 <= value["internal_requests"] <= 65
            or not valid_diagnostics(value["diagnostics"])
            or value["blocked_reason"]
            not in {
                "none",
                "request_budget",
                "active_or_credential_request",
                "dynamic_request",
                "resource_outside_map",
                "navigation",
                "resource_type",
                "websocket",
                "popup",
                "download",
                "worker",
                "script_error",
                "resource_failure",
                "challenge",
                "cookie_state",
                "runtime_failure",
            }
        ):
            raise ValueError("render receipt")
        diagnostic = value["diagnostics"]
        if (
            value["state"] == "DOM_OBSERVED"
            and (
                diagnostic["denied_requests"]
                or diagnostic["cancelled_after_stop"]
                or value["blocked_reason"] != "none"
            )
        ) or (
            diagnostic["denied_requests"]
            and diagnostic["denied_requests"][0]["cause"] != value["blocked_reason"]
        ):
            raise ValueError("contradictory render receipt")
        receipt = value
        result = 0 if run.returncode == 0 and receipt["state"] == "DOM_OBSERVED" else 1
        if args[0] in negative_fixtures:
            _, reason = negative_fixtures[args[0]]
            result = (
                0
                if run.returncode == 1
                and receipt["state"] == "UNKNOWN"
                and receipt["blocked_reason"] == reason
                else 1
            )
            if args == ["--fixture-navigation"]:
                denials = receipt["diagnostics"]["denied_requests"]
                if (
                    len(denials) != 1
                    or denials[0]["path"] != "/favicon.ico"
                    or denials[0]["method"] != "GET"
                    or denials[0]["kind"] != "document"
                    or denials[0]["query_redacted"] is not True
                    or denials[0]["scheme"] != "https"
                    or denials[0]["authority"] != bundle.HOST
                    or denials[0]["host_kind"] != "dns_syntax"
                ):
                    result = 1
            if args == ["--fixture-websocket"]:
                denials = receipt["diagnostics"]["denied_requests"]
                if (
                    len(denials) != 1
                    or denials[0]["scheme"] != "wss"
                    or denials[0]["authority"] != bundle.HOST
                    or denials[0]["host_kind"] != "dns_syntax"
                    or denials[0]["same_origin"] is not False
                ):
                    result = 1
            receipt["expected_stop_verified"] = result == 0
    except (Exception, KeyboardInterrupt):
        receipt["state"] = "UNKNOWN"
        receipt["blocked_reason"] = "deadline_or_transfer"
        result = 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        bundle.remove_bundle()
    print(json.dumps(receipt))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
