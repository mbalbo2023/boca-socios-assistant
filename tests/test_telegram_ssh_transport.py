"""P0 #315 regression: every protected Telegram SSH caller keeps secrets off argv."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from boca_socios import host_first_deploy as host
from boca_socios import telegram_ssh_transport as transport

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
SHA = "a" * 40
COMPOSE = "b" * 64
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "d" * 64
SEALED = "A" * 128  # Fake sealed input; never a real BotFather credential.
CHAT_HMAC = "e" * 64
OWNER = "-synthetic-private-owner-identity"


def _env(operation: str = "telegram-install", *, browser: bool = False) -> dict[str, str]:
    return {
        "BOCA_OPERATION": operation,
        "BOCA_IMAGE_REF": IMAGE,
        "BOCA_SOURCE_SHA": SHA,
        "BOCA_TELEGRAM_COMPOSE_SHA": COMPOSE,
        "BOCA_BETA_PANEL_ORIGIN": "http://localhost:8443",
        "BOCA_BETA_OWNER_SUBJECT": OWNER,
        "BOCA_TELEGRAM_ENVELOPE": SEALED if operation == "telegram-install" else "",
        "BOCA_TELEGRAM_EXPECTED_BOT_ID": "987654321",
        "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC": CHAT_HMAC,
        "BOCA_BROWSER_IMAGE_REF": BROWSER if browser else "",
        "BOCA_BROWSER_OVERLAY_SHA": "f" * 64 if browser else "",
        "BOCA_BROWSER_SECCOMP_SHA": "1" * 64 if browser else "",
        "BOCA_TELEGRAM_OWNER_READY": "ready",
        "GITHUB_RUN_ID": "314159",
        "BOCA_FAILED_TELEGRAM_RUN_ID": "271828",
    }


def _remote(frame: bytes) -> subprocess.CompletedProcess[bytes]:
    command = transport.remote_command()
    assert SEALED not in command and CHAT_HMAC not in command and OWNER not in command
    return subprocess.run(  # noqa: S603 - local fake Python/SH, no SSH or network
        ["/bin/bash", "-c", command],
        input=frame,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
        timeout=5,
        check=False,
    )


def test_four_telegram_ssh_calls_use_fixed_command_and_bounded_stdin() -> None:
    workflow = WORKFLOW.read_text()
    steps = (
        "Prove Telegram sender and egress absent before any attempt",
        "Operate only proven existing browser IPC services",
        "Immediately remove only the failed new Telegram sender and empty egress",
        "Execute protected Telegram schema, custody or one-shot test",
    )
    for name in steps:
        start = workflow.index("      - name: " + name)
        end = workflow.index("      - name: ", start + 14)
        section = workflow[start:end]
        assert len(re.findall(r"\bssh -F", section)) == 1, name
        assert "umask 077" in section
        assert "set -o pipefail" in section, name
        assert "telegram_ssh_transport emit < src/boca_socios/host_first_deploy.py" in section
        assert "telegram_ssh_transport command" in section
        assert "| env -u BOCA_TELEGRAM_ENVELOPE -u BOCA_TELEGRAM_EXPECTED_CHAT_HMAC" in section
        assert "set -x" not in section
        assert "shlex.join" not in section
        assert re.search(r"\w+_rc=\$\?", section)
    assert not any(
        "remote_command=" in line
        and any(
            variable in line
            for variable in (
                '"$BOCA_TELEGRAM_ENVELOPE"',
                '"$BOCA_TELEGRAM_EXPECTED_CHAT_HMAC"',
                '"$BOCA_TELEGRAM_EXPECTED_BOT_ID"',
                '"$expected_chat"',
            )
        )
        for line in workflow.splitlines()
    )


def test_transported_secrets_are_not_in_remote_os_argv_or_environment() -> None:
    source = b"""
