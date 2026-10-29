"""Bind a registry push result to the exact reviewed controller commit."""

from __future__ import annotations

import re


class ReleaseError(ValueError):
    """Image publication evidence is missing or ambiguous."""


_REPOSITORY = "ghcr.io/mbalbo2023/boca-socios-assistant"
_SHA = re.compile(r"[0-9a-f]{40}\Z")


def parse_push_digest(output: str, commit_sha: str) -> str:
    """Return an immutable OCI reference only for one exact push summary."""
    if not _SHA.fullmatch(commit_sha):
        raise ReleaseError("invalid source commit SHA")
    pattern = re.compile(
        rf"^sha-{commit_sha}: digest: (sha256:[0-9a-f]{{64}}) size: [0-9]+$",
        re.MULTILINE,
    )
    matches = pattern.findall(output)
    if len(matches) != 1:
        raise ReleaseError("missing or ambiguous image digest")
    return f"{_REPOSITORY}@{matches[0]}"
