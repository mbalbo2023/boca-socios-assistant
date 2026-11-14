"""Fail-closed R245/R282 exact internal Markdown-only PR classifier.

This has no network, Docker, secrets or host interactions. It verifies the
actual synthetic GitHub merge commit and changed Git modes, never trusting
PR title, labels, a changed-files API, or a guessed base.
"""

from __future__ import annotations

import os
import re
import subprocess

SHA = re.compile(r"[0-9a-f]{40}\Z")
PR_REF = re.compile(r"refs/pull/[1-9][0-9]*/merge\Z")
REPO = "mbalbo2023/boca-socios-assistant"
# This ADR is executable input to an existing workflow-contract regression.
CONTRACT_DOCS = frozenset({"docs/ADR/0159-protected-ops-postcutover-workflow.md"})


def _git(*args: str) -> bytes:
    return subprocess.run(  # noqa: S603 - fixed Git CLI in exact repository checkout
        ("/usr/bin/git", *args),
        check=True,
        capture_output=True,
        timeout=5,
    ).stdout


def docs_only() -> bool:
    env = os.environ
    if not (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_EVENT_NAME") == "pull_request"
        and env.get("GITHUB_REPOSITORY") == REPO
        and env.get("PR_HEAD_REPO") == REPO
        and env.get("PR_BASE_REF") == "main"
        and PR_REF.fullmatch(env.get("GITHUB_REF", ""))
    ):
        return False
    merge, base, head = (env.get(k, "") for k in ("GITHUB_SHA", "PR_BASE_SHA", "PR_HEAD_SHA"))
    if not all(SHA.fullmatch(value) for value in (merge, base, head)):
        return False
    if _git("rev-parse", "--verify", "HEAD").decode().strip() != merge:
        return False
    # A shallow or stale PR head is not a grant to skip source tests.
    parents = _git("rev-list", "--parents", "-n", "1", "HEAD").decode().split()
    if parents != [merge, base, head]:
        return False
    if _git("merge-base", base, merge).decode().strip() != base:
        return False
    raw = _git(
        "diff",
        "--raw",
        "-z",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        base,
        merge,
        "--",
    )
    if not raw or not raw.endswith(b"\0"):
        return False
    records = raw[:-1].split(b"\0")
    if len(records) % 2:
        return False
    for metadata, encoded_path in zip(records[::2], records[1::2], strict=True):
        fields = metadata.split()
        if len(fields) != 5:
            return False
        before, after, _old_id, _new_id, status = fields
        if (before, after, status) not in (
            (b":000000", b"100644", b"A"),
            (b":100644", b"100644", b"M"),
            (b":100644", b"000000", b"D"),
        ):
            return False
        path = encoded_path.decode("utf-8", "strict")
        if (
            not path.endswith(".md")
            or not path.startswith(("docs/ADR/", "docs/handoffs/"))
            or path in CONTRACT_DOCS
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            return False
    return True


def main() -> int:
    try:
        matched = docs_only()
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        matched = False
    print("true" if matched else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
