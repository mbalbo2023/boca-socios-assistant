"""Accepted RCA lessons must remain executable regression contracts."""

import json
import runpy
from pathlib import Path

import pytest

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/check_rca_lessons.py")
)
LessonError = MODULE["LessonError"]
check_retention = MODULE["check_retention"]
load_registry = MODULE["load_registry"]
validate_collected = MODULE["validate_collected"]
validate_registry = MODULE["validate_registry"]


def _registry() -> dict[str, object]:
    return {
        "version": 1,
        "lessons": [
            {
                "id": "RCA-80",
                "issue": 80,
                "fix_pr": 81,
                "root_cause": "A rootless UID map made a host-owned private key unreadable.",
                "prevention": "Verify ownership and reading by the actual container UID.",
                "regression_tests": [
                    "tests/test_host_first_deploy.py::test_key_volume_is_created_once_and_verified_without_host_secret"
                ],
            }
        ],
    }


def test_collected_regression_is_required_and_parameterized_cases_count() -> None:
    lessons = validate_registry(_registry())
    selector = lessons["RCA-80"]["regression_tests"][0]
    validate_collected(lessons, {selector + "[one]", selector + "[two]"})
    with pytest.raises(LessonError, match="not collected"):
        validate_collected(lessons, {"tests/test_host_first_deploy.py::test_unrelated"})


def test_accepted_lesson_and_its_tests_cannot_disappear() -> None:
    accepted = validate_registry(_registry())
    with pytest.raises(LessonError, match="removed"):
        check_retention(accepted, {})
    changed = _registry()
    changed["lessons"][0]["regression_tests"] = [
        "tests/test_host_first_deploy.py::test_renamed_without_review"
    ]
    with pytest.raises(LessonError, match="removed"):
        check_retention(accepted, validate_registry(changed))


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "lessons.json"
    path.write_text('{"version":1,"version":1,"lessons":[]}', encoding="utf-8")
    with pytest.raises(LessonError, match="duplicate"):
        load_registry(path)


def test_schema_rejects_duplicate_ids_unknown_fields_and_unsafe_selectors() -> None:
    duplicate = _registry()
    duplicate["lessons"].append(dict(duplicate["lessons"][0]))
    with pytest.raises(LessonError, match="duplicate"):
        validate_registry(duplicate)
    unknown = _registry()
    unknown["lessons"][0]["disable_gate"] = True
    with pytest.raises(LessonError, match="fields"):
        validate_registry(unknown)
    unsafe = _registry()
    unsafe["lessons"][0]["regression_tests"] = ["../../other-project/test.py::test_x"]
    with pytest.raises(LessonError, match="selector"):
        validate_registry(unsafe)


def test_actual_registry_is_well_formed() -> None:
    root = Path(__file__).resolve().parents[1]
    lessons = load_registry(root / "docs/quality/rca-lessons.json")
    assert {"RCA-80", "RCA-88", "RCA-90"} <= lessons.keys()
    assert json.loads((root / "docs/quality/rca-lessons.json").read_text())["version"] == 1