import os,sys
secret = sys.argv[-3]
owner = sys.argv[-4]
chat = sys.argv[-1]
cmdline = open('/proc/self/cmdline', 'rb').read()
assert secret == 'A' * 128 and owner == '-synthetic-private-owner-identity'
assert chat == ''
assert secret.encode() not in cmdline and owner.encode() not in cmdline
assert ('e' * 64).encode() not in cmdline
assert 'BOCA_TELEGRAM_ENVELOPE' not in os.environ
print('BOCA_TELEGRAM_PRIVATE_STDIN verified')
"""
    result = _remote(transport.build_frame(source, _env()))
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"BOCA_TELEGRAM_PRIVATE_STDIN verified\n"
    assert result.stderr == b""


def test_runner_emit_and_static_command_have_distinct_secret_surfaces() -> None:
    source = b"print('BOCA_CLI source=EXECUTED')\n"
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT / "src"), **_env()}
    emitted = subprocess.run(  # noqa: S603 - local reviewed fixed Python emitter
        [sys.executable, "-m", "boca_socios.telegram_ssh_transport", "emit"],
        input=source,
        capture_output=True,
        env=environment,
        timeout=5,
        check=False,
    )
    assert emitted.returncode == 0 and emitted.stderr == b""
    assert SEALED.encode() in emitted.stdout  # Ciphertext is on an anonymous FD only.
    command = subprocess.run(  # noqa: S603 - static CLI, not SSH
        [sys.executable, "-m", "boca_socios.telegram_ssh_transport", "command"],
        capture_output=True,
        env=environment,
        timeout=5,
        check=True,
    )
    assert SEALED.encode() not in command.stdout
    assert CHAT_HMAC.encode() not in command.stdout
    assert OWNER.encode() not in command.stdout
    assert shlex.split(command.stdout.decode()) == shlex.split(transport.remote_command())
    result = _remote(emitted.stdout)
    assert result.returncode == 0 and result.stdout == b"BOCA_CLI source=EXECUTED\n"


def test_invalid_frames_are_rejected_before_remote_side_effects() -> None:
    with tempfile.TemporaryDirectory(prefix="boca-telegram-transport-test-") as temp:
        marker = Path(temp) / "unexpected-write"
        source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n".encode()
        valid = transport.build_frame(source, _env())
        offset = len(transport.MAGIC) + 4
        decoded = json.loads(valid[offset:])
        decoded["sha256"] = "0" * 64
        altered = json.dumps(decoded, separators=(",", ":")).encode()
        bad_digest = transport.MAGIC + len(altered).to_bytes(4, "big") + altered
        decoded["sha256"] = hashlib.sha256(source).hexdigest()
        decoded["version"] = True
        bad_version_bytes = json.dumps(decoded, separators=(",", ":")).encode()
        bad_version = (
            transport.MAGIC + len(bad_version_bytes).to_bytes(4, "big") + bad_version_bytes
        )
        decoded["version"] = 1
        duplicate = json.dumps({**decoded, "sha256": hashlib.sha256(source).hexdigest()})
        duplicate = duplicate[:-1] + ',"version":1}'
        duplicate_encoded = duplicate.encode()
        bad_duplicate = (
            transport.MAGIC + len(duplicate_encoded).to_bytes(4, "big") + duplicate_encoded
        )
        for bad in (valid[:-1], valid + b"x", bad_digest, bad_version, bad_duplicate):
            result = _remote(bad)
            assert result.returncode == 2
            assert result.stdout == b""
            assert result.stderr == b"BOCA_NO_GO: telegram_stdin_frame_invalid\n"
            assert not marker.exists()


def test_all_telegram_and_browser_modes_preserve_host_parser_contract() -> None:
    modes = (
        ("custody", "telegram-install", "telegram-install", "", False),
        ("custody", "telegram-test", "telegram-test", "", False),
        ("preflight", "beta-browser-telegram-start", "browser-telegram-preflight", "314159", True),
        ("lifecycle", "beta-browser-start", "browser-start", "", True),
        ("lifecycle", "beta-browser-restart", "browser-restart", "", True),
        ("lifecycle", "beta-browser-status", "browser-status", "", True),
        ("lifecycle", "beta-browser-acceptance", "browser-acceptance", "", True),
        ("lifecycle", "beta-browser-telegram-start", "browser-telegram-start", "314159", True),
        ("cleanup", "beta-browser-telegram-start", "browser-telegram-cleanup", "314159", True),
        ("cleanup", "beta-browser-telegram-recover", "browser-telegram-cleanup", "271828", True),
    )
    for mode, operation, phase, attempt, browser in modes:
        env = {**_env(operation, browser=browser), "BOCA_TELEGRAM_TRANSPORT_MODE": mode}
        argv = transport.phase_arguments(env)
        mock = Mock()
        with patch.object(host, "phase", mock), patch.object(host.sys, "argv", ["host.py", *argv]):
            assert host.main() == 0
        mock.assert_called_once()
        args = mock.call_args.args
        assert args[:6] == (phase, IMAGE, SHA, COMPOSE, "http://localhost:8443", OWNER)
        assert args[6] == (SEALED if phase == "telegram-install" else "")
        assert mock.call_args.kwargs.get("telegram_attempt_id", "") == attempt
        assert mock.call_args.kwargs.get("browser_image", "") == (BROWSER if browser else "")
        expected_chat = (
            CHAT_HMAC
            if phase in {"telegram-test", "browser-telegram-preflight", "browser-telegram-cleanup"}
            or mode == "lifecycle"
            else ""
        )
        assert args[8] == expected_chat


def test_unknown_mode_or_unready_sender_is_no_go_without_serializing_secrets() -> None:
    malformed = {
        **_env("beta-browser-telegram-start", browser=True),
        "BOCA_TELEGRAM_TRANSPORT_MODE": "lifecycle",
        "BOCA_TELEGRAM_OWNER_READY": "missing",
    }
    try:
        transport.build_frame(b"print('never')", malformed)
    except transport.TelegramTransportError:
        pass
    else:
        raise AssertionError("unready Telegram sender was serialized")
    malformed["BOCA_TELEGRAM_TRANSPORT_MODE"] = "other"
    try:
        transport.build_frame(b"print('never')", malformed)
    except transport.TelegramTransportError:
        pass
    else:
        raise AssertionError("unknown Telegram mode was serialized")


def test_frame_embeds_byte_exact_reviewed_helper_and_sha256() -> None:
    source = (ROOT / "src/boca_socios/host_first_deploy.py").read_bytes()
    frame = transport.build_frame(source, _env())
    assert len(frame) < transport.MAX_FRAME
    decoded = json.loads(frame[len(transport.MAGIC) + 4 :])
    assert decoded["script"].encode() == source
    assert decoded["sha256"] == hashlib.sha256(source).hexdigest()
