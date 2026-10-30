"""A manual deployment can cite only its exact successful release run."""

from copy import deepcopy

import pytest

from boca_socios.release_run import ReleaseRunError, validate_release_run

SOURCE_SHA = "a" * 40


def valid_run() -> dict[str, object]:
    return {
        "id": 123456,
        "name": "Boca image release",
        "path": ".github/workflows/release-image.yml@refs/heads/main",
        "event": "workflow_dispatch",
        "head_sha": SOURCE_SHA,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
    }


def test_matching_successful_run_passes() -> None:
    validate_release_run(valid_run(), SOURCE_SHA, "123456")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("id", 123457),
        ("name", "Other release"),
        ("path", ".github/workflows/other.yml@main"),
        ("event", "pull_request"),
        ("head_sha", "b" * 40),
        ("head_branch", "feature/not-main"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("actor", {"login": "other"}),
        ("repository", {"full_name": "other/other"}),
    ],
)
def test_wrong_release_run_is_no_go(key: str, value: object) -> None:
    run = deepcopy(valid_run())
    run[key] = value
    with pytest.raises(ReleaseRunError):
        validate_release_run(run, SOURCE_SHA, "123456")


@pytest.mark.parametrize("run", [None, [], {}, {"id": True}])
def test_malformed_release_metadata_is_no_go(run: object) -> None:
    with pytest.raises(ReleaseRunError):
        validate_release_run(run, SOURCE_SHA, "123456")
