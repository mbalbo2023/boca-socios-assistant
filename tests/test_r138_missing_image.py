"""Exercise the bytes that Docker writes when the exact #904 release digest is absent."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from boca_socios import host_first_deploy as host

CONTROLLER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant"
    "@sha256:40ceea681a8568e93bb2d22decb294e712e70de32b68156d998a0bf612b7569b"
)
WORKER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser"
    "@sha256:8fb79002e937de1ca014db502af053a37046fa4361c44a7719f24e813faf185c"
)
REVISION = "b6a53c3348ce39c4d8536487e2baed559c2ca42f"
MISSING = f"Error: No such image: {CONTROLLER}".encode("ascii")


def docker_inspect(
    monkeypatch: pytest.MonkeyPatch, ref: str, code: int, stdout: bytes, stderr: bytes
) -> None:
    # Use real subprocess pipes so universal-newline decoding cannot mask a CR or CRLF.
    run = subprocess.run
    writer = (
        "import os, sys\n"
        "os.write(1, bytes.fromhex(sys.argv[1]))\n"
        "os.write(2, bytes.fromhex(sys.argv[2]))\n"
        "sys.exit(int(sys.argv[3]))\n"
    )

    def reply(argv: tuple[str, ...], **options: Any) -> subprocess.CompletedProcess[Any]:
        assert argv == ("docker", "image", "inspect", "--format", "{{json .}}", ref)
        return run(
            [sys.executable, "-I", "-c", writer, stdout.hex(), stderr.hex(), str(code)], **options
        )

    monkeypatch.setattr(host.subprocess, "run", reply)


@pytest.mark.parametrize("ref", [CONTROLLER, WORKER])
@pytest.mark.parametrize("stdout", [b"", b"\n"])
@pytest.mark.parametrize("prefix", ["Error: ", "Error response from daemon: "])
@pytest.mark.parametrize("terminator", [b"", b"\n"])
def test_exact_digest_missing_with_empty_docker_template(
    monkeypatch: pytest.MonkeyPatch, ref: str, stdout: bytes, prefix: str, terminator: bytes
) -> None:
    docker_inspect(
        monkeypatch, ref, 1, stdout, f"{prefix}No such image: {ref}".encode("ascii") + terminator
    )
    assert host._browser_image_absent(ref, REVISION) is True


@pytest.mark.parametrize("stdout", [b"\n\n", b"\r", b"\r\n", b" \n", b"\nCANARY", b"[]\n"])
def test_additional_stdout_never_proves_image_absence(
    monkeypatch: pytest.MonkeyPatch, stdout: bytes
) -> None:
    docker_inspect(monkeypatch, CONTROLLER, 1, stdout, MISSING + b"\n")
    with pytest.raises(host.PreflightError):
        host._browser_image_absent(CONTROLLER, REVISION)


@pytest.mark.parametrize(
    ("code", "stderr"),
    [
        (0, MISSING),
        (2, MISSING),
        (1, b" " + MISSING),
        (1, MISSING + b" "),
        (1, MISSING + b"\n\n"),
        (1, MISSING + b"\r\n"),
        (1, MISSING + b"\nCANARY"),
        (1, f"Error: No such image: {WORKER}".encode("ascii")),
        (1, b"Cannot connect to the Docker daemon"),
    ],
)
def test_diagnostic_must_identify_only_the_requested_digest(
    monkeypatch: pytest.MonkeyPatch, code: int, stderr: bytes
) -> None:
    docker_inspect(monkeypatch, CONTROLLER, code, b"", stderr)
    with pytest.raises(host.PreflightError):
        host._browser_image_absent(CONTROLLER, REVISION)


@pytest.mark.parametrize("ref", [CONTROLLER, WORKER])
def test_present_digest_still_requires_the_release_revision(
    monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    record = {
        "RepoDigests": [ref],
        "RepoTags": [],
        "Size": 17,
        "Config": {"Labels": {"org.opencontainers.image.revision": REVISION}},
    }
    docker_inspect(monkeypatch, ref, 0, json.dumps(record).encode("ascii") + b"\n", b"")
    assert host._browser_image_absent(ref, REVISION) is False
    with pytest.raises(host.PreflightError):
        host._browser_image_absent(ref, "f" * 40)
