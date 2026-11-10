"""Prove pre-start stream capture on the disposable GitHub Actions Docker daemon."""

from __future__ import annotations

import json
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

from boca_socios.host_first_deploy import _CUTOVER_CAPTURE_INSPECT, _WORKER_HEALTH_CMD
from boca_socios.worker_start_capture import CaptureFailure, CaptureResult, attach_output

SOCKET = Path("/var/run/docker.sock")
CID = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
LABEL = "boca.socios.ci-capture"
PROJECTION_LABELS = (
    ("attempt", "boca.socios.browser-ipc-attempt", "fixture-attempt"),
    ("revision", "org.opencontainers.image.revision", "fixture-revision"),
    ("service", "com.docker.compose.service", "fixture-service"),
    ("project", "com.docker.compose.project", "fixture-project"),
    ("config_hash", "com.docker.compose.config-hash", "fixture-hash"),
)
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
    (
        "ipc-directory",
        "from pathlib import Path; "
        "from boca_socios.browser.ipc_protocol import validate_socket_directory; "
        "validate_socket_directory(Path('/'))",
        "IPC_DIRECTORY_UNVERIFIED",
        1,
    ),
    (
        "missing-distribution",
        "import sys; sys.path.clear(); import playwright",
        "MISSING_PLAYWRIGHT",
        1,
    ),
)

# Only the mtime of an empty fixture-private tmpfs file records progress. Both writes
# must complete before every heartbeat. The bytes are generated inside the container.
RESIDENT = """\
import os, secrets, time
from pathlib import Path
marker = Path('/dev/shm/boca-capture-progress')
marker.touch()
chunk = secrets.token_hex(48).encode() + b'\\n'
for _ in range(1800):
    os.write(1, chunk)
    os.write(2, chunk)
    os.utime(marker)
    time.sleep(0.035)
"""
RESIDENT_HEALTH = "python -IBc " + shlex.quote("""\
import os, time
try:
    path = '/dev/shm/boca-capture-progress'
    before = os.stat(path).st_mtime_ns
    time.sleep(0.20)
    progressing = os.stat(path).st_mtime_ns > before
except OSError:
    progressing = False
raise SystemExit(0 if progressing else 1)
""")

# The same immutable process produces a different, closed observation on each run.
# The first receives a deliberate fixture STOP only after the handler is ready.
RESTART_FIXTURE = """\
import signal
import time
from pathlib import Path
def stop_fixture(_signal, _frame):
    raise PermissionError("fixture")
signal.signal(signal.SIGTERM, stop_fixture)
Path("/dev/shm/boca-restart-ready").touch()
time.sleep(5)
raise RuntimeError("fixture")
"""
RESTART_HEALTH = "test -f /dev/shm/boca-restart-ready"


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


def last_successful_probe(cid: str) -> datetime:
    # Project two scalar metadata fields. Never read or print healthcheck output.
    result = docker(
        "inspect",
        "--format",
        "{{range .State.Health.Log}}{{json .Start}} {{json .ExitCode}}{{println}}{{end}}",
        cid,
    )
    tokens = result.split()
    if not tokens or len(tokens) % 2:
        raise LabError("PROGRESS_PROBE_METADATA")
    last = None
    for stamp, code in zip(tokens[::2], tokens[1::2], strict=True):
        if not re.fullmatch(r'"[0-9.T:Z+\-]{20,40}"', stamp) or not re.fullmatch(
            r"-?[0-9]{1,3}", code
        ):
            raise LabError("PROGRESS_PROBE_METADATA")
        if code == "0":
            last = datetime.fromisoformat(stamp[1:-1])
    if last is None or last.tzinfo is None:
        raise LabError("PROGRESS_PROBE_METADATA")
    return last


def verify_detached_progress(cid: str) -> None:
    # The first new result may have been in flight at detach. The next successful
    # probe witnesses two completed writes while the collector is already gone.
    previous = last_successful_probe(cid)
    fresh = 0
    deadline = monotonic() + 10
    while monotonic() < deadline:
        stamp = last_successful_probe(cid)
        if stamp < previous:
            break
        if stamp > previous:
            previous = stamp
            fresh += 1
        if fresh == 2:
            if (
                field(cid, ".State.Running") is True
                and field(cid, ".State.Health.Status") == "healthy"
            ):
                return
            break
        sleep(0.15)
    raise LabError("DETACH_CHANGED_PROCESS")


def create_fixture(
    image: str, key: str, program: str, health_command: str | None, entrypoint: str
) -> str:
    health = (
        ("--health-cmd", health_command, "--health-interval", "1s", "--health-timeout", "2s")
        if health_command is not None
        else ("--no-healthcheck",)
    )
    return docker(
        "create",
        "--pull",
        "never",
        "--label",
        f"{LABEL}={key}",
        *(arg for _, label, value in PROJECTION_LABELS for arg in ("--label", f"{label}={value}")),
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
        entrypoint,
        image,
        "-O",
        "-B",
        "-c",
        program,
    )


def verify_capture_projection(cid: str, image: str, *, health_matches: bool = False) -> None:
    # Exercise the exact protected Go template on distinctly labeled, stopped fixtures.
    observed = json.loads(docker("inspect", "--format", _CUTOVER_CAPTURE_INSPECT, cid))
    expected = {
        "cid": cid,
        "image_id": image,
        "image_ref": image,
        **{key: value for key, _, value in PROJECTION_LABELS},
        "status": "created",
        "tty": False,
        "open_stdin": False,
        "attach_stdin": False,
        "log_driver": "none",
        "log_options": 0,
        "health": health_matches,
    }
    if (
        not isinstance(observed, dict)
        or observed.keys() != expected.keys()
        or any(
            type(observed[key]) is not type(value) or observed[key] != value
            for key, value in expected.items()
        )
    ):
        raise LabError("CAPTURE_PROJECTION")


