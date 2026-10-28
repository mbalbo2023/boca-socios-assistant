"""Bounded, synthetic-only Chromium BrowserContext capacity experiment.

This script never accepts a remote URL. The sole test page is served by an
ephemeral HTTP server bound to 127.0.0.1; every page request is allowlisted.
Playwright is imported only when actually running this optional benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CGROUP = Path("/sys/fs/cgroup")
MiB = 1024 * 1024
SYNTHETIC_HTML = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Offline synthetic page</title>
<style>body{font:14px sans-serif}.tile{display:inline-block;width:30px;height:20px;
margin:2px;background:#123d82}</style></head><body>
<main id="tiles" aria-label="Synthetic DOM"></main>
<script>
const count = Math.min(2000, Math.max(50,
  Number(new URLSearchParams(location.search).get('nodes')) || 400));
const frag = document.createDocumentFragment();
for (let i = 0; i < count; i++) {
  const tile = document.createElement('span');
  tile.className = 'tile';
  tile.setAttribute('data-index', String(i));
  frag.appendChild(tile);
}
document.getElementById('tiles').appendChild(frag);
requestAnimationFrame(() => {
  const done = document.createElement('output');
  done.id = 'app-ready';
  done.textContent = 'ready';
  document.body.appendChild(done);
});
</script></body></html>"""


class SyntheticPageHandler(BaseHTTPRequestHandler):
    """Serve one immutable local asset, without request/body logging."""

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/synthetic":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(SYNTHETIC_HTML)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(SYNTHETIC_HTML)

    def log_message(self, _format: str, *args: object) -> None:
        """No access logs: benchmark output contains numeric metrics only."""


@dataclass(frozen=True)
class ResourceSnapshot:
    """Cgroup-wide counters: not attributable to the browser alone."""

    memory_current_bytes: int | None
    memory_limit_bytes: int | None
    pids_current: int | None
    pids_limit: int | None
    cpu_usage_usec: int | None
    cpu_nr_throttled: int | None
    cpu_throttled_usec: int | None
    shm_available_bytes: int | None
    shm_total_bytes: int | None


def _read_number(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="ascii").strip()
        return None if raw == "max" else int(raw)
    except (OSError, ValueError):
        return None


def _cpu_stat() -> dict[str, int]:
    try:
        raw = (CGROUP / "cpu.stat").read_text(encoding="ascii")
    except OSError:
        return {}
    result: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                result[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return result


def resource_snapshot() -> ResourceSnapshot:
    """Return None for unavailable host metrics; never invent measurements."""
    cpu = _cpu_stat()
    try:
        # Read-only stats for the Linux shared-memory mount, not a temporary
        # file, directory creation or storage of sensitive information.
        shm = os.statvfs("/dev/shm")  # noqa: S108
        shm_available = shm.f_bavail * shm.f_frsize
        shm_total = shm.f_blocks * shm.f_frsize
    except OSError:
        shm_available = None
        shm_total = None
    return ResourceSnapshot(
        memory_current_bytes=_read_number(CGROUP / "memory.current"),
        memory_limit_bytes=_read_number(CGROUP / "memory.max"),
        pids_current=_read_number(CGROUP / "pids.current"),
        pids_limit=_read_number(CGROUP / "pids.max"),
        cpu_usage_usec=cpu.get("usage_usec"),
        cpu_nr_throttled=cpu.get("nr_throttled"),
        cpu_throttled_usec=cpu.get("throttled_usec"),
        shm_available_bytes=shm_available,
        shm_total_bytes=shm_total,
    )


def parse_counts(raw: str) -> tuple[int, ...]:
    """Strictly bound the number of real browser contexts created."""
    try:
        counts = tuple(int(part.strip()) for part in raw.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Counts must be comma-separated integers"
        ) from error
    if not counts or len(counts) > 4 or any(count < 1 or count > 8 for count in counts):
        raise argparse.ArgumentTypeError("Supply 1–4 counts, each in 1..8")
    if len(set(counts)) != len(counts) or list(counts) != sorted(counts):
        raise argparse.ArgumentTypeError("Counts must be unique and ascending")
    return counts


def latency_summary(samples: list[float]) -> dict[str, float | int] | None:
    """Nearest-rank percentiles, expressed in milliseconds."""
    if not samples:
        return None
    ordered = sorted(samples)

    def rank(p: float) -> float:
        return round(ordered[math.ceil(len(ordered) * p) - 1], 2)

    return {
        "n": len(ordered),
        "mean_ms": round(statistics.mean(ordered), 2),
        "p50_ms": rank(0.50),
        "p95_ms": rank(0.95),
        "p99_ms": rank(0.99),
        "max_ms": round(ordered[-1], 2),
    }


def budget_violation(
    before: ResourceSnapshot,
    current: ResourceSnapshot,
    max_delta_mib: int,
    min_headroom_mib: int,
    min_pid_headroom: int = 16,
) -> str | None:
    """Fail closed when the *observed* cgroup budget is insufficient."""
    used = current.memory_current_bytes
    baseline = before.memory_current_bytes
    limit = current.memory_limit_bytes
    if (
        used is not None
        and baseline is not None
        and used - baseline > max_delta_mib * MiB
    ):
        return "measured_cgroup_delta_exceeded"
    if used is not None and limit is not None and limit - used < min_headroom_mib * MiB:
        return "insufficient_cgroup_headroom"
    if (
        current.pids_current is not None
        and current.pids_limit is not None
        and current.pids_limit - current.pids_current < min_pid_headroom
    ):
        return "insufficient_pid_headroom"
    return None


def _delta(before: int | None, after: int | None) -> int | None:
    return None if before is None or after is None else after - before


def is_allowed_page_request(url: str, server_port: int) -> bool:
    """Only allow HTTP on the exact ephemeral loopback port, never DNS hosts."""
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == server_port
        )
    except ValueError:
        return False


