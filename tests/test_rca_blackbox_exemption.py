"""Regression gate: owner-only blackbox exception is exact and fail-closed.

Only temporary dummy bytes are used. The protected Python modules are never
opened, imported, parsed or executed by these tests.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = run_path(str(ROOT / "scripts/check_rca_lessons.py"))


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, dict[str, object]], set[str], frozenset[str]]:
    """Install a stand-in byte manifest without accessing owner files."""
    fixtures = {
        "src/boca_socios/browser/synthetic.py": b"dummy-synthetic-only",
        "src/boca_socios/browser/ipc_worker.py": b"dummy-ipc-only",
    }
    hashes: dict[str, tuple[int, str]] = {}
    for filename, data in fixtures.items():
        destination = tmp_path / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        hashes[filename] = (len(data), sha256(data).hexdigest())

    implementation = GATE["_owner_blackbox_exemptions"]
    monkeypatch.setitem(implementation.__globals__, "OWNER_BLACKBOX_FILES", hashes)
    allowed = GATE["OWNER_BLACKBOX_SELECTORS"]
    manifest = {
        "version": 1,
        "authority_issue": 288,
        "owner_attestation": "externally_validated_by_owner_2026-11-03",
        "protected_sha256": {name: value[1] for name, value in hashes.items()},
        "exempt_regression_selectors": sorted(allowed),
    }
    path = tmp_path / GATE["OWNER_BLACKBOX_MANIFEST"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    executed = {
        GATE["OWNER_BLACKBOX_GUARD"],
        GATE["OWNER_BLACKBOX_HASH_GUARD"] + "[first-file]",
        GATE["OWNER_BLACKBOX_HASH_GUARD"] + "[second-file]",
    }
    lessons = {
        "RCA-227": {
            "regression_tests": [
                "tests/test_browser_on_demand.py::test_close_during_stubborn_context_exit_never_returns_late_success"
            ]
        }
    }
    return lessons, executed, allowed


def test_legacy_executed_selectors_never_require_blackbox_exception(tmp_path: Path) -> None:
    selector = (
        "tests/test_browser_ipc.py::test_close_during_slow_socket_teardown_fences_late_success"
    )
    lessons = {"RCA-235": {"regression_tests": [selector]}}
    assert GATE["_owner_blackbox_exemptions"](tmp_path, lessons, {selector}) == frozenset()
    GATE["validate_executed"](lessons, {selector})


def test_exact_owner_scope_with_both_guards_can_be_externally_attested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    exempted = GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed)
    assert len(exempted) == 1
    GATE["validate_executed"](lessons, executed, externally_attested=exempted)


def test_missing_controller_guard_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    executed.remove(GATE["OWNER_BLACKBOX_GUARD"])
    with pytest.raises(GATE["LessonError"], match="controller isolation"):
        GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed)


def test_only_one_hash_parameter_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    executed.remove(GATE["OWNER_BLACKBOX_HASH_GUARD"] + "[second-file]")
    with pytest.raises(GATE["LessonError"], match="two-file hash guard"):
        GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed)


def test_changed_owner_bytes_revoke_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    (tmp_path / "src/boca_socios/browser/synthetic.py").write_bytes(b"changed-dummy")
    with pytest.raises(GATE["LessonError"], match="opaque integrity mismatch"):
        GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed)


def test_changed_attestation_scope_revokes_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    path = tmp_path / GATE["OWNER_BLACKBOX_MANIFEST"]
    value = json.loads(path.read_text(encoding="utf-8"))
    value["authority_issue"] = 999
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(GATE["LessonError"], match="scope differs"):
        GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed)


def test_missing_manifest_revokes_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    (tmp_path / GATE["OWNER_BLACKBOX_MANIFEST"]).unlink()
    with pytest.raises(GATE["LessonError"], match="manifest unavailable"):
        GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed)


def test_unrelated_missing_regression_is_never_exempted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    unrelated = "tests/test_host_first_deploy.py::test_unrelated_gate"
    lessons["RCA-275"] = {"regression_tests": [unrelated]}
    assert GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed) == frozenset()
    with pytest.raises(GATE["LessonError"], match="regression not executed"):
        GATE["validate_executed"](lessons, executed)


def test_new_selector_from_an_excluded_test_file_is_not_implicitly_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lessons, executed, _ = _fixture(tmp_path, monkeypatch)
    unreviewed = "tests/test_browser_ipc.py::test_new_unreviewed_regression"
    lessons["RCA-999"] = {"regression_tests": [unreviewed]}
    assert GATE["_owner_blackbox_exemptions"](tmp_path, lessons, executed) == frozenset()
    with pytest.raises(GATE["LessonError"], match="regression not executed"):
        GATE["validate_executed"](lessons, executed)


def test_owner_blackbox_allowlist_exactly_covers_three_historical_lessons() -> None:
    lessons = GATE["load_registry"](ROOT / GATE["REGISTRY"])
    expected = {
        selector
        for issue in ("RCA-227", "RCA-235", "RCA-257")
        for selector in lessons[issue]["regression_tests"]
    }
    assert expected == GATE["OWNER_BLACKBOX_SELECTORS"]
    assert all(
        selector.split("::", 1)[0]
        in ("tests/test_browser_on_demand.py", "tests/test_browser_ipc.py")
        for selector in expected
    )
