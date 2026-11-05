"""Execute the reviewed one-SSH Bash body against a fake, local Docker CLI.

Real Docker, SSH, the Boca host, browser modules and /data are never accessed.
Only synthetic stdout from the fake Boca container reaches the assertion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from boca_socios import host_official_notice_actions as actions


def _coords() -> actions.OfficialImportCoordinates:
    return actions.OfficialImportCoordinates(
        main_sha="a" * 40,
        controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        controller_release_run_id="555",
        controller_id="c" * 64,
        source_run_id="444",
        source_head_sha="d" * 40,
        artifact_id="333",
        artifact_sha256="e" * 64,
        snapshot_sha256="f" * 64,
        source_sha256="1" * 64,
        observed_at_utc="2026-11-05T12:41:50.606388+00:00",
    )


_FAKE_DOCKER = r"""
#!/usr/bin/python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
trace = Path(os.environ['BOCA_FAKE_TRACE'])
with trace.open('a', encoding='utf-8') as stream:
    stream.write(' '.join(args[:4]) + '\n')
assert args[:2] == ['--host', 'unix:///run/user/10001/docker.sock']
args = args[2:]
if args[0] == 'info':
    print('["name=rootless"]')
elif args[:2] == ['image', 'inspect']:
    print('sha256:' + '2' * 64)
elif args[:2] == ['container', 'inspect']:
    fmt = args[args.index('--format') + 1]
    mapping = {
        '{{.Id}}': 'c' * 64,
        '{{.Name}}': '/boca-socios-controller-1',
        '{{index .Config.Labels "com.docker.compose.project"}}': os.getenv('BOCA_FAKE_PROJECT', 'boca-socios'),
        '{{index .Config.Labels "com.docker.compose.service"}}': 'controller',
        '{{.Config.User}}': '10001:10001',
        '{{.Image}}': 'sha256:' + '2' * 64,
        '{{.State.Running}}': 'true',
        '{{.State.Health.Status}}': 'healthy',
        '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}|{{.Name}}|{{.RW}}{{end}}{{end}}': 'volume|boca-socios_boca_data|true',
    }
    if fmt not in mapping: raise SystemExit(4)
    print(mapping[fmt])
elif args[0] == 'exec':
    # A fake in-container import consumes a ZIP-like byte stream; no real data.
    data = sys.stdin.buffer.read()
    if data != b'FAKE_ZIP_FROM_GITHUB': raise SystemExit(5)
    print('BOCA_OFFICIAL_IMPORT state=CREATED main_sha=' + 'a' * 40 +
          ' artifact_sha256=' + 'e' * 64 + ' snapshot_sha256=' + 'f' * 64 +
          ' windows=5 actionable=false data=preserved readback=PASS')
else:
    raise SystemExit(6)
""".lstrip()


def _fake_host(
    tmp_path: Path, *, project: str = "boca-socios"
) -> tuple[subprocess.CompletedProcess[bytes], str]:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name, script in {
        "docker": _FAKE_DOCKER,
        "stat": "#!/bin/sh\nprintf '10001:600:1:regular file\\n'\n",
        "id": "#!/bin/sh\nprintf '10001\\n'\n",
    }.items():
        path = fakebin / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o700)
    lock = tmp_path / "boca-protected.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    sockpath = tmp_path / "socket"
    # This managed test environment disallows even loopback AF_UNIX sockets.
    # Replace ONLY the socket-type probe in this fake runner; the unchanged
    # production code and syntax test separately require an actual socket.
    sockpath.write_bytes(b"")
    command = (
        actions._HOST_SH.replace('-S "$socket"', '-f "$socket"')
        .replace("socket=/run/user/10001/docker.sock", f"socket={sockpath}")
        .replace("lock=/run/user/10001/boca-socios-protected-job.lock", f"lock={lock}")
    )
    trace = tmp_path / "trace"
    coords = _coords()
    token = actions.encode_coordinates(coords)
    run = subprocess.run(  # noqa: S603 - fake PATH tools and fixed local Bash
        [
            "/usr/bin/bash",
            "-c",
            command,
            "--",
            coords.controller_id,
            coords.controller_image,
            token,
        ],
        input=b"FAKE_ZIP_FROM_GITHUB",
        capture_output=True,
        timeout=15,
        check=False,
        env={
            "PATH": f"{fakebin}:/usr/bin:/bin",
            "BOCA_FAKE_TRACE": str(trace),
            "BOCA_FAKE_PROJECT": project,
        },
    )
    return run, trace.read_text(encoding="utf-8") if trace.exists() else ""


def test_host_shell_syntax_and_fixed_rootless_operation() -> None:
    lint = subprocess.run(  # noqa: S603 - local shell syntax check only
        ["/usr/bin/bash", "-n"],
        input=actions._HOST_SH,
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert lint.returncode == 0, lint.stderr
    assert "docker --host unix:///run/user/10001/docker.sock" in actions._HOST_SH
    assert '-S "$socket"' in actions._HOST_SH
    for forbidden in ("docker system prune", "docker image rm", "docker rm", "docker compose down"):
        assert forbidden not in actions._HOST_SH


def test_single_host_shell_accepts_only_exact_boca_identity(tmp_path: Path) -> None:
    run, trace = _fake_host(tmp_path)
    assert run.returncode == 0, run.stderr
    assert run.stdout.decode().startswith("BOCA_OFFICIAL_IMPORT state=CREATED")
    assert "exec -i" in trace
    assert "prune" not in trace


def test_foreign_docker_project_fails_before_container_import(tmp_path: Path) -> None:
    run, trace = _fake_host(tmp_path, project="porota")
    assert run.returncode != 0
    assert "exec -i" not in trace
    assert b"BOCA_OFFICIAL_IMPORT state=CREATED" not in run.stdout