def summarize_resources(
    before: ResourceSnapshot, samples: list[ResourceSnapshot], after: ResourceSnapshot
) -> dict[str, Any]:
    sampled_memory = [
        v.memory_current_bytes for v in samples if v.memory_current_bytes is not None
    ]
    sampled_pids = [v.pids_current for v in samples if v.pids_current is not None]
    sampled_shm = [
        v.shm_available_bytes for v in samples if v.shm_available_bytes is not None
    ]
    peak_memory = max(sampled_memory) if sampled_memory else None
    peak_pids = max(sampled_pids) if sampled_pids else None
    min_shm = min(sampled_shm) if sampled_shm else None
    return {
        "scope": "entire_current_cgroup_not_browser_only",
        "baseline": asdict(before),
        "peak_sampled_memory_bytes": peak_memory,
        "peak_sampled_pids": peak_pids,
        "minimum_sampled_shm_available_bytes": min_shm,
        "sampled_memory_delta_bytes": _delta(before.memory_current_bytes, peak_memory),
        "after_cleanup_memory_delta_bytes": _delta(
            before.memory_current_bytes, after.memory_current_bytes
        ),
        "cpu_usage_delta_usec": _delta(before.cpu_usage_usec, after.cpu_usage_usec),
        "cpu_throttled_delta_usec": _delta(
            before.cpu_throttled_usec, after.cpu_throttled_usec
        ),
        "cpu_nr_throttled_delta": _delta(
            before.cpu_nr_throttled, after.cpu_nr_throttled
        ),
        "after_cleanup": asdict(after),
    }


