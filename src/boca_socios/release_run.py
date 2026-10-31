"""Validate GitHub's release-run metadata before any host connection."""

from __future__ import annotations

from collections.abc import Mapping


class ReleaseRunError(ValueError):
    """The cited image release is not the approved main-source workflow."""


def validate_release_run(run: object, source_sha: str, release_run_id: str) -> None:
    if not isinstance(run, dict):
        raise ReleaseRunError("invalid release run metadata")
    if type(run.get("id")) is not int or str(run["id"]) != release_run_id:
        raise ReleaseRunError("release run ID mismatch")
    # Artifacts are scoped to a run ID, not to a particular rerun attempt.
    # A successful later attempt could otherwise cite an earlier artifact.
    if type(run.get("run_attempt")) is not int or run["run_attempt"] != 1:
        raise ReleaseRunError("release run must be the first attempt")
    for field, expected in {
        "name": "Boca image release",
        "event": "workflow_dispatch",
        "head_sha": source_sha,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }.items():
        if run.get(field) != expected:
            raise ReleaseRunError(f"release run {field} mismatch")
    path = run.get("path")
    if not isinstance(path, str) or path.partition("@")[0] != ".github/workflows/release-image.yml":
        raise ReleaseRunError("incorrect image release workflow")
    for field, key, expected in (
        ("actor", "login", "mbalbo2023"),
        ("repository", "full_name", "mbalbo2023/boca-socios-assistant"),
    ):
        nested = run.get(field)
        if not isinstance(nested, Mapping) or nested.get(key) != expected:
            raise ReleaseRunError(f"release run {field} mismatch")
