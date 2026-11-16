"""Causal harness contracts with real registry/pool and inert external browser I/O.

These tests establish no physical capacity and never start Docker or Playwright.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import textwrap
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = "a" * 40
IMAGE = "sha256:" + "b" * 64
RUN = "123456"
ROOT = Path(__file__).resolve().parents[1]
SECCOMP = str(ROOT / "docker/seccomp_profile.json")


def module():
    name = "boca_socios.browser.capacity_fixture"
    assert importlib.util.find_spec(name) is not None, "capacity measurement harness absent"
    return importlib.import_module(name)


class Page:
    def __init__(self, context):
        self.context = context
        self.closed = False
        self.url = "about:blank"

    async def goto(self, url, **kwargs):
        self.url = url

    def is_closed(self):
        return self.closed

    async def evaluate(self, expression, value=None):
        world = self.context.world
        if value is not None:
            world["writes"].append(value)
            self.context.storage["marker"] = value
            self.context.cookie = value
            return None
        if "localStorage" in expression:
            # All writes must have preceded the first read, on every failure path.
            assert len(world["writes"]) == 50
            return [self.context.storage.get("marker"), self.context.cookie]
        if world["mode"] == "b_dom" and world["closed"] == 25:
            return "broken"
        return "capacity_ready"


class Context:
    def __init__(self, browser):
        self.browser = browser
        self.world = browser.world
        self.storage = self.world["shared"] if self.world["mode"] == "storage" else {}
        self.cookie = None
        self.pages = []
        self.handlers = []

    async def route(self, pattern, callback):
        self.handlers.append(callback)

    async def route_web_socket(self, pattern, callback):
        self.handlers.append(callback)

    async def new_page(self):
        if self.world["mode"] == "repeated_page" and self.world.get("page"):
            page = self.world["page"]
        else:
            page = Page(self)
            self.world["page"] = page
        self.pages.append(page)
        return page

    async def close(self):
        if self.world["mode"] == "close":
            raise RuntimeError("private details must not leak")
        for page in self.pages:
            page.closed = True
        if self in self.browser.contexts:
            self.browser.contexts.remove(self)
            self.world["closed"] += 1


class Browser:
    def __init__(self, world):
        self.world = world
        self.contexts = []
        self.connected = True

    async def new_context(self, **options):
        if self.world["mode"] == "partial" and len(self.world["contexts"]) == 7:
            raise RuntimeError("private launch data")
        context = Context(self)
        self.contexts.append(context)
        self.world["contexts"].append(context)
        return context

    def is_connected(self):
        return self.connected

    async def close(self):
        self.connected = False


@pytest.fixture
def external(tmp_path, monkeypatch):
    api = module()
    root = tmp_path / "cgroup"
    root.mkdir()
    for name, value in {
        "memory.max": str(768 * 1024 * 1024),
        "pids.max": "128",
        "cpu.max": "100000 100000",
    }.items():
        (root / name).write_text(value)
    monkeypatch.setattr(os, "geteuid", lambda: 10002)
    monkeypatch.setattr(os, "getegid", lambda: 10002)
    monkeypatch.setattr(socket, "if_nameindex", lambda: [(1, "lo")])
    # Only external time is accelerated. Real pool and registry retain their defaults.
    from boca_socios.browser import engine_sessions

    clock = [0.0]
    sleep = asyncio.sleep

    async def advance(seconds):
        clock[0] += seconds
        await sleep(0)

    monkeypatch.setattr(engine_sessions, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine_sessions.asyncio, "sleep", advance)
    world = {"mode": "ok", "contexts": [], "writes": [], "shared": {}, "closed": 0}
    browsers = {kind: Browser(world) for kind in ("chromium", "firefox", "webkit")}

    class Kind:
        def __init__(self, browser):
            self.browser = browser

        async def launch(self, **options):
            return self.browser

    @asynccontextmanager
    async def playwright():
        yield SimpleNamespace(**{kind: Kind(browser) for kind, browser in browsers.items()})

    meta = api.Metadata(SOURCE, IMAGE, RUN)
    return api, root, playwright, meta, world, browsers


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("ok", "none"),
        ("storage", "isolation"),
        ("repeated_page", "handles"),
        ("partial", "admission"),
        ("b_dom", "survivors"),
        ("close", "teardown"),
    ],
)
def test_actual_harness_checks_simultaneity_isolation_partial_stop_and_uncertainty(
    external, mode, reason
):
    api, root, factory, meta, world, browsers = external
    world["mode"] = mode
    result = asyncio.run(api.CapacityHarness(meta, root=root, playwright_factory=factory).run())
    assert result["reason"] == reason
    assert result["state"] == ("GO" if mode == "ok" else "NO_GO")
    raw = api.encode_receipt(result)
    assert len(raw) <= 32768 and raw.endswith(b"\n")
    assert api.decode_receipt(raw, meta) == result
    assert b"private" not in raw and b"marker" not in raw
    if mode == "ok":
        assert result["counts"] == {
            "opened": 50,
            "barrier_live": 50,
            "closed_a": 25,
            "survivors_b": 25,
            "closed_final": 50,
        }
        assert len(world["writes"]) == 50
        assert all(not browser.connected for browser in browsers.values())
        assert result["peaks"]["pids_current"] == "UNKNOWN"
        assert all(check is True for check in result["checks"].values())
    if mode == "partial":
        assert result["counts"]["opened"] == 7
        assert result["counts"]["closed_final"] == 7


@pytest.mark.parametrize("guard", ["uid", "network", "limit"])
def test_real_guards_precede_any_browser_or_loopback_admission(external, monkeypatch, guard):
    api, root, factory, meta, world, _ = external
    if guard == "uid":
        monkeypatch.setattr(os, "geteuid", lambda: 0)
    elif guard == "network":
        monkeypatch.setattr(socket, "if_nameindex", lambda: [(1, "lo"), (2, "eth0")])
    else:
        (root / "memory.max").write_text("max")
    result = asyncio.run(api.CapacityHarness(meta, root=root, playwright_factory=factory).run())
    assert result["state"] == "NO_GO" and result["reason"] == "boundary"
    assert world["contexts"] == []


def test_work_timeout_still_runs_independent_teardown(external, monkeypatch):
    api, root, factory, meta, world, _ = external
    monkeypatch.setattr(api, "WORK_SECONDS", 0.000001)
    result = asyncio.run(api.CapacityHarness(meta, root=root, playwright_factory=factory).run())
    assert result["state"] == "NO_GO" and result["reason"] == "deadline"
    assert result["phase"] == "work"
    assert result["checks"]["final_closed"] is True


def test_receipt_is_closed_bounded_and_cannot_upgrade_partial_evidence(external):
    api, root, factory, meta, *_ = external
    good = asyncio.run(api.CapacityHarness(meta, root=root, playwright_factory=factory).run())
    for change in (
        {"unknown": "private"},
        {"environment": "DROPLET"},
        {"state": "PASS"},
        {"reason": "raw exception"},
        {"latencies": good["latencies"] | {"work_seconds": float("nan")}},
        {"counts": good["counts"] | {"barrier_live": 49}},
        {"checks": good["checks"] | {"isolation": False}},
    ):
        with pytest.raises(ValueError):
            api.encode_receipt(good | change)
    raw = api.encode_receipt(good)
    with pytest.raises(ValueError):
        api.decode_receipt(raw.replace(SOURCE.encode(), b"c" * 40), meta)
    with pytest.raises(ValueError):
        api.decode_receipt(raw.replace(b'"version":1', b'"version":1,"version":1'), meta)
    with pytest.raises(ValueError):
        api.decode_receipt(raw + b" " * 32768, meta)
    maximum = copy.deepcopy(good)
    maximum["samples"] = [
        sample | {"metrics": dict.fromkeys(api.METRICS, 2**63 - 1)} for sample in maximum["samples"]
    ]
    maximum["peaks"] = dict.fromkeys(api.METRICS, 2**63 - 1)
    maximum["run_id"] = "9" * 20
    maximum["latencies"] = dict.fromkeys(api.LATENCIES, 1.7976931348623157e-308)
    for sample in maximum["samples"]:
        sample["elapsed"] = 1.7976931348623157e-308
    size = len(api.encode_receipt(maximum))
    print(f"maximum_receipt_bytes={size}, including LF")
    assert size <= 32768


def test_routing_only_fixed_origin_and_websockets_are_denied(external):
    api, root, factory, meta, world, _ = external
    harness = api.CapacityHarness(meta, root=root, playwright_factory=factory)
    asyncio.run(harness.run())
    observer = harness.observers[0]

    async def check():
        for url, expected in (
            (observer.origin + "/", "continue"),
            (observer.origin + ".evil.invalid/", "abort"),
            ("http://127.0.0.1:1/", "abort"),
            ("https://example.invalid/", "abort"),
        ):
            calls = []

            async def allow(calls=calls):
                calls.append("continue")

            async def deny(calls=calls):
                calls.append("abort")

            route = SimpleNamespace(request=SimpleNamespace(url=url), continue_=allow, abort=deny)
            await observer.route(route)
            assert calls == [expected]

    asyncio.run(check())


def test_bounded_process_transport_rejects_overflow_and_timeout():
    api = module()
    result = api.command([sys.executable, "-c", "print('x'*40000)"], 2, 32768)
    assert result.overflow and not result.ok
    result = api.command([sys.executable, "-c", "import time; time.sleep(5)"], 0.02, 32768)
    assert result.timed_out and not result.ok


def workflow_step(name):
    source = (ROOT / ".github/workflows/boca-playwright-offline-diagnostic.yml").read_text()
    block = source.split("      - name: " + name + "\n", 1)[1].split("      - name:", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


def test_capacity_workflow_has_closed_selector_skips_both_legacy_probes_and_no_host():
    text = (ROOT / ".github/workflows/boca-playwright-offline-diagnostic.yml").read_text()
    assert "          - capacity50\n" in text
    for step in (
        "Verify all three bundles exist without blackbox execution",
        "Probe each Playwright engine in a separate offline process",
    ):
        block = text.split("      - name: " + step + "\n", 1)[1].split("      - name:", 1)[0]
        assert "if: env.DIAGNOSTIC_MODE != 'capacity50'" in block
    script = workflow_step("Measure capacity50 in one attested offline container")
    assert "if: env.DIAGNOSTIC_MODE == 'capacity50'" in text
    assert "boca_socios.browser.capacity_fixture --runner" in script
    assert "timeout 650s" in script
    assert "ssh" not in script and "docker run" not in script
    subprocess.run(["/bin/bash", "-n"], input=script, text=True, check=True)


def inspect_row(cid):
    return {
        "Id": cid,
        "Image": IMAGE,
        "Config": {
            "User": "10002:10002",
            "Entrypoint": ["python"],
            "Cmd": ["-m", "boca_socios.browser.capacity_fixture"],
            "Labels": {
                "boca.capacity.scope": "runner-offline",
                "boca.capacity.source": SOURCE,
                "boca.capacity.run": RUN,
            },
            "Env": [
                "BOCA_CAPACITY_SOURCE=" + SOURCE,
                "BOCA_CAPACITY_IMAGE=" + IMAGE,
                "BOCA_CAPACITY_RUN=" + RUN,
            ],
        },
        "HostConfig": {
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
            "CapAdd": ["SYS_CHROOT"],
            "ShmSize": 67108864,
            "SecurityOpt": [
                "no-new-privileges:true",
                "seccomp="
                + json.dumps(json.loads(Path(SECCOMP).read_text()), separators=(",", ":")),
            ],
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108 - fixed Docker tmpfs
                "/home/boca-browser": "rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0700",
            },
        },
        "Mounts": [],
        "State": {
            "Status": "exited",
            "Running": False,
            "ExitCode": 0,
            "OOMKilled": False,
            "Error": "",
        },
    }


@pytest.mark.parametrize(
    "case",
    [
        "ok",
        "attach_timeout",
        "exit",
        "oom",
        "bad_receipt",
        "remove",
        "absence_unknown",
        "attestation",
        "create_uncertain",
    ],
)
def test_global_go_requires_receipt_transport_zero_exit_and_exact_retirement(
    external, monkeypatch, capfd, case
):
    api, root, factory, meta, *_ = external
    receipt = api.encode_receipt(
        asyncio.run(api.CapacityHarness(meta, root=root, playwright_factory=factory).run())
    )
    cid = "c" * 64
    calls = []

    def docker(argv, seconds, cap=32768):
        calls.append(argv)
        op = argv[1]
        output = b""
        if op == "image":
            output = ((IMAGE if "{{.Id}}" in argv else SOURCE) + "\n").encode()
        elif op == "create":
            Path(argv[argv.index("--cidfile") + 1]).write_text(cid + "\n")
            assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
            assert "--volume" not in argv and "--publish" not in argv
            output = (cid + "\n").encode()
            if case == "create_uncertain":
                return api.CommandResult(None, b"", timed_out=True)
        elif op == "inspect":
            row = inspect_row(cid)
            if case == "attestation":
                row["Image"] = "sha256:" + "d" * 64
            if case == "exit":
                row["State"]["ExitCode"] = 1
            if case == "oom":
                row["State"]["OOMKilled"] = True
            output = json.dumps([row]).encode()
        elif op == "start":
            if case == "attach_timeout":
                return api.CommandResult(None, receipt, timed_out=True)
            output = b"private malformed content" if case == "bad_receipt" else receipt
        elif op == "rm":
            assert argv == ["docker", "rm", "--force", cid]
            if case == "remove":
                return api.CommandResult(1, b"")
            output = (cid + "\n").encode()
        elif op == "container":
            if case == "absence_unknown":
                return api.CommandResult(1, b"")
        else:
            pytest.fail("unreviewed external effect")
        return api.CommandResult(0, output)

    monkeypatch.setattr(api, "command", docker)
    assert api.run_runner("fixed-tag", SOURCE, RUN, SECCOMP) is (case == "ok")
    captured = capfd.readouterr()
    assert "private malformed" not in captured.out + captured.err
    assert "BOCA_CAPACITY50_GLOBAL state=" + ("GO" if case == "ok" else "NO_GO") in captured.out
    assert sum(call[1] == "create" for call in calls) == 1
    assert sum(call[1] == "start" for call in calls) == (
        0 if case in {"attestation", "create_uncertain"} else 1
    )
    assert sum(call[1] == "rm" for call in calls) == (0 if case == "attestation" else 1)


@pytest.mark.parametrize("change", ["shm", "mount", "port", "profile", "command", "source"])
def test_exact_container_attestation_rejects_boundary_drift(change):
    api = module()
    cid = "c" * 64
    value = inspect_row(cid)
    if change == "shm":
        value["HostConfig"]["ShmSize"] = 134217728
    elif change == "mount":
        value["Mounts"] = [{"Source": "/private"}]
    elif change == "port":
        value["HostConfig"]["PortBindings"] = {"8443/tcp": []}
    elif change == "profile":
        value["HostConfig"]["PidsLimit"] = 192
    elif change == "command":
        value["Config"]["Cmd"] = ["-m", "unreviewed"]
    else:
        value["Config"]["Labels"]["boca.capacity.source"] = "d" * 40
    with pytest.raises(ValueError):
        api.attest_container([value], cid, api.Metadata(SOURCE, IMAGE, RUN), SECCOMP)


def test_image_revision_is_verified_by_immutable_id_before_container_create(monkeypatch):
    api = module()
    calls = []

    def docker(argv, seconds, cap=32768):
        calls.append(argv)
        if len(calls) == 1:
            return api.CommandResult(0, (IMAGE + "\n").encode())
        if len(calls) == 2:
            assert argv[-1] == IMAGE, "tag lookup can race the immutable image identity"
            return api.CommandResult(1, b"")
        pytest.fail("no resource may be created after revision uncertainty")

    monkeypatch.setattr(api, "command", docker)
    assert api.run_runner("mutable-tag", SOURCE, RUN, SECCOMP) is False
    assert len(calls) == 2


def test_cgroup_continuity_and_independent_teardown_deadline(external, monkeypatch):
    api, root, factory, meta, world, _ = external
    original = Context.new_page

    async def replace_cgroup(context):
        if len(world["contexts"]) == 1:
            renamed = root.with_name("old-cgroup")
            root.rename(renamed)
            root.mkdir()
            for name in ("memory.max", "pids.max", "cpu.max"):
                (root / name).write_bytes((renamed / name).read_bytes())
        return await original(context)

    monkeypatch.setattr(Context, "new_page", replace_cgroup)
    result = asyncio.run(api.CapacityHarness(meta, root=root, playwright_factory=factory).run())
    assert result["state"] == "NO_GO" and result["reason"] in {"resources", "teardown"}
    assert result["counts"]["opened"] == 1


def test_uncertain_global_close_never_becomes_success(external, monkeypatch):
    api, root, factory, meta, *_ = external

    async def hanging_close(context):
        await asyncio.Event().wait()

    monkeypatch.setattr(Context, "close", hanging_close)
    monkeypatch.setattr(api, "CLOSE_SECONDS", 0.01)
    from boca_socios.browser import engine_sessions

    # Keep real registry/pool implementation, with shorter public constructor
    # deadlines through their declared API to exercise an external stalled close.
    original_init = engine_sessions.EngineSessionRegistry.__init__

    def configure(registry, **kwargs):
        original_init(registry, **kwargs, teardown_seconds=0.01)

    monkeypatch.setattr(engine_sessions.EngineSessionRegistry, "__init__", configure)
    result = asyncio.run(api.CapacityHarness(meta, root=root, playwright_factory=factory).run())
    assert result["state"] == "NO_GO" and result["reason"] == "teardown"
    assert result["checks"]["final_closed"] is False


def test_attestation_accepts_effective_seccomp_json_only_when_source_profile_matches():
    api = module()
    cid = "c" * 64
    row = inspect_row(cid)
    profile = ROOT / "docker/seccomp_profile.json"
    compact = json.dumps(json.loads(profile.read_text()), separators=(",", ":"))
    row["HostConfig"]["SecurityOpt"] = ["no-new-privileges:true", "seccomp=" + compact]
    assert api.attest_container([row], cid, api.Metadata(SOURCE, IMAGE, RUN), str(profile)) is row
    row["HostConfig"]["SecurityOpt"] = [
        "no-new-privileges:true",
        'seccomp={"defaultAction":"SCMP_ACT_ALLOW"}',
    ]
    with pytest.raises(ValueError):
        api.attest_container([row], cid, api.Metadata(SOURCE, IMAGE, RUN), str(profile))


def test_attestation_rejects_privileged_container_even_with_expected_cap_names():
    api = module()
    cid = "c" * 64
    row = inspect_row(cid)
    row["HostConfig"]["Privileged"] = True
    with pytest.raises(ValueError):
        api.attest_container([row], cid, api.Metadata(SOURCE, IMAGE, RUN), SECCOMP)