async def _run_group(
    playwright: Any, port: int, count: int, repeat: int, args: Any
) -> dict[str, Any]:
    browser: Any = None
    contexts: list[Any] = []
    pages: list[Any] = []
    creation_ms: list[float] = []
    navigation_ms: list[float] = []
    snapshots: list[ResourceSnapshot] = []
    errors: list[str] = []
    blocked_requests = 0
    before = resource_snapshot()
    snapshots.append(before)
    run_start = time.perf_counter()

    def check_budget() -> None:
        current = resource_snapshot()
        snapshots.append(current)
        violation = budget_violation(
            before,
            current,
            args.max_delta_mib,
            args.min_headroom_mib,
            args.min_pid_headroom,
        )
        if violation:
            raise RuntimeError(violation)

    async def restrict_page_request(route: Any) -> None:
        nonlocal blocked_requests
        if is_allowed_page_request(route.request.url, port):
            await route.continue_()
        else:
            blocked_requests += 1
            await route.abort("blockedbyclient")

    try:
        check_budget()
        # Minimize incidental browser background I/O. These flags alone are
        # NOT a network firewall: a dedicated network namespace with egress
        # denied is required to guarantee offline execution at OS level.
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-background-networking", "--disable-component-update"],
        )
        check_budget()
        for _ in range(count):
            start = time.perf_counter()
            context = await browser.new_context(service_workers="block")
            contexts.append(context)
            await context.route("**/*", restrict_page_request)
            pages.append(await context.new_page())
            creation_ms.append((time.perf_counter() - start) * 1000)
            check_budget()

        async def navigate(page: Any) -> float:
            start = time.perf_counter()
            url = f"http://127.0.0.1:{port}/synthetic?nodes={args.dom_nodes}"
            await page.goto(url, wait_until="load", timeout=args.timeout_ms)
            await page.locator("#app-ready").wait_for(timeout=args.timeout_ms)
            return (time.perf_counter() - start) * 1000

        navigations = await asyncio.gather(
            *(navigate(page) for page in pages), return_exceptions=True
        )
        for response in navigations:
            if isinstance(response, BaseException):
                errors.append(type(response).__name__)
            else:
                navigation_ms.append(response)
        check_budget()
        await asyncio.sleep(args.hold_ms / 1000)
        check_budget()
    # Third-party Playwright exceptions are dynamic; contain all errors at
    # this experiment boundary to guarantee cleanup and a NO_GO result.
    except Exception as error:  # noqa: BLE001
        errors.append(type(error).__name__)
        if str(error) in {
            "measured_cgroup_delta_exceeded",
            "insufficient_cgroup_headroom",
            "insufficient_pid_headroom",
        }:
            errors.append(str(error))
    finally:
        for context in reversed(contexts):
            try:
                await asyncio.wait_for(context.close(), timeout=5)
            except Exception as error:  # noqa: BLE001 - best-effort cleanup
                errors.append(f"cleanup_context_{type(error).__name__}")
        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), timeout=8)
            except Exception as error:  # noqa: BLE001 - best-effort cleanup
                errors.append(f"cleanup_browser_{type(error).__name__}")
        after = resource_snapshot()
    return {
        "context_count": count,
        "repeat": repeat,
        "result": "PASS" if not errors and len(navigation_ms) == count else "NO_GO",
        "navigation_successes": len(navigation_ms),
        "errors": errors,
        "blocked_external_page_requests": blocked_requests,
        "context_creation": latency_summary(creation_ms),
        "navigation_ready": latency_summary(navigation_ms),
        "wall_time_ms": round((time.perf_counter() - run_start) * 1000, 2),
        "resources": summarize_resources(before, snapshots, after),
    }


async def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """Only localhost is addressed; browser contexts never use user profiles."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return 2, {"error": "playwright_not_installed", "installation": "see ADR 0008"}

    server = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticPageHandler)
    port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever, name="synthetic-server", daemon=True
    )
    thread.start()
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "offline_synthetic_only",
        "target": "ephemeral_local_127.0.0.1",
        "browser": "Playwright Chromium",
        "resource_scope": "entire_current_cgroup_not_browser_only",
        "configuration": {
            "counts": list(args.counts),
            "repeats": args.repeats,
            "dom_nodes": args.dom_nodes,
            "timeout_ms": args.timeout_ms,
            "hold_ms": args.hold_ms,
            "max_delta_mib": args.max_delta_mib,
            "min_headroom_mib": args.min_headroom_mib,
            "min_pid_headroom": args.min_pid_headroom,
        },
        "runs": [],
    }
    result_code = 0
    try:
        async with async_playwright() as playwright:
            for count in args.counts:
                for repeat in range(1, args.repeats + 1):
                    result = await _run_group(playwright, port, count, repeat, args)
                    report["runs"].append(result)
                    if result["result"] != "PASS":
                        report["stopped_early"] = True
                        result_code = 1
                        return result_code, report
    except Exception as error:  # noqa: BLE001 - experiment failure boundary
        report["fatal_error_type"] = type(error).__name__
        result_code = 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return result_code, report


def _bounded_int(low: int, high: int) -> Any:
    def parse(raw: str) -> int:
        try:
            number = int(raw)
        except ValueError as error:
            raise argparse.ArgumentTypeError("Integer required") from error
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"Must be in {low}..{high}")
        return number

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local synthetic BrowserContext benchmark; no remote URL accepted."
    )
    parser.add_argument("--counts", type=parse_counts, default=(1, 2, 4, 8))
    parser.add_argument("--repeats", type=_bounded_int(1, 5), default=2)
    parser.add_argument("--dom-nodes", type=_bounded_int(50, 2000), default=400)
    parser.add_argument("--hold-ms", type=_bounded_int(100, 10_000), default=500)
    parser.add_argument(
        "--timeout-ms", type=_bounded_int(1_000, 30_000), default=10_000
    )
    parser.add_argument("--max-delta-mib", type=_bounded_int(128, 2048), default=512)
    parser.add_argument("--min-headroom-mib", type=_bounded_int(64, 4096), default=384)
    parser.add_argument("--min-pid-headroom", type=_bounded_int(4, 256), default=16)
    parser.add_argument("--output", type=Path, help="Optional local JSON report file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    status, report = asyncio.run(run(args))
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    if status == 2:
        print(
            "Install Playwright and Chromium in an isolated dev environment (ADR 0008).",
            file=sys.stderr,
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
