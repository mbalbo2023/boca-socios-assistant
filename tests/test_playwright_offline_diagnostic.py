"""Exercise the actual offline diagnostic classifier without launching a browser."""

from __future__ import annotations

import ast
import json
import os
import re
import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from scripts import measure_browser_budget as budget

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/boca-playwright-offline-diagnostic.yml"
)


def _definitions(*names: str) -> dict[str, object]:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Probe each Playwright engine in a separate offline process\n", 1
    )[1]
    source = step.split('--entrypoint python "$IMAGE" -c \'\n', 1)[1].split(
        "\n          ' ; then\n", 1
    )[0]
    parsed = ast.parse(textwrap.dedent(source))
    definitions = [
        node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(definitions) == len(names), "execute only the requested actual probe functions"
    module = ast.Module(body=definitions, type_ignores=[])
    namespace: dict[str, object] = {"re": re, "os": os, "budget": budget}
    # No Playwright import or workflow main body is executed.
    exec(compile(module, str(WORKFLOW), "exec"), namespace)  # noqa: S102
    return namespace


def _passive_namespace(root: Path) -> dict[str, object]:
    namespace = _definitions(
        "failure_details",
        "resource_snapshot",
        "resource_deltas",
        "stderr_snapshot",
        "late_stderr_details",
        "probe_engine",
    )
    namespace["budget"] = SimpleNamespace(
        CGROUP=root,
        UNKNOWN=budget.UNKNOWN,
        MAX_COUNTER=budget.MAX_COUNTER,
        COUNTER_FILES=budget.COUNTER_FILES,
        CPU_FIELDS=budget.CPU_FIELDS,
        read_counters=budget.read_counters,
        _bounded_text=budget._bounded_text,
        _counter=budget._counter,
    )
    return namespace


def _cgroup_fixture(root: Path) -> None:
    for name, value in {
        "memory.current": "100",
        "memory.peak": "150",
        "memory.max": "805306368",
        "pids.current": "2",
        "pids.peak": "3",
        "pids.max": "128",
        "cpu.max": "100000 100000",
        "cpu.stat": "usage_usec 8\nuser_usec 5\nsystem_usec 3\nnr_periods 4\n"
        "nr_throttled 1\nthrottled_usec 2\n",
        "memory.events": "max 1\noom 2\noom_kill 3\noom_group_kill 4\n",
        "pids.events": "max 5\n",
    }.items():
        (root / name).write_text(value, encoding="ascii")


def test_passive_resources_read_actual_bounded_files_and_only_three_mounts(tmp_path):
    namespace = _passive_namespace(tmp_path)
    _cgroup_fixture(tmp_path)
    paths = []

    def statvfs(path):
        paths.append(path)
        return SimpleNamespace(f_frsize=1024, f_blocks=8, f_bavail=3, f_favail=7)

    namespace["os"] = SimpleNamespace(statvfs=statvfs)
    result = namespace["resource_snapshot"]()
    assert result["memory_current_bytes"] == 100
    assert result["memory_peak_bytes"] == 150
    assert result["pids_current"] == 2
    assert result["pids_peak"] == 3
    assert result["cpu_usage_usec"] == 8
    assert result["memory_max_bytes"] == 805306368
    assert result["pids_max"] == 128
    assert result["cpu_quota_usec"] == result["cpu_period_usec"] == 100000
    assert result["memory_events_max"] == 1
    assert result["memory_events_oom"] == 2
    assert result["memory_events_oom_kill"] == 3
    assert result["memory_events_oom_group_kill"] == 4
    assert result["pids_events_max"] == 5
    metadata = tmp_path.stat()
    assert result["_cgroup_identity"] == (metadata.st_dev, metadata.st_ino)
    # These fixed paths reach only the inert, read-only statvfs boundary.
    assert paths == ["/tmp", "/dev/shm", "/home/boca-browser"]  # noqa: S108
    for mount in ("tmp", "shm", "home"):
        assert result[f"{mount}_capacity_bytes"] == 8192
        assert result[f"{mount}_available_bytes"] == 3072
        assert result[f"{mount}_available_inodes"] == 7


@pytest.mark.parametrize(
    "content",
    [
        b"oom -1\n",
        b"oom 9223372036854775808\n",
        b"oom 2\noom 3\n",
        b"oom 2 PRIVATE_FIXTURE_SECRET\n",
        b"oom \xff\n",
        b"x" * 4097,
    ],
)
def test_passive_event_corruption_is_unknown_and_never_reflects_input(tmp_path, content):
    namespace = _passive_namespace(tmp_path)
    _cgroup_fixture(tmp_path)
    (tmp_path / "memory.events").write_bytes(content)
    namespace["os"] = SimpleNamespace(
        statvfs=lambda _path: SimpleNamespace(f_frsize=1024, f_blocks=8, f_bavail=3, f_favail=7)
    )
    result = namespace["resource_snapshot"]()
    assert result["memory_events_oom"] == "UNKNOWN"
    assert result["pids_events_max"] == 5
    assert result["memory_current_bytes"] == 100
    assert "private" not in json.dumps(result).lower()


def test_passive_missing_counters_and_statvfs_failure_stay_unknown(tmp_path):
    namespace = _passive_namespace(tmp_path)

    def unavailable(_path):
        raise OSError("PRIVATE_FIXTURE_SECRET")

    namespace["os"] = SimpleNamespace(statvfs=unavailable)
    result = namespace["resource_snapshot"]()
    assert result and set(value for key, value in result.items() if key != "_cgroup_identity") == {
        "UNKNOWN"
    }
    assert "private" not in json.dumps(result).lower()


def test_passive_limits_and_mount_overflow_do_not_invent_zero(tmp_path):
    namespace = _passive_namespace(tmp_path)
    _cgroup_fixture(tmp_path)
    (tmp_path / "memory.max").write_text("max", encoding="ascii")
    (tmp_path / "cpu.max").write_text("max 100000", encoding="ascii")
    namespace["os"] = SimpleNamespace(
        statvfs=lambda _path: SimpleNamespace(
            f_frsize=4096, f_blocks=2**63 - 1, f_bavail=-1, f_favail=2**63
        )
    )
    result = namespace["resource_snapshot"]()
    assert result["memory_max_bytes"] == result["cpu_quota_usec"] == "UNKNOWN"
    assert result["cpu_period_usec"] == 100000
    assert result["tmp_capacity_bytes"] == "UNKNOWN"
    assert result["tmp_available_bytes"] == "UNKNOWN"
    assert result["tmp_available_inodes"] == "UNKNOWN"


def test_passive_event_deltas_require_two_monotonic_observations(tmp_path):
    namespace = _passive_namespace(tmp_path)
    result = namespace["resource_deltas"](
        {
            "_cgroup_identity": (8, 81),
            "memory_events_max": 2,
            "memory_events_oom": 0,
            "memory_events_oom_kill": "UNKNOWN",
            "memory_events_oom_group_kill": 7,
            "pids_events_max": 4,
            "PRIVATE_FIXTURE_SECRET": 0,
            "memory_current_bytes": 100,
        },
        {
            "_cgroup_identity": (8, 81),
            "memory_events_max": 5,
            "memory_events_oom": 0,
            "memory_events_oom_kill": 1,
            "memory_events_oom_group_kill": 6,
            "pids_events_max": 9,
            "PRIVATE_FIXTURE_SECRET": 1,
            "memory_current_bytes": 50,
        },
    )
    assert result == {
        "memory_events_max": 3,
        "memory_events_oom": 0,
        "memory_events_oom_kill": "UNKNOWN",
        "memory_events_oom_group_kill": "UNKNOWN",
        "pids_events_max": 5,
    }


@pytest.mark.parametrize("identity", [None, (8, 82)])
def test_passive_event_deltas_reject_missing_or_changed_cgroup_identity(tmp_path, identity):
    namespace = _passive_namespace(tmp_path)
    result = namespace["resource_deltas"](
        {"_cgroup_identity": (8, 81), "memory_events_max": 2},
        {"_cgroup_identity": identity, "memory_events_max": 5},
    )
    assert result and set(result.values()) == {"UNKNOWN"}


def test_stderr_snapshot_freezes_real_offset_and_late_reads_only_new_bytes(tmp_path):
    namespace = _passive_namespace(tmp_path)
    with tempfile.TemporaryFile() as stream:
        original = b"Exiting due to channel error. PRIVATE_FIXTURE_SECRET\n"
        stream.write(original)
        stream.flush()
        text, offset, metadata = namespace["stderr_snapshot"](stream.fileno())
        assert text == original.decode()
        assert offset == len(original)
        assert metadata == {
            "stderr_read": "observed",
            "stderr_bytes": len(original),
            "stderr_truncated": "false",
        }
        late = b"<process did exit: exitCode=-11, signal=SIGSEGV>\n"
        stream.write(late)
        stream.flush()
        result = namespace["late_stderr_details"](stream.fileno(), offset)
        assert result["late_stderr_read"] == "observed"
        assert result["late_stderr_bytes"] == len(late)
        assert result["late_stderr_truncated"] == "false"
        assert result["late_exit_code"] == "-11"
        assert result["late_markers"] == "sigsegv"
        assert "channel_error" not in result["late_markers"]
        assert "private" not in json.dumps(result).lower()


def test_stderr_windows_are_bounded_and_truncated_absence_remains_unknown(tmp_path):
    namespace = _passive_namespace(tmp_path)
    with tempfile.TemporaryFile() as stream:
        stream.write(b"x" * 65537)
        stream.flush()
        text, offset, metadata = namespace["stderr_snapshot"](stream.fileno())
        assert len(text) == 65536 and offset == 65537
        assert metadata["stderr_truncated"] == "true"
        stream.write(b"SIGSEGV " + b"x" * 65537)
        stream.flush()
        result = namespace["late_stderr_details"](stream.fileno(), offset)
        assert result["late_stderr_read"] == "observed"
        assert result["late_stderr_truncated"] == "true"
        assert result["late_markers"] == "UNKNOWN"
        assert result["late_categories"] == "UNKNOWN"
        assert result["late_exit_code"] == "UNKNOWN"
        assert result["late_missing_library"] == "UNKNOWN"


@pytest.mark.parametrize("offset", ["UNKNOWN", -1, True, 2**63])
def test_late_stderr_unknown_or_invalid_offset_cannot_report_absence(tmp_path, offset):
    namespace = _passive_namespace(tmp_path)
    with tempfile.TemporaryFile() as stream:
        result = namespace["late_stderr_details"](stream.fileno(), offset)
    assert set(result.values()) == {"UNKNOWN"}


def test_stderr_truncation_or_unavailable_descriptor_is_unknown(tmp_path):
    namespace = _passive_namespace(tmp_path)
    with tempfile.TemporaryFile() as stream:
        stream.write(b"before")
        stream.flush()
        _text, offset, _metadata = namespace["stderr_snapshot"](stream.fileno())
        stream.truncate(0)
        result = namespace["late_stderr_details"](stream.fileno(), offset)
        fd = stream.fileno()
    assert set(result.values()) == {"UNKNOWN"}
    text, offset, metadata = namespace["stderr_snapshot"](fd)
    assert text == "" and offset == "UNKNOWN"
    assert metadata == {
        "stderr_read": "unavailable",
        "stderr_bytes": "UNKNOWN",
        "stderr_truncated": "UNKNOWN",
    }


@pytest.fixture
def classify() -> Callable[[str], dict[str, str]]:
    namespace = _definitions("failure_details")
    return cast(Callable[[str], dict[str, str]], namespace["failure_details"])


@pytest.mark.parametrize(
    "library",
    ["libgstcodecparsers-1.0.so.0", "libgstwebrtc-1.0.so.0", "libgtk-4.so.1"],
)
def test_loader_receipt_keeps_only_explicit_public_soname(classify, library: str) -> None:
    details = classify(
        "/private/fixture/runner: error while loading shared libraries: "
        + library
        + ": cannot open shared object file: No such file or directory\n"
        + "<process did exit: exitCode=127, signal=null>"
    )
    assert details == {
        "categories": "library",
        "exit_code": "127",
        "missing_library": library,
        "markers": "none",
        "protocol": "none",
        "xpcom": "none",
    }
    assert "/private/" not in json.dumps(details)


@pytest.mark.parametrize(
    "candidate",
    [
        "libPRIVATE_FIXTURE_SECRET.so",
        "../../private/libgstcodecparsers-1.0.so.0",
        "https://private.invalid/bearer",
        "libgstcodecparsers-1.0.so.0?token=PRIVATE_FIXTURE_SECRET",
        "x" * 129,
        "libgstcodecparsers-1.0.so.0\nPRIVATE_FIXTURE_SECRET",
    ],
)
def test_unknown_or_hostile_loader_names_never_become_public(classify, candidate: str) -> None:
    details = classify("error while loading shared libraries: " + candidate + ": missing")
    assert details["missing_library"] == "unlisted"
    serialized = json.dumps(details)
    assert "private" not in serialized.lower()
    assert "/" not in serialized
    assert "token" not in serialized
    assert len(serialized) < 512


def test_soname_without_loader_failure_is_not_reported_missing(classify) -> None:
    details = classify("loaded libgstcodecparsers-1.0.so.0; page closed")
    assert details["missing_library"] == "none"
    assert details["markers"] == "none"
    assert details["categories"] == "unclassified"


def test_firefox_failure_markers_are_fixed_and_do_not_reflect_stderr(classify) -> None:
    details = classify(
        "glxtest: Unable to open a connection to the X server\n"
        "RenderCompositorSWGL failed mapping default framebuffer\n"
        "Exiting due to channel error. /private/profile PRIVATE_FIXTURE_SECRET\n"
        "No space left on device\n"
        "<process did exit: exitCode=0, signal=null>"
    )
    assert details["markers"] == "glxtest,swgl,channel_error,no_space"
    assert details["exit_code"] == "0"
    assert "private" not in json.dumps(details).lower()


def test_failure_details_scan_is_bounded(classify) -> None:
    details = classify(
        "x" * 81920
        + "error while loading shared libraries: libgstcodecparsers-1.0.so.0: missing"
        + " Sandbox: CanCreateUserNamespace clone failure"
    )
    assert details == {
        "categories": "unclassified",
        "exit_code": "unknown",
        "missing_library": "none",
        "markers": "none",
        "protocol": "none",
        "xpcom": "none",
    }


def test_technical_signal_output_is_fixed_and_bounded(classify) -> None:
    details = classify(
        "sandbox operation not permitted shared library out of memory "
        "fork failed SIGSYS glxtest RenderCompositorSWGL "
        "Exiting due to channel error No space left on device "
        "Read-only file system CanCreateUserNamespace "
        "Failed to connect to the bus Crash Annotation "
        "no DISPLAY environment variable specified "
        "<process did exit: exitCode=-11, signal=SIGSEGV>"
    )
    assert details["categories"] == "sandbox,permission,library,memory,process,signal"
    assert details["exit_code"] == "-11"
    assert details["markers"]
    assert len(json.dumps(details)) < 512


def test_xpcom_hexadecimal_failure_is_not_a_process_exit(classify) -> None:
    details = classify(
        "Browser.new_page: Protocol error (Browser.createBrowserContext): "
        "Component returned failure code: 0x80004005 (NS_ERROR_FAILURE)"
    )
    assert details["exit_code"] == "unknown"
    assert details["protocol"] == "Browser.createBrowserContext"
    assert details["xpcom"] == "failure"


@pytest.mark.parametrize("text", ["exitCode=0", "exit code:0", "code=127"])
def test_numeric_code_without_process_exit_envelope_is_not_an_exit(classify, text) -> None:
    assert classify(text)["exit_code"] == "unknown"


@pytest.mark.parametrize(
    "message",
    [
        "Protocol error (Browser.PRIVATE_FIXTURE_SECRET): NS_ERROR_PRIVATE_FIXTURE_SECRET",
        "Protocol error (Browser.newPage_PRIVATE_FIXTURE_SECRET): NS_ERROR_FAILURE_PRIVATE",
        "Protocol error (https://private.invalid/bearer): NS_ERROR_PRIVATE_FIXTURE_SECRET",
        "Protocol error (" + "x" * 81 + "): NS_ERROR_PRIVATE_FIXTURE_SECRET",
    ],
)
def test_unknown_protocol_and_xpcom_names_never_become_public(classify, message) -> None:
    details = classify(message)
    assert details["protocol"] == details["xpcom"] == "unlisted"
    assert "private" not in json.dumps(details).lower()
    assert "/" not in json.dumps(details)
    assert len(json.dumps(details)) < 512


def test_fixed_protocol_and_xpcom_labels_do_not_reflect_private_error_suffix(classify) -> None:
    details = classify(
        "Protocol error (Page.setInitScripts): NS_ERROR_FILE_NO_DEVICE_SPACE "
        "NS_ERROR_FILE_ACCESS_DENIED /private/path?token=PRIVATE_FIXTURE_SECRET"
    )
    assert details["protocol"] == "Page.setInitScripts"
    assert details["xpcom"] == "file_no_space,file_access_denied"
    assert "private" not in json.dumps(details).lower()


class Error(Exception):
    """Inert boundary with the same closed class name as a Playwright error."""


class _BrowserBoundary:
    def __init__(
        self, failures=(), *, error_type=Error, wrong_url=False, disconnect_after_goto=False
    ):
        self.failures = set(failures)
        self.error_type = error_type
        self.wrong_url = wrong_url
        self.disconnect_after_goto = disconnect_after_goto
        self.events: list[str] = []
        self.stderr = ""
        self.stderr_stream = None
        self.on_step = None
        self.connected = False
        self.context_options: dict[str, object] = {}
        self.launch_options: dict[str, object] = {}
        boundary = self

        class Page:
            url = "about:unexpected" if boundary.wrong_url else "about:blank"

            def goto(self, url, *, timeout):
                assert url == "about:blank" and timeout == 10000
                boundary.step("goto")
                if boundary.disconnect_after_goto:
                    boundary.connected = False

        class Context:
            def new_page(self):
                boundary.step("new_page")
                return Page()

            def close(self):
                boundary.step("context_close")

        class Browser:
            def new_context(self, **options):
                boundary.context_options = options
                boundary.step("new_context")
                return Context()

            def is_connected(self):
                boundary.step("connection_observation")
                return boundary.connected

            def close(self):
                boundary.step("browser_close")
                boundary.connected = False

        class BrowserType:
            def launch(self, **options):
                boundary.launch_options = options
                boundary.step("launch")
                boundary.connected = True
                return Browser()

        class Driver:
            def __enter__(self):
                boundary.step("driver_start")
                return SimpleNamespace(
                    chromium=BrowserType(), firefox=BrowserType(), webkit=BrowserType()
                )

            def __exit__(self, *_args):
                boundary.step("driver_close")

        self.driver = Driver()

    def step(self, phase):
        self.events.append(phase)
        if self.on_step is not None:
            self.on_step(phase)
        if phase in {"context_close", "browser_close", "driver_close"}:
            # A later cleanup exit or error must never replace the first snapshot.
            late = "<process did exit: exitCode=0, signal=null> NS_ERROR_FILE_ACCESS_DENIED"
            self.stderr += late
            if self.stderr_stream is not None:
                self.stderr_stream.write(late.encode())
                self.stderr_stream.flush()
        if phase in self.failures:
            raise self.error_type(
                "Protocol error (Browser.newPage): NS_ERROR_FAILURE PRIVATE_FIXTURE_SECRET"
            )


def _run_probe(namespace, boundary, name="firefox"):
    namespace["sync_playwright"] = lambda: boundary.driver
    with tempfile.TemporaryFile() as stream:
        boundary.stderr_stream = stream
        stream.write(boundary.stderr.encode())
        stream.flush()

        def read_stderr():
            boundary.events.append("read_stderr")
            return namespace["stderr_snapshot"](stream.fileno())

        def read_late_stderr(offset):
            boundary.events.append("read_late_stderr")
            return namespace["late_stderr_details"](stream.fileno(), offset)

        return namespace["probe_engine"](name, read_stderr, read_late_stderr)


@pytest.fixture
def probe(tmp_path):
    namespace = _passive_namespace(tmp_path)
    _cgroup_fixture(tmp_path)
    namespace["os"] = SimpleNamespace(
        fstat=os.fstat,
        pread=os.pread,
        statvfs=lambda _path: SimpleNamespace(f_frsize=1024, f_blocks=8, f_bavail=3, f_favail=7),
    )

    def run(boundary, name="firefox"):
        return _run_probe(namespace, boundary, name)

    return run


@pytest.mark.parametrize("engine", ["chromium", "firefox", "webkit"])
def test_probe_requires_explicit_runtime_context_and_every_close_before_pass(probe, engine):
    boundary = _BrowserBoundary()
    result = probe(boundary, engine)
    expected = {
        "state": "PASS",
        "phase": "complete",
        "reason": "none",
        "connected_before_close": "true",
        "context_created": "true",
        "page_created": "true",
        "context_close": "closed",
        "browser_close": "closed",
        "driver_close": "closed",
    }
    assert {key: result[key] for key in expected} == expected
    assert result["before_memory_max_bytes"] == 805306368
    assert not any(key.startswith(("failure_", "delta_", "late_")) for key in result)
    assert boundary.context_options == {
        "java_script_enabled": True,
        "service_workers": "block",
        "accept_downloads": False,
        "ignore_https_errors": False,
    }
    expected_launch = {"headless": True, "timeout": 20000}
    if engine == "chromium":
        expected_launch.update(chromium_sandbox=True, args=["--disable-background-networking"])
    assert boundary.launch_options == expected_launch
    assert boundary.events == [
        "driver_start",
        "launch",
        "new_context",
        "new_page",
        "goto",
        "connection_observation",
        "context_close",
        "browser_close",
        "driver_close",
    ]


@pytest.mark.parametrize(
    ("failure", "context_created", "page_created"),
    [
        ("driver_start", False, False),
        ("launch", False, False),
        ("new_context", False, False),
        ("new_page", True, False),
        ("goto", True, True),
        ("context_close", True, True),
        ("browser_close", True, True),
        ("driver_close", True, True),
    ],
)
def test_probe_reports_exact_failure_phase_and_never_passes_failed_close(
    probe, failure, context_created, page_created
):
    boundary = _BrowserBoundary({failure})
    result = probe(boundary)
    assert result["state"] == "NO_GO"
    assert result["phase"] == failure
    assert result["context_created"] == str(context_created).lower()
    assert result["page_created"] == str(page_created).lower()
    for close in ("context_close", "browser_close", "driver_close"):
        assert boundary.events.count(close) <= 1
    if context_created:
        assert boundary.events.count("context_close") == 1
    if failure not in {"driver_start", "launch"}:
        assert boundary.events.count("browser_close") == 1
    if failure != "driver_start":
        assert boundary.events.count("driver_close") == 1
    if failure.endswith("_close"):
        assert result[failure] == "failed"
    assert "private" not in json.dumps(result).lower()


def test_first_failure_snapshot_precedes_cleanup_and_survives_every_close_error(probe):
    boundary = _BrowserBoundary({"new_page", "context_close", "browser_close", "driver_close"})
    result = probe(boundary)
    assert result["state"] == "NO_GO" and result["phase"] == "new_page"
    assert result["reason"] == "Error"
    assert result["exit_code"] == "unknown"
    assert result["xpcom"] == "failure"
    assert result["connected_before_close"] == "true"
    assert result["context_close"] == result["browser_close"] == result["driver_close"] == "failed"
    assert boundary.events.index("read_stderr") < boundary.events.index("context_close")
    assert boundary.events.count("read_stderr") == 1
    assert boundary.events.index("read_late_stderr") > boundary.events.index("driver_close")
    assert result["late_exit_code"] == "0"
    assert result["late_xpcom"] == "file_access_denied"


def test_probe_keeps_unknown_exception_class_and_message_private(probe):
    private_error = type("PRIVATE_FIXTURE_SECRET", (Exception,), {})
    result = probe(_BrowserBoundary({"goto"}, error_type=private_error))
    assert result["state"] == "NO_GO" and result["reason"] == "UnexpectedError"
    assert "private" not in json.dumps(result).lower()


def test_probe_retains_blank_url_assertion_and_cleanup(probe):
    boundary = _BrowserBoundary(wrong_url=True)
    result = probe(boundary)
    assert result["state"] == "NO_GO" and result["phase"] == "goto"
    assert result["reason"] == "RuntimeError" and result["markers"] == "blank_url_mismatch"
    assert result["context_close"] == result["browser_close"] == result["driver_close"] == "closed"


def test_failed_connection_observation_is_unknown_and_does_not_replace_original_error(probe):
    result = probe(_BrowserBoundary({"new_page", "connection_observation"}))
    assert result["state"] == "NO_GO" and result["phase"] == "new_page"
    assert result["connected_before_close"] == "unknown"
    assert result["context_close"] == result["browser_close"] == "closed"


@pytest.mark.parametrize("unavailable", [False, True])
def test_connection_must_be_confirmed_before_idempotent_close_can_pass(probe, unavailable):
    boundary = _BrowserBoundary(
        {"connection_observation"} if unavailable else (),
        disconnect_after_goto=not unavailable,
    )
    result = probe(boundary)
    assert result["state"] == "NO_GO" and result["phase"] == "connection_check"
    assert result["connected_before_close"] == ("unknown" if unavailable else "false")
    assert result["context_close"] == result["browser_close"] == result["driver_close"] == "closed"


def test_probe_freezes_resource_events_at_first_fault_before_cleanup(tmp_path):
    namespace = _passive_namespace(tmp_path)
    _cgroup_fixture(tmp_path)
    boundary = _BrowserBoundary({"goto"})
    namespace["os"] = SimpleNamespace(
        fstat=os.fstat,
        pread=os.pread,
        statvfs=lambda _path: SimpleNamespace(f_frsize=1024, f_blocks=8, f_bavail=3, f_favail=7),
    )

    def change_events(phase):
        if phase == "goto":
            (tmp_path / "memory.events").write_text(
                "max 4\noom 3\noom_kill 4\noom_group_kill 4\n", encoding="ascii"
            )
            (tmp_path / "pids.events").write_text("max 7\n", encoding="ascii")
        elif phase == "context_close":
            (tmp_path / "memory.events").write_text(
                "max 99\noom 99\noom_kill 99\noom_group_kill 99\n", encoding="ascii"
            )

    boundary.on_step = change_events
    actual_snapshot = namespace["resource_snapshot"]

    def capture_resources():
        boundary.events.append("resource_snapshot")
        return actual_snapshot()

    namespace["resource_snapshot"] = capture_resources
    result = _run_probe(namespace, boundary)
    assert result["state"] == "NO_GO" and result["phase"] == "goto"
    assert result["before_memory_events_oom_kill"] == 3
    assert result["failure_memory_events_oom_kill"] == 4
    assert result["delta_memory_events_oom_kill"] == 1
    assert result["delta_memory_events_max"] == 3
    assert result["delta_pids_events_max"] == 2
    assert boundary.events.count("resource_snapshot") == 2
    assert boundary.events[0] == "resource_snapshot"
    assert boundary.events.index("read_stderr") < boundary.events.index("context_close")
    assert boundary.events.index("resource_snapshot", 1) < boundary.events.index("context_close")
    assert boundary.events[-1] == "read_late_stderr"
    assert result["exit_code"] == "unknown" and result["late_exit_code"] == "0"
    assert "cgroup_identity" not in json.dumps(result)


def test_missing_passive_observations_do_not_change_functional_pass(tmp_path):
    namespace = _passive_namespace(tmp_path)

    def unavailable(_path):
        raise OSError("PRIVATE_FIXTURE_SECRET")

    namespace["os"] = SimpleNamespace(statvfs=unavailable, fstat=os.fstat, pread=os.pread)
    result = _run_probe(namespace, _BrowserBoundary())
    assert result["state"] == "PASS" and result["phase"] == "complete"
    assert set(value for key, value in result.items() if key.startswith("before_")) == {"UNKNOWN"}
    assert "private" not in json.dumps(result).lower()


def test_failed_stderr_metadata_cannot_replace_primary_failure_or_invent_late_exit(tmp_path):
    namespace = _passive_namespace(tmp_path)

    def unavailable(_value):
        raise OSError("PRIVATE_FIXTURE_SECRET")

    namespace["os"] = SimpleNamespace(statvfs=unavailable, fstat=unavailable, pread=os.pread)
    result = _run_probe(namespace, _BrowserBoundary({"goto"}))
    assert result["state"] == "NO_GO" and result["phase"] == "goto"
    assert result["reason"] == "Error" and result["xpcom"] == "failure"
    assert result["exit_code"] == "unknown"
    assert result["stderr_read"] == "unavailable"
    assert set(value for key, value in result.items() if key.startswith("late_")) == {"UNKNOWN"}
    assert result["context_close"] == result["browser_close"] == result["driver_close"] == "closed"
    assert "private" not in json.dumps(result).lower()
