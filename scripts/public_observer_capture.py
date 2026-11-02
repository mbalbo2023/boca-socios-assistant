"""One approved 25-GET capture; TLS stays end-to-end through the fixed CONNECT gate."""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import signal
import socket
import ssl
import sys
import time
from datetime import UTC, datetime

from . import public_observer_bundle as bundle

REQUEST_HEADERS = {
    "Host": bundle.HOST,
    "Connection": "close",
    "Accept-Encoding": "identity",
    "User-Agent": "BocaSociosPublicDiagnostic/1.0",
    "Accept": "*/*",
}


def request_budget(now: float, deadline: float) -> float:
    remaining = deadline - now
    if remaining <= 0:
        raise TimeoutError("capture deadline")
    return min(8.0, remaining)


def alarm(_signum: int, _frame: object) -> None:
    raise TimeoutError("wall deadline")


def read_response(response: http.client.HTTPResponse, path: str, remaining: int) -> bytes:
    maximum, expected = bundle.contract(path)
    if response.status != 200:
        raise ValueError("http rejection")
    mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
    allowed = {expected}
    if expected == "text/javascript":
        allowed.add("application/javascript")
    if expected == "font/ttf":
        allowed |= {"application/octet-stream", "application/x-font-ttf"}
    if mime not in allowed or response.getheader("Content-Encoding", "identity") != "identity":
        raise ValueError("content type or encoding")
    declared = response.getheader("Content-Length", "")
    limit = min(maximum, remaining)
    if declared and (not declared.isdecimal() or int(declared) > limit):
        raise ValueError("declared body size")
    chunks = bytearray()
    while True:
        part = response.read(min(65536, limit + 1 - len(chunks)))
        if not part:
            break
        chunks.extend(part)
        if len(chunks) > limit:
            raise ValueError("body size")
    if not chunks or (declared and len(chunks) != int(declared)):
        raise ValueError("body incomplete")
    return bytes(chunks)


def fetch(path: str, proxy_ip: str, timeout: float, remaining: int) -> bytes:
    bundle.contract(path)
    # stdlib has no redirects, retry loop or cookie jar. TLS verifies the tunnel
    # hostname, not the numeric proxy; each request owns a fresh connection.
    connection = http.client.HTTPSConnection(
        proxy_ip, 18080, timeout=timeout, context=ssl.create_default_context()
    )
    connection.set_tunnel(bundle.HOST, 443)
    try:
        connection.request("GET", path, headers=REQUEST_HEADERS)
        return read_response(connection.getresponse(), path, remaining)
    finally:
        connection.close()


def finish_proxy(proxy_ip: str, count: int) -> None:
    # A local control message, never a public HTTP request. It cannot enlarge
    # the allowance, reset counters or choose an upstream destination.
    request = f"POST /finish/{count} HTTP/1.1\r\nHost: proxy\r\nContent-Length: 0\r\n\r\n"
    with socket.create_connection((proxy_ip, 18080), timeout=2) as connection:
        connection.sendall(request.encode("ascii"))
        if not connection.recv(128).startswith(b"HTTP/1.1 204 "):
            raise ValueError("proxy completion mismatch")


def capture(proxy_ip: str, receipt: dict) -> dict:
    deadline = time.monotonic() + 120
    previous_start: float | None = None
    entries: list[dict[str, str]] = []
    total = 0
    for path in (bundle.LOGIN_PATH, *bundle.ASSETS):
        if previous_start is not None:
            spacing = max(0.0, previous_start + 0.5 - time.monotonic())
            if spacing >= deadline - time.monotonic():
                raise TimeoutError("capture deadline")
            time.sleep(spacing)
        budget = request_budget(time.monotonic(), deadline)
        previous_start = time.monotonic()
        # Count attempts before touching transport. No exception can cause retry.
        receipt["http_get_attempts"] += 1
        signal.setitimer(signal.ITIMER_REAL, budget)
        try:
            body = fetch(path, proxy_ip, budget, bundle.TOTAL_LIMIT - total)
            item = bundle.entry(path, body)
            entries.append(item)
            total += len(body)
            receipt["completed"].append(
                {"path": path, "status": 200, "bytes": len(body), "sha256": item["sha256"]}
            )
            if path == bundle.LOGIN_PATH:
                bundle.inventory(body)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    signal.setitimer(signal.ITIMER_REAL, request_budget(time.monotonic(), deadline))
    try:
        finish_proxy(proxy_ip, receipt["http_get_attempts"])
        value = {"mode": "public_capture", "entries": entries}
        bundle.save_bundle(value, fixture=False)
        request_budget(time.monotonic(), deadline)
        return value
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> int:
    receipt = {
        "mode": "bounded_public_capture",
        "state": "STOPPED",
        "reason": "none",
        "http_get_attempts": 0,
        "completed": [],
        "connected_site": False,
        "observed_at": datetime.now(UTC).isoformat(),
        "source_sha": None,
    }
    signal.signal(signal.SIGALRM, alarm)
    address = None
    try:
        if sys.argv[1:] == ["--export"]:
            signal.setitimer(signal.ITIMER_REAL, 8)
            try:
                with bundle.open_bundle() as stream:
                    value = bundle.decode_bundle(stream, fixture=False)
                sys.stdout.buffer.write(bundle.encode_bundle(value))
                sys.stdout.buffer.flush()
            finally:
                bundle.remove_bundle()
            return 0
        if (
            sys.argv[1:] != ["--capture-25"]
            or os.environ.get("BOCA_PUBLIC_OBSERVATION") != "capture-25"
            or os.environ.get("BOCA_OBSERVER_STOP", "1") != "0"
        ):
            raise ValueError("capture disabled")
        source_sha = os.environ.get("BOCA_PUBLIC_SOURCE_SHA", "")
        if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
            raise ValueError("source identity")
        receipt["source_sha"] = source_sha
        address = ipaddress.IPv4Address(os.environ.get("BOCA_PUBLIC_PROXY_IP", ""))
        if not address.is_private or address.is_loopback or address.is_unspecified:
            raise ValueError("invalid proxy")
        capture(str(address), receipt)
        receipt["state"] = "CAPTURED"
    except (Exception, KeyboardInterrupt) as error:
        reasons = {
            "challenge": "challenge",
            "publication inventory changed": "inventory_changed",
            "unapproved reference": "unapproved_reference",
            "active navigation": "active_navigation",
            "alternate resource": "alternate_resource",
            "http rejection": "http_rejection",
            "content type or encoding": "content_type_or_encoding",
            "body size": "body_size",
            "declared body size": "body_size",
            "body incomplete": "body_incomplete",
            "proxy completion mismatch": "proxy_completion_mismatch",
        }
        receipt["reason"] = (
            "deadline"
            if isinstance(error, TimeoutError)
            else "tls_failure"
            if isinstance(error, ssl.SSLError)
            else "transport_failure"
            if isinstance(error, OSError)
            else reasons.get(str(error), "validation_or_runtime_failure")
        )
        signal.setitimer(signal.ITIMER_REAL, 0)
        if address is not None:
            try:
                finish_proxy(str(address), receipt["http_get_attempts"])
            except (OSError, ValueError):
                pass
        bundle.remove_bundle()
        if sys.argv[1:] == ["--export"]:
            print("private_transfer_stopped", file=sys.stderr)
            return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    print(json.dumps(receipt))
    return 0 if receipt["state"] == "CAPTURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
