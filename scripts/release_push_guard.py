"""Bounded same-run paired image publication; never log registry output."""

from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

from check_release_dispatch import _unique_fields, validate_dispatch_history

from boca_socios.deploy_inputs import validate_main_ref

LIMIT = 1_048_576
SOURCE = "https://github.com/mbalbo2023/boca-socios-assistant"
TEMP = Path(os.environ["RUNNER_TEMP"])
SHA = os.environ["GITHUB_SHA"]
ROLES = ("browser", "controller")
IMAGES = {role: os.environ[role.upper() + "_IMAGE"] for role in ROLES}
SNAPSHOT = TEMP / "boca-push-identities.json"
PROGRESS = re.compile(
    rb"[a-f0-9]{12}: (?:Preparing|Waiting|Pushing(?: +[0-9.]+[kMGT]?B/[0-9.]+[kMGT]?B)?|Pushed|Layer already exists|Mounted from [a-zA-Z0-9_./-]+)"
)


class GuardError(Exception):
    def __init__(self, stage: str, category: str) -> None:
        self.stage, self.category = stage, category


def report_push(role: str, attempt: int, status: int, elapsed: int, category: str) -> None:
    print(
        f"publisher role={role} attempt={attempt} rc={status} duration_ms={elapsed} category={category}",
        file=sys.stderr,
    )


def command(*args: str) -> bytes:
    result = subprocess.run(  # noqa: S603
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=True,
    )
    if len(result.stdout) > LIMIT:
        raise ValueError("command response too large")
    return result.stdout


def identity(role: str) -> str:
    data = json.loads(command("docker", "image", "inspect", "--format", "{{json .}}", IMAGES[role]))
    image_id = data["Id"]
    labels = data["Config"]["Labels"]
    if (
        not isinstance(image_id, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
        or labels.get("org.opencontainers.image.source") != SOURCE
        or labels.get("org.opencontainers.image.revision") != SHA
    ):
        raise ValueError("image identity or labels invalid")
    return image_id


def recheck_dispatch() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    raw_main = command("gh", "api", f"repos/{repo}/git/ref/heads/main")
    if len(raw_main) > 8192:
        raise ValueError("main response too large")
    main = json.loads(raw_main)
    validate_main_ref(main, SHA)
    raw_runs = command(
        "gh",
        "api",
        f"repos/{repo}/actions/workflows/release-image.yml/runs?event=workflow_dispatch&head_sha={SHA}&per_page=2",
    )
    if len(raw_runs) > 131_072:
        raise ValueError("dispatch response too large")
    runs = json.loads(raw_runs, object_pairs_hook=_unique_fields)
    validate_dispatch_history(runs, SHA, os.environ["GITHUB_RUN_ID"])


def limit_file_size() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))


def push(role: str, attempt: int) -> tuple[int, bytes, bytes, int]:
    prefix = TEMP / f"boca-{role}-push-{attempt}"
    status = None
    started = time.monotonic()
    try:
        with (
            prefix.with_suffix(".out").open("xb") as stdout,
            prefix.with_suffix(".err").open("xb") as stderr,
        ):
            try:
                result = subprocess.run(  # noqa: S603
                    ["docker", "push", IMAGES[role]],  # noqa: S607
                    stdout=stdout,
                    stderr=stderr,
                    timeout=300,
                    preexec_fn=limit_file_size,
                    check=False,
                )
                status = result.returncode
            except subprocess.TimeoutExpired:
                status = 124
        out = prefix.with_suffix(".out").read_bytes()
        err = prefix.with_suffix(".err").read_bytes()
        if len(out) >= LIMIT or len(err) >= LIMIT:
            raise OSError("oversized")
    except OSError as exc:
        if status is not None:
            report_push(role, attempt, status, int((time.monotonic() - started) * 1000), "LOG_IO")
        raise GuardError("PUSH", "LOG_IO") from exc
    return status, out, err, int((time.monotonic() - started) * 1000)


