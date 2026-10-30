"""Validate an exact first-install dispatch before preparing host access."""

from __future__ import annotations

import re


class DeployInputError(ValueError):
    """A deployment coordinate is absent or outside the Boca-only contract."""


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,11}\Z")


def validate_deploy_inputs(
    image_ref: str, source_sha: str, service: str, resource_budget: str, release_run_id: str
) -> None:
    if not _IMAGE.fullmatch(image_ref):
        raise DeployInputError("invalid immutable image reference")
    if not _SHA.fullmatch(source_sha):
        raise DeployInputError("invalid source commit SHA")
    if service != "controller":
        raise DeployInputError("only controller is allowed")
    if resource_budget != "0.5cpu-256m-64pids":
        raise DeployInputError("invalid resource budget")
    if not _RUN.fullmatch(release_run_id):
        raise DeployInputError("invalid release run ID")
