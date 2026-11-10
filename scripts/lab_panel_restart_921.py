"""Measure panel STOP acknowledgements and the production cold-cycle adapter on runner Docker."""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import Mock, patch
from uuid import uuid4

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover_backend as backend
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_cutover import CandidateAcceptanceFailure, CutoverPlan
from scripts import check_worker_start_capture as fixture

ORIGIN = "http://localhost:8443"
PORTS = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
INSPECT = (
    "[{{json .Id}},{{json .State.Status}},{{json .State.Running}},{{json .State.Pid}},"
    "{{json .State.StartedAt}},{{json .State.Restarting}},{{json .State.Dead}},{{json .NetworkSettings.Ports}}]"
)
SERVER = """from http.server import BaseHTTPRequestHandler, HTTPServer
import signal, sys
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'BOCA_BETA_READY' if self.path == '/healthz' else b''
        self.send_response(200 if body else 404)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
HTTPServer(('', 8443), Handler).serve_forever()
"""
HEALTH = (
    "python -IBc "
    + shlex.quote(
        "import http.client; c=http.client.HTTPConnection('127.0.0.1',8443,timeout=1); "
        "c.request('GET','/healthz'); r=c.getresponse(); raise SystemExit(0 if r.status==200 and r.read(64)==b'BOCA_BETA_READY' else 1)"
    )
    + " >/dev/null 2>&1"
)
_WARNING = b"Flag --time has been deprecated, use --timeout instead"


def channel(data: bytes, cid: str) -> str:
    if len(data) > 2048:
        return "OVERSIZE"
    full = cid.encode("ascii")
    if data == b"":
        return "EMPTY"
    lines = data.removesuffix(b"\n").split(b"\n")
    if lines == [full]:
        return "FULL_CID"
    if lines == [_WARNING]:
        return "DEPRECATION"
    if lines == [_WARNING, full]:
        return "DEPRECATION_AND_CID"
    return "MULTILINE_OTHER" if len(lines) > 1 else "OTHER"


def state(cid: str, *, running: bool) -> tuple[int, int]:
    raw = json.loads(fixture.docker("inspect", "--type", "container", "--format", INSPECT, cid))
    if (
        type(raw) is not list
        or len(raw) != 8
        or raw[0] != cid
        or raw[2] is not running
        or type(raw[3]) is not int
        or raw[5] is not False
        or raw[6] is not False
    ):
        raise fixture.LabError("STATE")
    stamp = host._worker_rfc3339nano_ns(raw[4])
    if stamp is None or stamp <= 0:
        raise fixture.LabError("START_ID")
    if running:
        if raw[1] != "running" or raw[3] <= 0 or raw[7] != PORTS:
            raise fixture.LabError("RUNNING")
        host._beta_loopback_health(cid, ORIGIN)
    else:
        if raw[1] != "exited" or raw[3] != 0 or raw[7] not in (None, {}, {"8443/tcp": None}):
            raise fixture.LabError("STOPPED")
        deadline = monotonic() + 3
        while True:
            with socket.socket() as sock:
                sock.settimeout(0.5)
                if sock.connect_ex(("127.0.0.1", 8443)) == errno.ECONNREFUSED:
                    break
            if monotonic() >= deadline:
                raise fixture.LabError("PORT")
            sleep(0.05)
    return stamp, raw[3]


def compare_flag(cid: str, flag: str) -> None:
    before = state(cid, running=True)
    raw = subprocess.run(  # noqa: S603 - fixed local Docker and allowlisted option
        ["/usr/bin/docker", "--host", f"unix://{fixture.SOCKET}", "stop", flag, "8", cid],
        capture_output=True,
        check=False,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
    )
    out, err = channel(raw.stdout, cid), channel(raw.stderr, cid)
    unsupported = b"unknown flag: " + flag.encode() in raw.stderr.splitlines()
    result = "OK" if raw.returncode == 0 else "UNSUPPORTED" if unsupported else "ERROR"
    print(
        f"BOCA_PANEL_STOP_LAB flag={flag.removeprefix('--').upper()} "
        f"result={result} stdout={out} stderr={err}",
        flush=True,
    )
    if raw.returncode != 0:
        # An old/new CLI may lack a particular long form. An unchanged live process is required.
        if not unsupported or state(cid, running=True) != before:
            raise fixture.LabError("FLAG_FAILED")
        return
    # These long forms are measured independently. The productive adapter below must
    # accept only its exact CID and must prove both transitions over the real engine.
    if "OVERSIZE" in (out, err) or state(cid, running=False)[0] != before[0]:
        raise fixture.LabError("FLAG_OBSERVATION")
    fixture.start_fixture(cid)
    fixture.wait_healthy(cid)
    if state(cid, running=True)[0] <= before[0]:
        raise fixture.LabError("FLAG_START_ID")


