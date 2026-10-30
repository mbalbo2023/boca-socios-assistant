"""Pure-Python invariants for the optional offline benchmark harness."""

from __future__ import annotations

import argparse
import asyncio
import runpy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

# The optional script is deliberately not an installed application dependency.
# Load it by path so `uv run pytest` works even when the repository root is not
# inserted into sys.path by the pytest console entrypoint.
_script = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "benchmark_browser_contexts.py")
)
MiB = _script["MiB"]
ResourceSnapshot = _script["ResourceSnapshot"]
SYNTHETIC_HTML = _script["SYNTHETIC_HTML"]
budget_violation = _script["budget_violation"]
build_parser = _script["build_parser"]
is_allowed_page_request = _script["is_allowed_page_request"]
latency_summary = _script["latency_summary"]
parse_counts = _script["parse_counts"]
summarize_resources = _script["summarize_resources"]
run_group = _script["_run_group"]


def snapshot(
    *, memory: int | None = 1000 * MiB, limit: int | None = 2000 * MiB
) -> ResourceSnapshot:
    return ResourceSnapshot(
        memory_current_bytes=memory,
        memory_limit_bytes=limit,
        pids_current=4,
        pids_limit=64,
        cpu_usage_usec=100,
        cpu_nr_throttled=3,
        cpu_throttled_usec=20,
        shm_available_bytes=32 * MiB,
        shm_total_bytes=64 * MiB,
    )


@pytest.mark.parametrize("raw", ["", "9", "0", "1,1", "4,2", "1,2,4,8,8", "2,abc"])
def test_unbounded_or_duplicate_counts_rejected(raw: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_counts(raw)


def test_context_counts_have_strict_ceiling() -> None:
    assert parse_counts("1,2,4,8") == (1, 2, 4, 8)
    assert parse_counts("3") == (3,)


def test_command_line_never_accepts_external_target() -> None:
    parser = build_parser()
    assert parser.parse_args([]).counts == (1, 2, 4, 8)
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["--url", "https://example.invalid"])
    assert error.value.code == 2


def test_nearest_rank_latencies_and_missing_samples() -> None:
    assert latency_summary([]) is None
    assert latency_summary([10, 20, 30, 40]) == {
        "n": 4,
        "mean_ms": 25,
        "p50_ms": 20,
        "p95_ms": 40,
        "p99_ms": 40,
        "max_ms": 40,
    }


def test_cgroup_budget_stops_on_delta_or_headroom() -> None:
    baseline = snapshot()
    assert budget_violation(baseline, snapshot(memory=1400 * MiB), 512, 384) is None
    assert (
        budget_violation(baseline, snapshot(memory=1600 * MiB), 512, 384)
        == "measured_cgroup_delta_exceeded"
    )
    assert (
        budget_violation(baseline, snapshot(memory=1700 * MiB), 1000, 384)
        == "insufficient_cgroup_headroom"
    )
    assert budget_violation(snapshot(memory=None), snapshot(memory=None), 512, 384) is None
    nearly_full_pids = replace(baseline, pids_current=51)
    assert budget_violation(baseline, nearly_full_pids, 512, 384, 16) == "insufficient_pid_headroom"


def test_cgroup_accounting_does_not_claim_browser_specific_metrics() -> None:
    before = snapshot()
    peak = replace(
        before,
        memory_current_bytes=1200 * MiB,
        pids_current=12,
        cpu_usage_usec=500,
        cpu_nr_throttled=5,
        cpu_throttled_usec=30,
    )
    after = replace(peak, memory_current_bytes=1050 * MiB, pids_current=4)
    report = summarize_resources(before, [before, peak], after)
    assert report["scope"] == "entire_current_cgroup_not_browser_only"
    assert report["sampled_memory_delta_bytes"] == 200 * MiB
    assert report["after_cleanup_memory_delta_bytes"] == 50 * MiB
    assert report["cpu_usage_delta_usec"] == 400
    assert report["cpu_nr_throttled_delta"] == 2


def test_synthetic_html_references_no_external_asset() -> None:
    assert b"https://" not in SYNTHETIC_HTML
    assert b"<script src=" not in SYNTHETIC_HTML
    assert b"<link rel=" not in SYNTHETIC_HTML
    assert b"app-ready" in SYNTHETIC_HTML


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:54321/synthetic",
        "http://localhost:54321/synthetic",
        "http://example.invalid:54321/synthetic",
        "http://127.0.0.1:4444/synthetic",
        "http://127.0.0.1:notaport/synthetic",
        "file:///etc/passwd",
        "http://127.0.0.1:54321@evil.invalid/",
    ],
)
def test_page_requests_fail_closed_outside_ephemeral_loopback(url: str) -> None:
    assert is_allowed_page_request(url, 54321) is False


def test_page_request_accepts_only_ephemeral_loopback() -> None:
    assert is_allowed_page_request("http://127.0.0.1:54321/synthetic?nodes=400", 54321)


def test_blocked_external_page_request_makes_group_no_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(run_group.__globals__, "resource_snapshot", snapshot)

    class FakeRoute:
        request = SimpleNamespace(url="https://example.invalid/asset")
        aborted = False

        async def abort(self, _reason: str) -> None:
            self.aborted = True

        async def continue_(self) -> None:
            raise AssertionError("external request must never continue")

    class FakePage:
        async def goto(self, _url: str, **_kwargs: object) -> None:
            await context.route_callback(route)

        def locator(self, _selector: str) -> FakePage:
            return self

        async def wait_for(self, **_kwargs: object) -> None:
            pass

    class FakeContext:
        async def route(self, _pattern: str, callback: object) -> None:
            self.route_callback = callback

        async def new_page(self) -> FakePage:
            return FakePage()

        async def close(self) -> None:
            pass

    class FakeBrowser:
        async def new_context(self, **_kwargs: object) -> FakeContext:
            return context

        async def close(self) -> None:
            pass

    class FakeChromium:
        async def launch(self, **_kwargs: object) -> FakeBrowser:
            return FakeBrowser()

    context = FakeContext()
    route = FakeRoute()
    args = SimpleNamespace(
        max_delta_mib=512,
        min_headroom_mib=384,
        min_pid_headroom=16,
        dom_nodes=50,
        timeout_ms=1_000,
        hold_ms=0,
    )
    report = asyncio.run(run_group(SimpleNamespace(chromium=FakeChromium()), 54321, 1, 1, args))
    assert route.aborted
    assert report["navigation_successes"] == 1
    assert report["blocked_external_page_requests"] == 1
    assert "external_page_request_blocked" in report["errors"]
    assert report["result"] == "NO_GO"
