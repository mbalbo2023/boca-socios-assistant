"""Validate an exact first-install dispatch before preparing host access."""

from __future__ import annotations

import re


class DeployInputError(ValueError):
    """A deployment coordinate is absent or outside the Boca-only contract."""


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,11}\Z")


def validate_deploy_inputs(
    image_ref: str,
    source_sha: str,
    service: str,
    resource_budget: str,
    release_run_id: str,
    *,
    browser_ipc_v2: bool = False,
    telegram_runtime: bool = False,
    infrastructure_preflight: bool = False,
) -> None:
    if type(infrastructure_preflight) is not bool:
        raise DeployInputError("infrastructure preflight must be explicitly selected")
    if infrastructure_preflight:
        if (
            image_ref
            or release_run_id
            or browser_ipc_v2 is not False
            or telegram_runtime is not False
            or not _SHA.fullmatch(source_sha)
            or service != "controller"
            or resource_budget not in {"1.5cpu-1024m-192pids", "1.75cpu-1152m-224pids"}
        ):
            raise DeployInputError("invalid image-free infrastructure preflight coordinates")
        return
    if not _IMAGE.fullmatch(image_ref):
        raise DeployInputError("invalid immutable image reference")
    if not _SHA.fullmatch(source_sha):
        raise DeployInputError("invalid source commit SHA")
    if service != "controller":
        raise DeployInputError("only controller is allowed")
    if type(browser_ipc_v2) is not bool:
        raise DeployInputError("browser IPC mode must be explicitly selected")
    if type(telegram_runtime) is not bool or telegram_runtime and not browser_ipc_v2:
        raise DeployInputError("Telegram runtime requires the explicit dual browser topology")
    expected_budget = "1.5cpu-1024m-192pids" if browser_ipc_v2 else "0.5cpu-256m-64pids"
    if telegram_runtime:
        expected_budget = "1.75cpu-1152m-224pids"
    if resource_budget != expected_budget:
        raise DeployInputError("invalid resource budget")
    if not _RUN.fullmatch(release_run_id):
        raise DeployInputError("invalid release run ID")


def validate_main_ref(main_ref: object, source_sha: str) -> None:
    """A dispatched SHA must still be the current main HEAD before SSH."""
    if (
        not isinstance(main_ref, dict)
        or main_ref.get("ref") != "refs/heads/main"
        or not isinstance(main_ref.get("object"), dict)
    ):
        raise DeployInputError("current main ref is unavailable")
    object_ref = main_ref["object"]
    sha = object_ref.get("sha")
    if (
        object_ref.get("type") != "commit"
        or not isinstance(sha, str)
        or not _SHA.fullmatch(sha)
        or sha != source_sha
    ):
        raise DeployInputError("current main HEAD differs from dispatch SHA")
