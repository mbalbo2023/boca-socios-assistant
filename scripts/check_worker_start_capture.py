"""Prove pre-start stream capture on the disposable GitHub Actions Docker daemon."""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep

from .worker_start_capture import CaptureFailure, CaptureResult, attach_output

SOCKET = Path("/var/run/docker.sock")
CID = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
LABEL = "boca.socios.ci-capture"
# Only the public IPC contract, domain policy and simulator types are imported.
IMAGE_CONTRACT = """\
import os, sys
from pathlib import Path
for reserved in ("synthetic", "ipc_worker"):
    sys.modules["boca_socios.browser." + reserved] = None
from boca_socios.browser import contracts, ipc_protocol
from boca_socios.domain import policy
from importlib.metadata import version
checks = (
    os.geteuid() == os.getegid() == 10002,
    Path.cwd() == Path("/app"),
    sys.prefix == "/app/.venv" and sys.prefix != sys.base_prefix,
    Path(sys.executable).parent == Path("/app/.venv/bin"),
    all(Path(m.__file__).resolve().is_relative_to("/app/src/boca_socios")
        for m in (contracts, ipc_protocol, policy)),
    all(version(d) for d in ("playwright", "greenlet", "pyee", "typing-extensions")),
)
if not all(checks):
    raise SystemExit(23)
"""
# The synthetic process generates its private value after start. Only the
# attach reader sees process streams; Docker CLI calls below read metadata.
CASES = (
    ("image-contract", IMAGE_CONTRACT, "EMPTY", 0),
    ("missing", "import boca_r131_missing_fixture", "MODULE_NOT_FOUND_ERROR", 1),
    (
        "denied",
        "import secrets; raise PermissionError(secrets.token_hex(16))",
        "PERMISSION_ERROR",
        1,
    ),
    ("silent", "raise SystemExit(1)", "EMPTY", 1),
    ("stdout", "print('PermissionError: fixture'); raise SystemExit(1)", "STDOUT_ONLY", 1),
    ("overflow", "import os; os.write(2, b'x' * 65536); raise SystemExit(1)", "LIMIT", 1),
)


class LabError(Exception):
    """A finite stage, never Docker output or fixture text."""


