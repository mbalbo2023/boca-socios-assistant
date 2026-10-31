"""A fresh manual dispatch cannot republish the same source SHA."""

import json
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_release_dispatch.py"
SHA = "a" * 40


def _api_response() -> dict[str, object]:
    return {
        "total_count": 1,
        "workflow_runs": [
            {
                "id": 12345,
                "head_sha": SHA,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "run_attempt": 1,
            }
        ],
    }


def test_only_current_first_attempt_is_accepted() -> None:
    module = runpy.run_path(str(SCRIPT))
    module["validate_dispatch_history"](_api_response(), SHA, "12345")


def test_duplicate_fresh_dispatch_is_no_go() -> None:
    module = runpy.run_path(str(SCRIPT))
    response = _api_response()
    response["total_count"] = 2
    response["workflow_runs"].append(dict(response["workflow_runs"][0], id=67890))
    with pytest.raises(module["DispatchError"], match="duplicated"):
        module["validate_dispatch_history"](response, SHA, "12345")


@pytest.mark.parametrize(
    "change",
    [
        {"total_count": 0},
        {"total_count": True},
        {"workflow_runs": []},
        {"workflow_runs": [{"id": 54321}]},
        {"workflow_runs": [{"head_sha": "b" * 40}]},
        {"workflow_runs": [{"head_branch": "feature"}]},
        {"workflow_runs": [{"event": "push"}]},
        {"workflow_runs": [{"run_attempt": 2}]},
    ],
)
def test_duplicate_or_mismatched_dispatch_is_no_go(change: dict[str, object]) -> None:
    module = runpy.run_path(str(SCRIPT))
    response = _api_response()
    for key, value in change.items():
        if key == "workflow_runs" and value and isinstance(value, list):
            response[key][0].update(value[0])
        else:
            response[key] = value
    with pytest.raises(module["DispatchError"]):
        module["validate_dispatch_history"](response, SHA, "12345")


def test_bounded_json_rejects_duplicate_fields_symlink_and_oversize(tmp_path: Path) -> None:
    module = runpy.run_path(str(SCRIPT))
    path = tmp_path / "runs.json"
    path.write_text('{"total_count":1,"total_count":1,"workflow_runs":[]}')
    with pytest.raises(module["DispatchError"]):
        module["load_history"](path)
    path.write_text(json.dumps(_api_response()))
    module["validate_dispatch_history"](module["load_history"](path), SHA, "12345")
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(module["DispatchError"]):
        module["load_history"](link)
    path.write_text("x" * 131073)
    with pytest.raises(module["DispatchError"]):
        module["load_history"](path)


def test_release_checks_unique_dispatch_before_build_and_before_push() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/release-image.yml"
    ).read_text()
    publish = workflow.split("  publish:\n", maxsplit=1)[1]
    checks = [
        index
        for index in range(len(publish))
        if publish.startswith("python scripts/check_release_dispatch.py", index)
    ]
    assert len(checks) == 2
    assert checks[0] < publish.index("Build one local controller image")
    assert publish.index("Scan the image that will be published") < checks[1]
    assert checks[1] < publish.index("Log in only after successful scan")
    assert publish.count("event=workflow_dispatch&head_sha=$GITHUB_SHA&per_page=2") == 2
    assert "actions: read" in publish
