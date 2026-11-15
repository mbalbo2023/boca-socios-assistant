"""Exercise the actual offline diagnostic classifier without launching a browser."""

from __future__ import annotations

import ast
import json
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/boca-playwright-offline-diagnostic.yml"
)


@pytest.fixture
def classify() -> Callable[[str], dict[str, str]]:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Probe each Playwright engine in a separate offline process\n", 1
    )[1]
    source = step.split('--entrypoint python "$IMAGE" -c \'\n', 1)[1].split(
        "\n          ' ; then\n", 1
    )[0]
    parsed = ast.parse(textwrap.dedent(source))
    definitions = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name == "failure_details"
    ]
    assert len(definitions) == 1, "the public receipt needs one bounded technical classifier"
    module = ast.Module(body=definitions, type_ignores=[])
    namespace: dict[str, object] = {"re": re}
    # Only the reviewed pure classifier is executed; no Playwright import or main body.
    exec(compile(module, str(WORKFLOW), "exec"), namespace)  # noqa: S102
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
        + "process did exit: exitCode=127, signal=null"
    )
    assert details == {
        "categories": "library",
        "exit_code": "127",
        "missing_library": library,
        "markers": "none",
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
        "process did exit: exitCode=0, signal=null"
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
    }


def test_technical_signal_output_is_fixed_and_bounded(classify) -> None:
    details = classify(
        "sandbox operation not permitted shared library out of memory "
        "fork failed SIGSYS glxtest RenderCompositorSWGL "
        "Exiting due to channel error No space left on device "
        "Read-only file system CanCreateUserNamespace "
        "Failed to connect to the bus Crash Annotation "
        "no DISPLAY environment variable specified "
        "process did exit: exitCode=-11, signal=SIGSEGV"
    )
    assert details["categories"] == "sandbox,permission,library,memory,process,signal"
    assert details["exit_code"] == "-11"
    assert details["markers"]
    assert len(json.dumps(details)) < 512