def docker(*args: str) -> str:
    executable = shutil.which("docker", path="/usr/bin:/usr/local/bin")
    if executable is None:
        raise LabError("DOCKER_UNAVAILABLE")
    try:
        with subprocess.Popen(  # noqa: S603 - fixed local CLI and reviewed arguments
            [executable, "--host", f"unix://{SOCKET}", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/usr/local/bin:/bin", "LANG": "C"},
        ) as proc:
            assert proc.stdout is not None
            deadline = monotonic() + 15
            data = bytearray()
            try:
                while len(data) <= 2048:
                    remaining = deadline - monotonic()
                    if remaining <= 0 or not select.select([proc.stdout], [], [], remaining)[0]:
                        raise LabError("DOCKER_TIMEOUT")
                    chunk = os.read(proc.stdout.fileno(), 2049 - len(data))
                    if not chunk:
                        if proc.wait(max(0, deadline - monotonic())):
                            raise LabError("DOCKER_METADATA")
                        return data.decode("ascii").removesuffix("\n")
                    data.extend(chunk)
                raise LabError("DOCKER_METADATA_LIMIT")
            finally:
                if proc.poll() is None:
                    proc.kill()
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise LabError("DOCKER_UNAVAILABLE") from None


def field(cid: str, template: str) -> object:
    return json.loads(docker("inspect", "--format", "{{json " + template + "}}", cid))


def remove_fixture(cid: str, key: str, image: str) -> None:
    if field(cid, ".Id") != cid or field(cid, ".Image") != image:
        raise LabError("CLEANUP_IDENTITY")
    if field(cid, f'(index .Config.Labels "{LABEL}")') != key:
        raise LabError("CLEANUP_SCOPE")
    if field(cid, ".State.Running") is True and docker("stop", "-t", "1", cid) != cid:
        raise LabError("CLEANUP_STOP")
    if docker("rm", cid) != cid or docker("ps", "-aq", "--no-trunc", "--filter", f"id={cid}"):
        raise LabError("CLEANUP_VERIFY")


def start_fixture(cid: str) -> None:
    if docker("start", cid) != cid:
        raise LabError("START_ACK")


def wait_healthy(cid: str) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if field(cid, ".State.Health.Status") == "healthy":
            return
        sleep(0.15)
    raise LabError("FIXTURE_HEALTH")


def create_fixture(image: str, key: str, program: str, resident: bool) -> str:
    health = (
        ("--health-cmd", "true", "--health-interval", "1s", "--health-timeout", "1s")
        if resident
        else ("--no-healthcheck",)
    )
    return docker(
        "create",
        "--pull",
        "never",
        "--label",
        f"{LABEL}={key}",
        "--network",
        "none",
        "--log-driver",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10002:10002",
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "16",
        *health,
        "--entrypoint",
        "python",
        image,
        "-O",
        "-B",
        "-c",
        program,
    )


def verify_fixture(cid: str, image: str, key: str, program: str, resident: bool) -> None:
    # Validate the image/attempt, effective command and isolated output
    # before registering the stream or allowing any process to start.
    checks = {
        ".Id": cid,
        ".Image": image,
        f'(index .Config.Labels "{LABEL}")': key,
        ".State.Status": "created",
        ".HostConfig.NetworkMode": "none",
        ".HostConfig.LogConfig.Type": "none",
        ".Config.Tty": False,
        ".Config.OpenStdin": False,
        ".Config.AttachStdin": False,
        ".Config.Entrypoint": ["python"],
        ".Config.Cmd": ["-O", "-B", "-c", program],
        ".Config.Healthcheck.Test": ["CMD-SHELL", "true"] if resident else ["NONE"],
        "(len .Mounts)": 0,
        ".HostConfig.Privileged": False,
        ".HostConfig.ReadonlyRootfs": True,
    }
    for path, wanted in checks.items():
        observed = field(cid, path)
        if type(observed) is not type(wanted) or observed != wanted:
            # Only this source-defined selector crosses the output boundary.
            raise LabError(f"PRESTART_CONTRACT field={path}")


def exercise(image: str, run: str, name: str, program: str, expected: str, exit_code: int) -> None:
    key = f"{run}-{name}"
    resident = name == "resident"
    print(f"BOCA_CAPTURE_LAB case={name} phase=PREPARE", flush=True)
    try:
        cid = create_fixture(image, key, program, resident)
        if not CID.fullmatch(cid):
            raise LabError("CREATE_IDENTITY")
    except (LabError, OSError, ValueError):
        # A lost create ACK may still have created a fixture. Look up only this
        # unique job/case label and require its image and full CID before removal.
        try:
            found = docker("ps", "-aq", "--no-trunc", "--filter", f"label={LABEL}={key}")
            if found:
                if not CID.fullmatch(found):
                    raise LabError("CREATE_AMBIGUOUS")
                remove_fixture(found, key, image)
                print(
                    f"BOCA_CAPTURE_LAB case={name} cleanup=VERIFIED removed=EXACT_CID", flush=True
                )
            else:
                print(f"BOCA_CAPTURE_LAB case={name} cleanup=ABSENT_AT_INVENTORY", flush=True)
        except (LabError, OSError, ValueError):
            print("BOCA_CAPTURE_LAB cleanup=INDETERMINATE", flush=True)
        raise
    try:
        verify_fixture(cid, image, key, program, resident)
        if resident:
            with attach_output(SOCKET, cid):
                start_fixture(cid)
                wait_healthy(cid)
            if (
                field(cid, ".State.Running") is not True
                or field(cid, ".State.Health.Status") != "healthy"
            ):
                raise LabError("DETACH_CHANGED_PROCESS")
        else:
            with attach_output(SOCKET, cid) as capture, ThreadPoolExecutor(max_workers=1) as reader:
                pending = reader.submit(capture.finish)
                start_fixture(cid)
                signal = pending.result()
            waited = docker("wait", cid)
            if (
                signal != CaptureResult(expected)
                or waited != str(exit_code)
                or field(cid, ".State.ExitCode") != exit_code
                or field(cid, ".State.OOMKilled") is not False
            ):
                raise LabError(f"OBSERVATION signal={signal.value}")
        observed_status = "HEALTHY" if resident else f"EXIT_{exit_code}"
        print(
            f"BOCA_CAPTURE_LAB case={name} observed={expected} state={observed_status}", flush=True
        )
    finally:
        primary = sys.exc_info()[0] is not None
        try:
            remove_fixture(cid, key, image)
        except (LabError, ValueError, OSError):
            if not primary:
                raise LabError("CLEANUP_INDETERMINATE") from None
            print(f"BOCA_CAPTURE_LAB case={name} cleanup=INDETERMINATE", flush=True)
        else:
            print(f"BOCA_CAPTURE_LAB case={name} cleanup=VERIFIED removed=EXACT_CID", flush=True)


def main() -> None:
    if not (
        os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REPOSITORY") == "mbalbo2023/boca-socios-assistant"
        and re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", ""))
        and re.fullmatch(r"[1-9][0-9]{0,19}", os.environ.get("GITHUB_RUN_ID", ""))
    ):
        raise LabError("RUNNER_SCOPE")
    image = docker(
        "image", "inspect", "--format", "{{.Id}}", "boca-browser-ci:" + os.environ["GITHUB_SHA"]
    )
    if not IMAGE_ID.fullmatch(image):
        raise LabError("IMAGE_ID")

    # A versioned attach is deliberate. Refuse unsupported APIs before create.
    def api_version(selector: str) -> tuple[int, int]:
        value = docker("version", "--format", "{{.Server." + selector + "}}")
        if not re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}", value):
            raise LabError("ENGINE_API")
        major, minor = value.split(".")
        return int(major), int(minor)

    if not api_version("MinAPIVersion") <= (1, 48) <= api_version("APIVersion"):
        raise LabError("ENGINE_API_RANGE")
    for case in CASES:
        exercise(image, os.environ["GITHUB_RUN_ID"], *case)
    exercise(
        image,
        os.environ["GITHUB_RUN_ID"],
        "resident",
        "import time; time.sleep(60)",
        "DETACHED_HEALTHY",
        0,
    )
    print(f"BOCA_CAPTURE_LAB state=PASS fixture_image={image} droplet_effects=0", flush=True)


if __name__ == "__main__":
    try:
        main()
    except CaptureFailure as exc:
        sys.exit("BOCA_CAPTURE_LAB state=FAIL attach=" + exc.result.value)
    except LabError as exc:
        sys.exit("BOCA_CAPTURE_LAB state=FAIL stage=" + str(exc))
    except (OSError, ValueError):
        sys.exit("BOCA_CAPTURE_LAB state=FAIL stage=INVALID_METADATA")