def verify_fixture(
    cid: str, image: str, key: str, program: str, health_command: str | None, entrypoint: str
) -> None:
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
        ".Config.Entrypoint": [entrypoint],
        ".Config.Cmd": ["-O", "-B", "-c", program],
        ".Config.Healthcheck.Test": ["CMD-SHELL", health_command] if health_command else ["NONE"],
        "(len .Mounts)": 0,
        ".HostConfig.Privileged": False,
        ".HostConfig.ReadonlyRootfs": True,
    }
    for path, wanted in checks.items():
        observed = field(cid, path)
        if type(observed) is not type(wanted) or observed != wanted:
            # Only this source-defined selector crosses the output boundary.
            raise LabError(f"PRESTART_CONTRACT field={path}")
    verify_capture_projection(cid, image, health_matches=health_command == _WORKER_HEALTH_CMD)


@contextmanager
def verified_fixture(
    image: str,
    run: str,
    name: str,
    program: str,
    health_command: str | None,
    entrypoint: str = "python",
) -> Iterator[str]:
    key = f"{run}-{name}"
    print(f"BOCA_CAPTURE_LAB case={name} phase=PREPARE", flush=True)
    try:
        cid = create_fixture(image, key, program, health_command, entrypoint)
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
    completed = False
    try:
        verify_fixture(cid, image, key, program, health_command, entrypoint)
        yield cid
        completed = True
    finally:
        try:
            remove_fixture(cid, key, image)
        except (LabError, ValueError, OSError):
            if completed:
                raise LabError("CLEANUP_INDETERMINATE") from None
            print(f"BOCA_CAPTURE_LAB case={name} cleanup=INDETERMINATE", flush=True)
        else:
            print(f"BOCA_CAPTURE_LAB case={name} cleanup=VERIFIED removed=EXACT_CID", flush=True)


def exercise(image: str, run: str, name: str, program: str, expected: str, exit_code: int) -> None:
    resident = name == "resident"
    health_command = {"resident": RESIDENT_HEALTH, "restart-exited": RESTART_HEALTH}.get(name)
    with verified_fixture(image, run, name, program, health_command) as cid:
        if resident:
            with attach_output(SOCKET, cid) as capture:
                start_fixture(cid)
                wait_healthy(cid)
                if not capture.close():
                    raise LabError("DETACH_INACTIVE")
            verify_detached_progress(cid)
            print(
                "BOCA_CAPTURE_LAB case=resident after_detach=PROGRESS_VERIFIED fresh_probes=2",
                flush=True,
            )
        elif name == "restart-exited":
            exercise_restart(cid)
        else:
            with attach_output(SOCKET, cid) as capture:
                start_fixture(cid)
                signal = capture.finish()
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


def exercise_restart(cid: str) -> None:
    previous_finished = None
    for attempt, (before, expected) in enumerate(
        (("created", CaptureResult.PERMISSION_ERROR), ("exited", CaptureResult.RUNTIME_ERROR)),
        start=1,
    ):
        if field(cid, ".Id") != cid or field(cid, ".State.Status") != before:
            raise LabError("RESTART_PRESTATE")
        with attach_output(SOCKET, cid) as capture:
            start_fixture(cid)
            if attempt == 1:
                wait_healthy(cid)
                if docker("stop", "-t", "2", cid) != cid:
                    raise LabError("RESTART_STOP_ACK")
            observed = capture.finish()
        if (
            observed != expected
            or docker("wait", cid) != "1"
            or field(cid, ".State.Status") != "exited"
            or field(cid, ".State.OOMKilled") is not False
        ):
            raise LabError("RESTART_OBSERVATION")
        started_at = field(cid, ".State.StartedAt")
        finished_at = field(cid, ".State.FinishedAt")
        if not isinstance(started_at, str) or not isinstance(finished_at, str):
            raise LabError("RESTART_TIMESTAMPS")
        started, finished = datetime.fromisoformat(started_at), datetime.fromisoformat(finished_at)
        if (
            started.tzinfo is None
            or finished.tzinfo is None
            or finished <= started
            or previous_finished is not None
            and started <= previous_finished
        ):
            raise LabError("RESTART_TIMESTAMPS")
        previous_finished = finished
        print(
            f"BOCA_CAPTURE_LAB case=restart-exited attempt={attempt} "
            f"before={before} observed={expected.value} state=EXIT_1",
            flush=True,
        )


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
    # Inspect the actual production health command as metadata only. This fixture
    # has a deliberately nonexistent entrypoint and never reaches attach/start.
    with verified_fixture(
        image,
        os.environ["GITHUB_RUN_ID"],
        "health-template",
        "raise SystemExit(97)",
        _WORKER_HEALTH_CMD,
        entrypoint="/boca-ci-no-such-health-fixture",
    ):
        print(
            "BOCA_CAPTURE_LAB case=health-template observed=HEALTH_TEMPLATE_MATCH state=CREATED",
            flush=True,
        )
    for case in CASES:
        exercise(image, os.environ["GITHUB_RUN_ID"], *case)
    exercise(
        image, os.environ["GITHUB_RUN_ID"], "restart-exited", RESTART_FIXTURE, "RESTART_VERIFIED", 1
    )
    exercise(
        image,
        os.environ["GITHUB_RUN_ID"],
        "resident",
        RESIDENT,
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