def eligible(role: str, status: int, out: bytes, err: bytes) -> bool:
    # Docker progress may precede its one diagnostic; anything else is ambiguous.
    lines = out.splitlines()
    header = f"The push refers to repository [{IMAGES[role].rsplit(':', 1)[0]}]".encode()
    if lines and lines[0] == header:
        lines = lines[1:]
    return (
        status == 1
        and err == b"unknown blob\n"
        and b"\r" not in out
        and all(PROGRESS.fullmatch(line) for line in lines)
    )


def valid_success(role: str, out: bytes, err: bytes) -> bool:
    if err or not out.endswith(b"\n") or b"\r" in out:
        return False
    lines = out.splitlines()
    if len(lines) < 2:
        return False
    expected_header = f"The push refers to repository [{IMAGES[role].rsplit(':', 1)[0]}]".encode()
    digest = rb"sha-" + SHA.encode() + rb": digest: sha256:[0-9a-f]{64} size: [0-9]+"
    return (
        lines[0] == expected_header
        and bool(re.fullmatch(digest, lines[-1]))
        and all(PROGRESS.fullmatch(line) for line in lines[1:-1])
    )


def main() -> int:
    if sys.argv[1:] == ["snapshot"]:
        try:
            ids = {role: identity(role) for role in ROLES}
            with SNAPSHOT.open("x", encoding="utf-8") as file:
                json.dump(ids, file)
        except Exception as exc:
            raise GuardError("SNAPSHOT", "PROVENANCE") from exc
        return 0
    if sys.argv[1:] != ["publish"]:
        raise GuardError("INPUT", "OTHER")
    if os.environ["GITHUB_RUN_ATTEMPT"] != "1":
        raise GuardError("PREPUSH", "PROVENANCE")
    try:
        ids = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GuardError("PREPUSH", "PROVENANCE") from exc
    refs = {}
    recovered = False
    for role in ROLES:
        for attempt in (1, 2):
            try:
                recheck_dispatch()
                if any(identity(item) != ids[item] for item in ROLES):
                    raise ValueError("local image changed")
            except Exception as exc:
                raise GuardError("PREPUSH", "PROVENANCE") from exc
            status, out, err, elapsed = push(role, attempt)
            if status == 0:
                try:
                    if not valid_success(role, out, err):
                        raise ValueError("invalid success output")
                    log = TEMP / f"boca-{role}-push-{attempt}.out"
                    refs[role] = (
                        command(
                            sys.executable,
                            "scripts/parse_image_digest.py",
                            str(log),
                            SHA,
                            "--role",
                            role,
                        )
                        .decode("utf-8")
                        .strip()
                    )
                except Exception as exc:
                    report_push(role, attempt, status, elapsed, "DIGEST")
                    raise GuardError("PARSER", "DIGEST") from exc
                report_push(role, attempt, status, elapsed, "SUCCESS")
                break
            is_eligible = eligible(role, status, out, err)
            if is_eligible:
                category = "UNKNOWN_BLOB"
            elif status == 124:
                category = "TIMEOUT"
            elif b"unknown blob" not in err and (
                b"unauthorized" in err.lower() or b"denied" in err.lower()
            ):
                category = "AUTH"
            else:
                category = "OTHER"
            report_push(role, attempt, status, elapsed, category)
            if recovered or not is_eligible:
                raise GuardError("PUSH", category)
            recovered = True
            subprocess.run(["sleep", "5"], check=True, timeout=10)  # noqa: S607
        else:
            raise GuardError("PUSH", "OTHER")
    for role in ROLES:
        print(f"{role}={refs[role]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GuardError as exc:
        print(f"RELEASE_FAIL stage={exc.stage} category={exc.category}", file=sys.stderr)
        sys.exit(1)
    except (Exception, KeyboardInterrupt):
        print("RELEASE_FAIL stage=INTERNAL category=OTHER", file=sys.stderr)
        sys.exit(1)
