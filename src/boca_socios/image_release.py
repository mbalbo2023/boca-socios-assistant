"""Bind either scanned image push to one reviewed commit and fixed GHCR identity."""

from __future__ import annotations

import re


class ReleaseError(ValueError):
    """Image publication evidence is missing or ambiguous."""


_REPOSITORIES = {
    "controller": "ghcr.io/mbalbo2023/boca-socios-assistant",
    "browser": "ghcr.io/mbalbo2023/boca-socios-assistant-browser",
}
_SHA = re.compile(r"[0-9a-f]{40}\Z")


def parse_push_digest(output: str, commit_sha: str, *, role: str = "controller") -> str:
    """Reject an ambiguous digest or a push log belonging to another image."""
    if not _SHA.fullmatch(commit_sha):
        raise ReleaseError("invalid source commit SHA")
    repository = _REPOSITORIES.get(role)
    if repository is None:
        raise ReleaseError("unknown release image role")
    headers = re.findall(
        r"^The push refers to repository \[([^\]\r\n]+)\]$", output, flags=re.MULTILINE
    )
    # Legacy controller receipts may omit this Docker header. The new browser
    # package must carry its exact header so logs cannot be swapped by role.
    if (role == "browser" and headers != [repository]) or (headers and headers != [repository]):
        raise ReleaseError("release push repository mismatched")
    pattern = re.compile(
        rf"^sha-{commit_sha}: digest: (sha256:[0-9a-f]{{64}}) size: [0-9]+$",
        re.MULTILINE,
    )
    matches = pattern.findall(output)
    if len(matches) != 1:
        raise ReleaseError("missing or ambiguous image digest")
    return f"{repository}@{matches[0]}"
