"""Fail closed when an accepted RCA loses its executed regression test."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REGISTRY = Path("docs/quality/rca-lessons.json")
LESSON_FIELDS = {
    "id",
    "issue",
    "fix_pr",
    "root_cause",
    "prevention",
    "regression_tests",
}
SELECTOR = re.compile(r"tests/test_[a-z0-9_]+\.py::test_[a-z0-9_]+\Z")
MAX_REGISTRY_BYTES = 65536
MAX_JUNIT_BYTES = 2_000_000
GIT = "/usr/bin/git"


class LessonError(ValueError):
    """The checked-in learning contract cannot be verified."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LessonError("duplicate JSON field")
        result[key] = value
    return result


def _decode_registry(text: str) -> dict[str, dict[str, Any]]:
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise LessonError("invalid RCA registry JSON") from exc
    return validate_registry(document)


def validate_registry(document: object) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict) or set(document) != {"version", "lessons"}:
        raise LessonError("RCA registry fields must be version and lessons")
    if type(document["version"]) is not int or document["version"] != 1:
        raise LessonError("unsupported RCA registry version")
    entries = document["lessons"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise LessonError("RCA registry requires 1..100 lessons")
    lessons: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != LESSON_FIELDS:
            raise LessonError("RCA lesson fields are invalid")
        issue, pr = entry["issue"], entry["fix_pr"]
        if (
            type(issue) is not int
            or type(pr) is not int
            or not 1 <= issue <= 999999
            or not 1 <= pr <= 999999
            or entry["id"] != f"RCA-{issue}"
        ):
            raise LessonError("RCA lesson issue/PR identity is invalid")
        if entry["id"] in lessons:
            raise LessonError("duplicate RCA lesson ID")
        for key in ("root_cause", "prevention"):
            value = entry[key]
            if (
                not isinstance(value, str)
                or not 20 <= len(value) <= 300
                or "\n" in value
                or "\r" in value
            ):
                raise LessonError("RCA lesson explanation is missing or unbounded")
        selectors = entry["regression_tests"]
        if (
            not isinstance(selectors, list)
            or not 1 <= len(selectors) <= 8
            or any(not isinstance(item, str) or not SELECTOR.fullmatch(item) for item in selectors)
        ):
            raise LessonError("RCA regression selector is invalid")
        if len(selectors) != len(set(selectors)):
            raise LessonError("duplicate RCA regression selector")
        lessons[entry["id"]] = entry
    return lessons


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REGISTRY_BYTES:
        raise LessonError("RCA registry is absent, linked or oversized")
    try:
        return _decode_registry(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise LessonError("invalid RCA registry encoding") from exc


def check_retention(
    accepted: dict[str, dict[str, Any]], proposed: dict[str, dict[str, Any]]
) -> None:
    """Preserve accepted IDs and test selectors across a PR or main push."""
    for lesson_id, old in accepted.items():
        new = proposed.get(lesson_id)
        if new is None:
            raise LessonError(f"accepted lesson removed: {lesson_id}")
        if old["issue"] != new["issue"] or old["fix_pr"] != new["fix_pr"]:
            raise LessonError(f"accepted lesson identity changed: {lesson_id}")
        if not set(old["regression_tests"]) <= set(new["regression_tests"]):
            raise LessonError(f"accepted regression removed: {lesson_id}")


def load_junit(path: Path) -> set[str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JUNIT_BYTES:
        raise LessonError("pytest report is absent, linked or oversized")
    try:
        document = path.read_bytes()
        if b"<!" in document:
            raise LessonError("pytest report contains a forbidden XML declaration")
        # Bounded, locally generated pytest XML with DTD/entities forbidden.
        root = ET.fromstring(document)  # noqa: S314
    except ET.ParseError as exc:
        raise LessonError("pytest report is invalid XML") from exc
    if root.tag != "testsuites":
        raise LessonError("pytest report root is invalid")
    executed: set[str] = set()
    for case in root.findall("./testsuite/testcase"):
        classname, name = case.get("classname", ""), case.get("name", "")
        nodeid = classname.replace(".", "/") + ".py::" + name
        if not nodeid.startswith("tests/") or "::test_" not in nodeid:
            raise LessonError("pytest report has an invalid test identity")
        if case.find("skipped") is not None:
            raise LessonError("pytest report includes a skipped or xfailed test")
        if case.find("failure") is not None or case.find("error") is not None:
            raise LessonError("pytest report includes a failed test")
        if nodeid in executed:
            raise LessonError("pytest report includes a duplicate test")
        executed.add(nodeid)
    if not executed:
        raise LessonError("pytest report has no executed tests")
    return executed


def validate_executed(lessons: dict[str, dict[str, Any]], executed: set[str]) -> None:
    for lesson_id, lesson in lessons.items():
        for selector in lesson["regression_tests"]:
            if selector not in executed and not any(
                case.startswith(selector + "[") for case in executed
            ):
                raise LessonError(f"regression not executed: {lesson_id} {selector}")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Literal executable/arguments only; no shell or user-supplied ref.
    return subprocess.run(  # noqa: S603
        [GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def _baseline(root: Path) -> dict[str, dict[str, Any]]:
    try:
        parent = _git(root, "rev-parse", "--verify", "HEAD^1")
        if parent.returncode != 0:
            raise LessonError("baseline commit unavailable; checkout requires fetch-depth 2")
        available = _git(root, "ls-tree", "--name-only", "HEAD^1", "--", str(REGISTRY))
        if available.returncode != 0:
            raise LessonError("cannot inspect accepted RCA baseline")
        if not available.stdout.strip():
            return {}
        old = _git(root, "show", f"HEAD^1:{REGISTRY}")
        if old.returncode != 0 or len(old.stdout.encode("utf-8")) > MAX_REGISTRY_BYTES:
            raise LessonError("accepted RCA baseline is unavailable")
    except subprocess.TimeoutExpired as exc:
        raise LessonError("RCA baseline read timed out") from exc
    return _decode_registry(old.stdout)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_rca_lessons.py <pytest-junit.xml>", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    try:
        proposed = load_registry(root / REGISTRY)
        accepted = _baseline(root)
        check_retention(accepted, proposed)
        executed = load_junit(Path(args[0]))
        validate_executed(proposed, executed)
    except LessonError as exc:
        print(f"RCA_GATE_FAIL: {exc}", file=sys.stderr)
        return 1
    selectors = sum(len(entry["regression_tests"]) for entry in proposed.values())
    print(f"RCA_GATE_PASS: {len(proposed)} lessons, {selectors} executed regression selectors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
