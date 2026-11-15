"""Exercise the actual offline diagnostic classifier without launching a browser."""

from __future__ import annotations

import ast
import json
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

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
    namespace: dict[str, object] = {"re": re}
    # No Playwright import or workflow main body is executed.
    exec(compile(module, str(WORKFLOW), "exec"), namespace)  # noqa: S102
    return namespace


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
        if phase in {"context_close", "browser_close", "driver_close"}:
            # A later cleanup exit or error must never replace the first snapshot.
            self.stderr += "<process did exit: exitCode=0, signal=null> NS_ERROR_FILE_ACCESS_DENIED"
        if phase in self.failures:
            raise self.error_type(
                "Protocol error (Browser.newPage): NS_ERROR_FAILURE PRIVATE_FIXTURE_SECRET"
            )

    def read_stderr(self):
        self.events.append("read_stderr")
        return self.stderr


@pytest.fixture
def probe():
    namespace = _definitions("failure_details", "probe_engine")

    def run(boundary, name="firefox"):
        namespace["sync_playwright"] = lambda: boundary.driver
        return namespace["probe_engine"](name, boundary.read_stderr)

    return run


@pytest.mark.parametrize("engine", ["chromium", "firefox", "webkit"])
def test_probe_requires_explicit_runtime_context_and_every_close_before_pass(probe, engine):
    boundary = _BrowserBoundary()
    result = probe(boundary, engine)
    assert result == {
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
