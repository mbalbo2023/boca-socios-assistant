"""Fixed runner-only capacity evidence; never a provider, host or ticket probe.

The runner wrapper owns one disposable Docker CID. Its global result additionally
requires known transport/exit and attested retirement; the inner receipt alone
has no authority over a deployment or over physical droplet capacity.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import selectors
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit
from uuid import UUID

if TYPE_CHECKING:
    from boca_socios.browser.automatic_observer import PlaywrightFactory
    from boca_socios.browser.boca_auth_protocol import (
        BocaAuthReadiness,
        BocaAuthReply,
        BocaAuthRequest,
    )
    from boca_socios.browser.engine_protocol import (
        BrowserKind,
        EngineIdentity,
        EngineName,
        SessionInspection,
    )
    from boca_socios.browser.engine_sessions import EngineSessionRegistry, SharedBrowserPool
    from boca_socios.browser.queue_page_observation import QueuePageObservation

WORK_SECONDS = 600.0
CLOSE_SECONDS = 15.0
ENVELOPE_SECONDS = 650.0
MAX_RECEIPT = 32768
UNKNOWN = "UNKNOWN"
METRICS = (
    "memory_current_bytes",
    "memory_peak_bytes",
    "pids_current",
    "pids_peak",
    "cpu_usage_usec",
    "cpu_user_usec",
    "cpu_system_usec",
    "cpu_nr_periods",
    "cpu_nr_throttled",
    "cpu_throttled_usec",
)
PROFILE = {
    "cpu_millis": 1000,
    "memory_bytes": 805306368,
    "pids": 128,
    "uid": 10002,
    "gid": 10002,
    "opening_interval_seconds": 8,
    "work_seconds": 600,
    "close_seconds": 15,
    "envelope_seconds": 650,
}
COUNTS = ("opened", "barrier_live", "closed_a", "survivors_b", "closed_final")
CHECKS = (
    "distinct_handles",
    "dom_all",
    "isolation",
    "partial_close",
    "b_dom",
    "replay_rejected",
    "final_closed",
)
LATENCIES = ("opening_total_seconds", "opening_max_seconds", "work_seconds", "close_seconds")
REASONS = {
    "none",
    "boundary",
    "admission",
    "handles",
    "isolation",
    "survivors",
    "replay",
    "teardown",
    "deadline",
    "resources",
    "operation",
    "configuration",
}
PHASES = {"preflight", "admission", "barrier", "closed_a", "work", "final", "complete"}
_HTML = b'<!doctype html><title>Offline capacity fixture</title><p id="fixture-stage">capacity_ready</p>'
_WRITE = """value => {localStorage.setItem('capacity', value);
 document.cookie = 'capacity=' + value + '; Path=/; SameSite=Strict';}"""
_READ = """() => [localStorage.getItem('capacity'),
 document.cookie.split('; ').find(value => value.startsWith('capacity='))?.slice(9)]"""
_DOM = "() => document.getElementById('fixture-stage')?.textContent"
_MODULE = "boca_socios.browser.capacity_fixture"
_TMP = "/tmp"  # noqa: S108 - fixed private Docker tmpfs target, never a host file


class CapacityError(RuntimeError):
    """Only finite public failure categories escape the private operation."""


@dataclass(frozen=True)
class Metadata:
    source_sha: str
    image_id: str
    run_id: str

    def __post_init__(self) -> None:
        for value, pattern in (
            (self.source_sha, r"[0-9a-f]{40}"),
            (self.image_id, r"sha256:[0-9a-f]{64}"),
            (self.run_id, r"[1-9][0-9]{0,19}"),
        ):
            if type(value) is not str or re.fullmatch(pattern, value) is None:
                raise ValueError("capacity_metadata_unverified")


def _receipt(meta: Metadata) -> dict[str, Any]:
    return {
        "version": 1,
        "environment": "RUNNER_OFFLINE",
        "source_sha": meta.source_sha,
        "image_id": meta.image_id,
        "run_id": meta.run_id,
        "profile": dict(PROFILE),
        "state": "NO_GO",
        "phase": "preflight",
        "reason": "boundary",
        "counts": dict.fromkeys(COUNTS, 0),
        "checks": dict.fromkeys(CHECKS, False),
        "latencies": dict.fromkeys(LATENCIES, 0.0),
        "samples": [],
        "peaks": dict.fromkeys(METRICS, UNKNOWN),
    }


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 650  # type: ignore[arg-type,operator]


def _metrics(value: object) -> bool:
    return (
        type(value) is dict
        and set(value) == set(METRICS)
        and all(
            item == UNKNOWN or (type(item) is int and 0 <= item <= 2**63 - 1)
            for item in value.values()
        )
    )


def validate_receipt(value: object, meta: Metadata) -> dict[str, Any]:
    template = _receipt(meta)
    if (
        type(value) is not dict
        or set(value) != set(template)
        or type(value["version"]) is not int
        or value["version"] != 1
        or any(
            value[key] != template[key]
            for key in ("environment", "source_sha", "image_id", "run_id", "profile")
        )
        or type(value["profile"]) is not dict
        or any(type(item) is not int for item in value["profile"].values())
        or value["state"] not in ("GO", "NO_GO")
        or type(value["reason"]) is not str
        or value["reason"] not in REASONS
        or type(value["phase"]) is not str
        or value["phase"] not in PHASES
        or type(value["counts"]) is not dict
        or set(value["counts"]) != set(COUNTS)
        or any(type(count) is not int or not 0 <= count <= 50 for count in value["counts"].values())
        or type(value["checks"]) is not dict
        or set(value["checks"]) != set(CHECKS)
        or any(type(check) is not bool for check in value["checks"].values())
        or type(value["latencies"]) is not dict
        or set(value["latencies"]) != set(LATENCIES)
        or not all(_finite(latency) for latency in value["latencies"].values())
        or not _metrics(value["peaks"])
        or type(value["samples"]) is not list
        or len(value["samples"]) > 54
    ):
        raise ValueError("capacity_receipt_unverified")
    for sample in value["samples"]:
        if (
            type(sample) is not dict
            or set(sample) != {"phase", "admitted", "live", "elapsed", "metrics"}
            or type(sample["phase"]) is not str
            or sample["phase"] not in {"preflight", "admission", "barrier", "closed_a", "final"}
            or any(
                type(sample[key]) is not int or not 0 <= sample[key] <= 50
                for key in ("admitted", "live")
            )
            or not _finite(sample["elapsed"])
            or not _metrics(sample["metrics"])
        ):
            raise ValueError("capacity_receipt_unverified")
    if value["state"] == "GO":
        expected = {
            "opened": 50,
            "barrier_live": 50,
            "closed_a": 25,
            "survivors_b": 25,
            "closed_final": 50,
        }
        phases = [sample["phase"] for sample in value["samples"]]
        if (
            value["reason"] != "none"
            or value["phase"] != "complete"
            or value["counts"] != expected
            or not all(value["checks"].values())
            or phases != ["preflight", *(["admission"] * 50), "barrier", "closed_a", "final"]
            or [sample["live"] for sample in value["samples"]] != [0, *range(1, 51), 50, 25, 0]
            or [sample["admitted"] for sample in value["samples"]] != [0, *range(1, 51), 50, 50, 50]
        ):
            raise ValueError("capacity_receipt_unverified")
    elif value["reason"] == "none":
        raise ValueError("capacity_receipt_unverified")
    return value


def encode_receipt(value: dict[str, Any]) -> bytes:
    meta = Metadata(value["source_sha"], value["image_id"], value["run_id"])
    validate_receipt(value, meta)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(raw) > MAX_RECEIPT:
        raise ValueError("capacity_receipt_oversize")
    return raw


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("capacity_receipt_duplicate")
        result[key] = value
    return result


def decode_receipt(raw: bytes, meta: Metadata) -> dict[str, Any]:
    if not 0 < len(raw) <= MAX_RECEIPT or not raw.endswith(b"\n"):
        raise ValueError("capacity_receipt_unverified")
    value = json.loads(raw, object_pairs_hook=_pairs)
    return validate_receipt(value, meta)


class FixtureObserver:
    """One ordinary pool loan, one real context and one real page."""

    def __init__(self, pool: SharedBrowserPool, identity: EngineIdentity, origin: str):
        self.identity, self.origin = identity, origin
        self.loan = pool.browser_factory(identity.browser)()
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None
        self.closed = False

    async def route(self, route: Any) -> None:
        parts = urlsplit(route.request.url)
        if (
            parts.scheme + "://" + parts.netloc == self.origin
            and parts.path == "/"
            and not parts.query
            and not parts.fragment
        ):
            await route.continue_()
        else:
            await route.abort()

    @staticmethod
    async def deny_socket(route: Any) -> None:
        await route.close()

    async def dom(self) -> bool:
        return (
            self.page is not None
            and not self.page.is_closed()
            and await self.page.evaluate(_DOM) == "capacity_ready"
        )

    async def observe_queue(self) -> QueuePageObservation:
        from datetime import UTC, datetime

        from boca_socios.browser.queue_page_observation import parse_queue_page_observation

        if self.context is None:
            self.browser = await self.loan.__aenter__()
            self.context = await self.browser.new_context(
                service_workers="block",
                accept_downloads=False,
                java_script_enabled=True,
                ignore_https_errors=False,
            )
            await self.context.route("**/*", self.route)
            await self.context.route_web_socket("**/*", self.deny_socket)
            self.page = await self.context.new_page()
            await self.page.goto(self.origin + "/", wait_until="load", timeout=5000)
        if not await self.dom():
            raise CapacityError("admission")
        return parse_queue_page_observation(
            final_url=self.origin + "/",
            queue_model=None,
            markers=frozenset(),
            observed_at=datetime.now(UTC),
        )

    async def inspect(self) -> SessionInspection:
        from boca_socios.browser.engine_protocol import SessionInspection

        return SessionInspection(context_open=self.context is not None and not self.closed)

    async def prepare_boca_login(self, operation: str) -> BocaAuthReadiness:
        raise CapacityError("operation")

    async def login_boca(self, request: BocaAuthRequest) -> BocaAuthReply:
        raise CapacityError("operation")

    async def close(self) -> None:
        if self.closed:
            return
        if self.context is not None:
            await self.context.close()
        if self.browser is not None:
            await self.loan.__aexit__(None, None, None)
        self.closed = True

    def proven_closed(self) -> bool:
        return (
            self.closed
            and (self.page is None or self.page.is_closed())
            and (self.context is None or self.context not in self.browser.contexts)
        )


class CapacityHarness:
    def __init__(
        self,
        meta: Metadata,
        *,
        root: Path = Path("/sys/fs/cgroup"),
        playwright_factory: PlaywrightFactory | None = None,
    ):
        self.meta, self.root = meta, root
        self.factory = playwright_factory
        self.observers: list[FixtureObserver] = []
        self.registry: EngineSessionRegistry | None = None
        self.result = _receipt(meta)
        self.start = time.monotonic()
        self.cgroup: object = None

    def sample(self, phase: str) -> None:
        from scripts import measure_browser_budget as budget

        try:
            snapshot = budget.resource_snapshot(self.root, "browser-worker")
            if self.cgroup is not None and self.cgroup != snapshot["cgroup"]:
                raise CapacityError("resources")
            self.cgroup = snapshot["cgroup"]
            counters = cast(dict[str, Any], snapshot["counters"])
            metrics = {key: counters.get(key, UNKNOWN) for key in METRICS}
            if not _metrics(metrics):
                raise CapacityError("resources")
        except (OSError, ValueError, budget.BudgetError):
            raise CapacityError("resources") from None
        for key, value in metrics.items():
            previous = self.result["peaks"][key]
            if type(value) is int:
                self.result["peaks"][key] = max(previous, value) if type(previous) is int else value
        self.result["samples"].append(
            {
                "phase": phase,
                "admitted": len(self.observers),
                "live": self.registry.live_contexts if self.registry else 0,
                "elapsed": min(650.0, time.monotonic() - self.start),
                "metrics": metrics,
            }
        )

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(2):
                request = await reader.readuntil(b"\r\n\r\n")
                if len(request) > 4096 or not request.startswith(b"GET / HTTP/1."):
                    return
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nCache-Control: no-store\r\n"
                    + b"Content-Length: "
                    + str(len(_HTML)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + _HTML
                )
                await writer.drain()
        except (
            OSError,
            ValueError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def _scenario(self, pool: SharedBrowserPool) -> None:
        from boca_socios.browser.engine_protocol import EngineIdentity, EngineRequest
        from boca_socios.browser.engine_sessions import EngineSessionRegistry

        server = await asyncio.start_server(self._serve, "127.0.0.1", 0, limit=4096)
        async with server:
            port = server.sockets[0].getsockname()[1]
            origin = f"http://127.0.0.1:{port}"

            def observer(identity: EngineIdentity) -> FixtureObserver:
                value = FixtureObserver(pool, identity, origin)
                self.observers.append(value)
                return value

            self.registry = EngineSessionRegistry(observer_factory=observer, pool=pool)
            identities: list[EngineIdentity] = []
            distribution: tuple[BrowserKind, ...] = (
                ("chromium",) * 15 + ("firefox",) * 5 + ("webkit",) * 5
            )
            self.sample("preflight")
            self.result.update(phase="admission", reason="admission")
            engines: tuple[EngineName, ...] = ("queues_tokens", "browsers_members")
            for group, engine in enumerate(engines, 1):
                for browser in distribution:
                    identity = EngineIdentity(
                        engine,
                        str(UUID(int=group)),
                        1,
                        str(UUID(int=100 + len(identities))),
                        browser,
                    )
                    started = time.monotonic()
                    reply = await self.registry.execute(EngineRequest(identity, "observe"))
                    if reply.status != "OK" or self.registry.poisoned:
                        raise CapacityError("admission")
                    identities.append(identity)
                    latency = time.monotonic() - started
                    self.result["latencies"]["opening_total_seconds"] += latency
                    self.result["latencies"]["opening_max_seconds"] = max(
                        self.result["latencies"]["opening_max_seconds"], latency
                    )
                    self.result["counts"]["opened"] = len(identities)
                    self.sample("admission")
            self.result["phase"] = "barrier"
            if (
                self.registry.live_contexts != 50
                or len(self.observers) != 50
                or len({id(item.context) for item in self.observers}) != 50
                or len({id(item.page) for item in self.observers}) != 50
                or Counter(item.identity.browser for item in self.observers)
                != {"chromium": 30, "firefox": 10, "webkit": 10}
                or not all(
                    item.context in item.browser.contexts
                    and item.browser.is_connected()
                    and not item.closed
                    and not item.page.is_closed()
                    for item in self.observers
                )
            ):
                raise CapacityError("handles")
            self.result["checks"]["distinct_handles"] = True
            for item in self.observers:
                if not await item.dom():
                    raise CapacityError("handles")
            self.result["checks"]["dom_all"] = True
            self.result["counts"]["barrier_live"] = 50
            # Do not read one context before EVERY synthetic marker is written.
            for index, item in enumerate(self.observers):
                await item.page.evaluate(_WRITE, f"fixture-{index}")
            for index, item in enumerate(self.observers):
                if await item.page.evaluate(_READ) != [f"fixture-{index}"] * 2:
                    raise CapacityError("isolation")
            self.result["checks"]["isolation"] = True
            self.sample("barrier")
            self.result["phase"] = "closed_a"
            reply = await self.registry.execute(
                EngineRequest(identities[0], "close", close_scope="activation")
            )
            a, b = self.observers[:25], self.observers[25:]
            if (
                reply.status != "CLOSED"
                or self.registry.poisoned
                or self.registry.live_contexts != 25
                or not all(item.proven_closed() for item in a)
                or not all(
                    item.context in item.browser.contexts
                    and item.browser.is_connected()
                    and not item.closed
                    and not item.page.is_closed()
                    for item in b
                )
            ):
                raise CapacityError("teardown")
            self.result["counts"].update(closed_a=25, survivors_b=25)
            self.result["checks"]["partial_close"] = True
            for item in b:
                if not await item.dom():
                    raise CapacityError("survivors")
            self.result["checks"]["b_dom"] = True
            before = len(self.observers)
            replay = await self.registry.execute(EngineRequest(identities[0], "observe"))
            if (
                replay.status != "NO_GO"
                or len(self.observers) != before
                or self.registry.live_contexts != 25
            ):
                raise CapacityError("replay")
            self.result["checks"]["replay_rejected"] = True
            self.sample("closed_a")
            reply = await self.registry.execute(
                EngineRequest(identities[25], "close", close_scope="activation")
            )
            if reply.status != "CLOSED" or self.registry.live_contexts != 0:
                raise CapacityError("teardown")

    async def run(self) -> dict[str, Any]:
        from boca_socios.browser.automatic_observer import _default_playwright
        from boca_socios.browser.engine_sessions import SharedBrowserPool
        from boca_socios.browser.offline_fixture import (
            _require_no_egress_namespace as require_no_egress,
        )
        from boca_socios.browser.worker_health import validate_worker_boundary

        pool = SharedBrowserPool(
            playwright_factory=self.factory or _default_playwright,
            boundary_check=partial(validate_worker_boundary, root=self.root),
            opening_interval=8.0,
        )
        good = False
        try:
            validate_worker_boundary(root=self.root)
            require_no_egress()
            # Exact resource_snapshot limits are additionally required before I/O.
            self.sample("preflight")
            self.result["samples"].clear()
            self.result["phase"] = "work"
            async with asyncio.timeout(WORK_SECONDS):
                await self._scenario(pool)
            good = True
        except TimeoutError:
            self.result.update(reason="deadline", phase="work")
        except CapacityError as exc:
            self.result["reason"] = str(exc) if str(exc) in REASONS else "operation"
        except Exception:
            self.result["reason"] = (
                "boundary" if self.result["phase"] == "preflight" else "operation"
            )
        finally:
            self.result["latencies"]["work_seconds"] = min(650.0, time.monotonic() - self.start)
            started = time.monotonic()
            try:
                async with asyncio.timeout(CLOSE_SECONDS):
                    if self.registry is not None:
                        await self.registry.close()
                    else:
                        await pool.close()
                    if (
                        self.registry is not None
                        and (self.registry.live_contexts != 0 or self.registry.poisoned)
                        or not all(
                            item.proven_closed() and not item.browser.is_connected()
                            for item in self.observers
                        )
                    ):
                        raise CapacityError("teardown")
                    self.result["checks"]["final_closed"] = True
                    self.result["counts"]["closed_final"] = sum(
                        item.context is not None and item.proven_closed() for item in self.observers
                    )
                    if self.cgroup is not None:
                        self.sample("final")
            except Exception:
                good = False
                self.result["reason"] = "teardown"
            self.result["latencies"]["close_seconds"] = min(650.0, time.monotonic() - started)
        if good:
            self.result.update(state="GO", reason="none", phase="complete")
        return self.result


@dataclass(frozen=True)
class CommandResult:
    code: int | None
    stdout: bytes
    timed_out: bool = False
    overflow: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out and not self.overflow


def command(argv: list[str], seconds: float, cap: int = 32768) -> CommandResult:
    """Bounded process transport; never publish stderr or arbitrary output."""
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)  # noqa: S603
    output = bytearray()
    deadline = time.monotonic() + max(0.0, seconds)
    timed_out = overflow = False
    try:
        with selectors.DefaultSelector() as selector:
            assert process.stdout is not None
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fd, min(4096, cap + 1 - len(output)))
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(data)
                        if len(output) > cap:
                            overflow = True
                            break
                if overflow:
                    break
        if timed_out or overflow:
            process.kill()
        try:
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            code = process.wait(timeout=1)
        return CommandResult(code, bytes(output[:cap]), timed_out, overflow)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        if process.stdout:
            process.stdout.close()


def _security_matches(value: object, seccomp: str) -> bool:
    # Docker stores the effective compact JSON, not the caller's source path.
    if (
        type(value) is not list
        or len(value) != 2
        or value[0] != "no-new-privileges:true"
        or type(value[1]) is not str
        or not value[1].startswith("seccomp=")
    ):
        return False
    try:
        with Path(seccomp).open("rb") as stream:
            raw = stream.read(MAX_RECEIPT + 1)
        if len(raw) > MAX_RECEIPT:
            return False
        expected = json.loads(raw, object_pairs_hook=_pairs)
        observed = json.loads(value[1][8:], object_pairs_hook=_pairs)
        return type(expected) is dict and observed == expected
    except (OSError, ValueError):
        return False


def attest_container(value: object, cid: str, meta: Metadata, seccomp: str) -> dict[str, Any]:
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise ValueError("capacity_container_unverified")
    row = value[0]
    config, host = row.get("Config", {}), row.get("HostConfig", {})
    if type(config) is not dict or type(host) is not dict or type(config.get("Labels")) is not dict:
        raise ValueError("capacity_container_unverified")
    required = {
        "NetworkMode": "none",
        "ReadonlyRootfs": True,
        "Init": True,
        "Privileged": False,
        "Memory": 805306368,
        "NanoCpus": 1000000000,
        "PidsLimit": 128,
        "IpcMode": "private",
        "CgroupnsMode": "private",
        "CapDrop": ["ALL"],
        "ShmSize": 67108864,
        "Tmpfs": {
            _TMP: "rw,noexec,nosuid,size=32m",
            "/home/boca-browser": "rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0700",
        },
    }
    labels = config.get("Labels", {})
    if (
        re.fullmatch(r"[0-9a-f]{64}", cid) is None
        or row.get("Id") != cid
        or row.get("Image") != meta.image_id
        or config.get("User") != "10002:10002"
        or config.get("Entrypoint") != ["python"]
        or config.get("Cmd") != ["-m", _MODULE]
        or any(
            type(host.get(key)) is not type(expected) or host.get(key) != expected
            for key, expected in required.items()
        )
        or host.get("CapAdd") not in (["SYS_CHROOT"], ["CAP_SYS_CHROOT"])
        or not _security_matches(host.get("SecurityOpt"), seccomp)
        or host.get("Binds")
        or host.get("PortBindings")
        or host.get("PublishAllPorts")
        or row.get("Mounts")
        or any(
            labels.get(key) != expected
            for key, expected in {
                "boca.capacity.scope": "runner-offline",
                "boca.capacity.source": meta.source_sha,
                "boca.capacity.run": meta.run_id,
            }.items()
        )
        or any(
            item not in config.get("Env", [])
            for item in (
                "BOCA_CAPACITY_SOURCE=" + meta.source_sha,
                "BOCA_CAPACITY_IMAGE=" + meta.image_id,
                "BOCA_CAPACITY_RUN=" + meta.run_id,
            )
        )
    ):
        raise ValueError("capacity_container_unverified")
    return row


def run_runner(image: str, source: str, run: str, seccomp: str) -> bool:
    """Single runner-owned disposable CID, no mounts/ports or reusable host path."""
    deadline = time.monotonic() + ENVELOPE_SECONDS

    def invoke(args: list[str], seconds: float = 5, cap: int = MAX_RECEIPT) -> CommandResult:
        return command(["docker", *args], min(seconds, max(0.0, deadline - time.monotonic())), cap)

    cid = ""
    meta = None
    internal = False
    transport = False
    exit_known = False
    retired = False
    try:
        Metadata(source, "sha256:" + "0" * 64, run)
        identity = invoke(["image", "inspect", "--format", "{{.Id}}", image], cap=80)
        if not identity.ok:
            raise ValueError
        meta = Metadata(source, identity.stdout.decode().strip(), run)
        revision = invoke(
            [
                "image",
                "inspect",
                "--format",
                '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                meta.image_id,
            ],
            cap=41,
        )
        if not revision.ok or revision.stdout != (source + "\n").encode():
            raise ValueError
        # The CID file is an invocation-owned fallback if create transport fails.
        with tempfile.TemporaryDirectory(prefix="boca-capacity-") as directory:
            cidfile = Path(directory) / "cid"
            args = [
                "create",
                "--cidfile",
                str(cidfile),
                "--init",
                "--network",
                "none",
                "--user",
                "10002:10002",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "SYS_CHROOT",
                "--security-opt",
                "no-new-privileges:true",
                "--security-opt",
                "seccomp=" + seccomp,
                "--cgroupns",
                "private",
                "--ipc",
                "private",
                "--pids-limit",
                "128",
                "--memory",
                "768m",
                "--cpus",
                "1.0",
                "--shm-size",
                "64m",
                "--tmpfs",
                _TMP + ":rw,noexec,nosuid,size=32m",
                "--tmpfs",
                "/home/boca-browser:rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0700",
            ]
            for key, value in (("scope", "runner-offline"), ("source", source), ("run", run)):
                args.extend(["--label", "boca.capacity." + key + "=" + value])
            for key, value in (("SOURCE", source), ("IMAGE", meta.image_id), ("RUN", run)):
                args.extend(["--env", "BOCA_CAPACITY_" + key + "=" + value])
            args.extend(["--entrypoint", "python", meta.image_id, "-m", _MODULE])
            created = invoke(args, cap=80)
            if cidfile.exists() and cidfile.stat().st_size <= 65:
                cid = cidfile.read_text().strip()
            if not created.ok or created.stdout != (cid + "\n").encode():
                raise ValueError
            observed = invoke(["inspect", cid])
            if not observed.ok:
                raise ValueError
            attest_container(json.loads(observed.stdout), cid, meta, seccomp)
            attached = invoke(["start", "--attach", cid], 625)
            transport = (
                not attached.timed_out and not attached.overflow and attached.code is not None
            )
            if transport:
                receipt = decode_receipt(attached.stdout, meta)
                # Preserve only a validated receipt, never arbitrary output.
                sys.stdout.buffer.write(encode_receipt(receipt))
                internal = receipt["state"] == "GO"
            observed = invoke(["inspect", cid])
            if not observed.ok:
                raise ValueError
            row = attest_container(json.loads(observed.stdout), cid, meta, seccomp)
            state = row.get("State", {})
            exit_known = (
                attached.ok
                and state.get("Status") == "exited"
                and state.get("Running") is False
                and type(state.get("ExitCode")) is int
                and state["ExitCode"] == 0
                and state.get("OOMKilled") is False
                and state.get("Error") == ""
            )
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        pass
    finally:
        if meta is not None and re.fullmatch(r"[0-9a-f]{64}", cid):
            try:
                observed = invoke(["inspect", cid])
                if not observed.ok:
                    raise ValueError
                attest_container(json.loads(observed.stdout), cid, meta, seccomp)
                removed = invoke(["rm", "--force", cid], cap=80)
                listed = invoke(
                    [
                        "container",
                        "ls",
                        "--all",
                        "--no-trunc",
                        "--filter",
                        "id=" + cid,
                        "--format",
                        "{{.ID}}",
                    ],
                    cap=80,
                )
                retired = (
                    removed.ok
                    and removed.stdout == (cid + "\n").encode()
                    and listed.ok
                    and listed.stdout == b""
                )
            except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
                retired = False
    good = internal and transport and exit_known and retired
    print(
        "BOCA_CAPACITY50_GLOBAL state="
        + ("GO" if good else "NO_GO")
        + " receipt="
        + ("GO" if internal else "NO_GO")
        + " transport="
        + ("KNOWN" if transport else "UNKNOWN")
        + " exit="
        + ("KNOWN_ZERO" if exit_known else "UNVERIFIED")
        + " retirement="
        + ("CONFIRMED" if retired else "UNVERIFIED")
    )
    return good


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 5 and args[0] == "--runner":
            return 0 if run_runner(*args[1:]) else 1
        if args:
            raise ValueError
        meta = Metadata(
            os.environ.get("BOCA_CAPACITY_SOURCE", ""),
            os.environ.get("BOCA_CAPACITY_IMAGE", ""),
            os.environ.get("BOCA_CAPACITY_RUN", ""),
        )
        # Browser stderr can contain private paths: discard at the OS boundary.
        with open(os.devnull, "wb") as sink:
            saved = os.dup(2)
            try:
                os.dup2(sink.fileno(), 2)
                receipt = asyncio.run(CapacityHarness(meta).run())
            finally:
                os.dup2(saved, 2)
                os.close(saved)
        sys.stdout.buffer.write(encode_receipt(receipt))
        return 0 if receipt["state"] == "GO" else 1
    except (Exception, KeyboardInterrupt):
        print("BOCA_CAPACITY50 state=NO_GO reason=configuration", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