def adapter_cycle(cid: str, *, absent: bool = False) -> None:
    subject = sha256((cid + "-missing").encode()).hexdigest() if absent else cid
    if absent and fixture.docker("ps", "-aq", "--no-trunc", "--filter", "id=" + subject):
        raise fixture.LabError("NEGATIVE_ID")
    before = state(cid, running=True)
    instance = backend.RootlessCutoverBackend(
        backend.ReviewedCutoverSources(b"", b"", b"", b""), on_demand=True
    )
    worker = "e" * 64
    instance.candidate_id, instance.worker_id = subject, worker
    instance.control_directory = Path("/fixture/unused")
    plan = Mock(
        spec=CutoverPlan,
        attempt_id="1",
        legacy_id="a" * 64,
        legacy_image="fixture",
        legacy_sha="a" * 40,
    )
    lease = Mock(spec=cleanup.BocaJobLease)
    guards = 0

    def guard(*args: object) -> None:
        nonlocal guards
        guards += 1
        if guards == 2 and (absent or state(cid, running=False)[0] != before[0]):
            raise fixture.LabError("ADAPTER_STOP")

    def restart_check(*args: object, **kwargs: object) -> None:
        if kwargs != {"visit": "RESTART"} or state(cid, running=True)[0] <= before[0]:
            raise fixture.LabError("ADAPTER_RESTART")

    with (
        patch.object(host, "ROOTLESS_SOCKET", fixture.SOCKET),
        patch.object(instance, "installation", object()),
        patch.object(instance, "_guard", side_effect=guard),
        patch.object(backend, "_verify_mounted_control", return_value=(1, 1)),
        patch.object(host, "_cutover_legacy_record"),
        patch.object(service, "verify_control"),
        patch.object(instance, "_verify_cold_pair", side_effect=restart_check) as post,
        patch.object(host, "_run", wraps=host._run) as commands,
    ):
        try:
            instance._cycle_idle_panel(plan, subject, worker, lease)
        except CandidateAcceptanceFailure as exc:
            if not absent or (exc.check, exc.result) != ("PANEL_STOP_ACK", "COMMAND_FAILED"):
                raise fixture.LabError("ADAPTER_CHECK") from None
        else:
            if absent:
                raise fixture.LabError("NEGATIVE_ACCEPTED")
        actions = [
            call.args
            for call in commands.call_args_list
            if call.args[:2] in (("docker", "stop"), ("docker", "start"))
        ]
        expected: list[tuple[str, ...]] = [("docker", "stop", "-t", "8", subject)]
        if not absent:
            expected.append(("docker", "start", subject))
        if (
            actions != expected
            or guards != (1 if absent else 2)
            or post.call_count != (0 if absent else 1)
        ):
            raise fixture.LabError("ADAPTER_PATH")
    if absent and state(cid, running=True) != before:
        raise fixture.LabError("NEGATIVE_EFFECT")


def main() -> int:
    sha = os.environ.get("GITHUB_SHA", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("BOCA_LAB_RUNNER") != "github-hosted"
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or not re.fullmatch(r"[1-9][0-9]{0,19}", run)
    ):
        return 3
    key = f"panel-restart-921-{run}-{uuid4().hex}"
    try:
        image = fixture.docker("image", "inspect", "--format", "{{.Id}}", "boca-socios-ci:" + sha)
        if not fixture.IMAGE_ID.fullmatch(image):
            raise fixture.LabError("IMAGE")
        host._browser_port_free()
        try:
            cid = fixture.docker(
                "create",
                "--pull",
                "never",
                "--label",
                f"{fixture.LABEL}={key}",
                "--publish",
                "127.0.0.1:8443:8443/tcp",
                "--log-driver",
                "none",
                "--init",
                "--restart",
                "no",
                "--read-only",
                "--user",
                "10001:10001",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "128m",
                "--pids-limit",
                "32",
                "--health-cmd",
                HEALTH,
                "--health-interval",
                "1s",
                "--health-timeout",
                "2s",
                "--entrypoint",
                "/usr/local/bin/python",
                image,
                "-I",
                "-B",
                "-c",
                SERVER,
            )
            if not fixture.CID.fullmatch(cid):
                raise fixture.LabError("CID")
            fixture.start_fixture(cid)
            fixture.wait_healthy(cid)
            compare_flag(cid, "--time")
            compare_flag(cid, "--timeout")
            adapter_cycle(cid)
            adapter_cycle(cid, absent=True)
        finally:
            saved = fixture.docker(
                "ps", "-aq", "--no-trunc", "--filter", f"label={fixture.LABEL}={key}"
            )
            if saved:
                if not fixture.CID.fullmatch(saved):
                    raise fixture.LabError("CLEANUP_ID")
                fixture.remove_fixture(saved, key, image)
    except (
        OSError,
        ValueError,
        TypeError,
        subprocess.SubprocessError,
        fixture.LabError,
        host.PreflightError,
    ) as exc:
        stage = str(exc) if isinstance(exc, fixture.LabError) else "UNVERIFIED"
        print("BOCA_PANEL_STOP_LAB state=FAIL step=" + stage, file=sys.stderr)
        return 3
    print(
        "BOCA_PANEL_STOP_LAB state=PASS adapter=FULL_CID stopped=EXITED_PID0 restart=NEW_START_ID "
        "loopback=HEALTHY missing=COMMAND_FAILED panel=UNCHANGED cleanup=EXACT_CID"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
