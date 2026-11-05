"""Single-SSH stdin transport for protected Telegram host phases (#315).

No token, sealed envelope, chat assertion or owner identity is serialized into
the OS argv of either SSH or its remote Python process.  The fixed remote
loader executes exactly one bounded, digest-checked helper and phase frame.
This module does not contact SSH, Telegram, Docker or any production host.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from collections.abc import Mapping

MAGIC = b"BOCA-TELEGRAM-SSH-STDIN-V1\0"
MAX_SCRIPT = 1_048_576
MAX_FRAME = 1_200_000
TELEGRAM_PHASES = frozenset(
    {"telegram-migrate", "telegram-prepare", "telegram-install", "telegram-verify", "telegram-test"}
)
BROWSER_OPERATIONS = frozenset(
    {
        "beta-browser-start",
        "beta-browser-restart",
        "beta-browser-status",
        "beta-browser-acceptance",
        "beta-browser-telegram-start",
    }
)
REMOTE_PHASES = (
    TELEGRAM_PHASES
    | {x.removeprefix("beta-") for x in BROWSER_OPERATIONS}
    | {
        "browser-telegram-preflight",
        "browser-telegram-cleanup",
    }
)
_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_BROWSER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_BOT_ID = re.compile(r"[1-9][0-9]{0,15}\Z")
_ENVELOPE = re.compile(r"[A-Za-z0-9_-]{100,5500}\Z")

# Static Python only; all sensitive operands arrive on the SSH stdin FD.
# The remote host needs stdlib, not an installed helper package. Validation
# occurs before any host operation, with constant/redacted errors.
REMOTE_CODE = r"""
import hashlib
import json
import re
import sys

def unique(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError('duplicate')
    return value

try:
    data = sys.stdin.buffer.read(1200001)
    magic = b'BOCA-TELEGRAM-SSH-STDIN-V1\0'
    if len(data) > 1200000 or not data.startswith(magic) or len(data) < len(magic) + 5:
        raise ValueError('frame')
    offset = len(magic)
    size = int.from_bytes(data[offset:offset + 4], 'big')
    content = data[offset + 4:]
    if size != len(content) or size <= 0:
        raise ValueError('length')
    frame = json.loads(content.decode('utf-8'), object_pairs_hook=unique)
    if not isinstance(frame, dict) or set(frame) != {'version', 'script', 'sha256', 'argv'}:
        raise ValueError('fields')
    source = frame['script']
    argv = frame['argv']
    if type(frame['version']) is not int or frame['version'] != 1 or not isinstance(source, str) or not isinstance(argv, list):
        raise ValueError('version')
    source_bytes = source.encode('utf-8')
    if not source_bytes or len(source_bytes) > 1048576:
        raise ValueError('source')
    if hashlib.sha256(source_bytes).hexdigest() != frame['sha256']:
        raise ValueError('digest')
    if len(argv) not in (10, 18, 20) or any(not isinstance(x, str) or '\0' in x or len(x) > 8192 for x in argv):
        raise ValueError('argv')
    sep = argv.index('--')
    if sep not in (0, 8, 10) or len(argv[sep + 1:]) != 9:
        raise ValueError('separator')
    if sep and argv[:8:2] != ['--browser-image', '--browser-overlay-sha', '--browser-seccomp-sha', '--browser-attempt-id']:
        raise ValueError('browser-flags')
    if sep == 10 and (argv[8] != '--telegram-attempt-id' or re.fullmatch(r'[1-9][0-9]{0,19}', argv[9]) is None):
        raise ValueError('telegram-flags')
    phase = argv[sep + 1]
    allowed = {'telegram-migrate', 'telegram-prepare', 'telegram-install', 'telegram-verify', 'telegram-test', 'browser-start', 'browser-restart', 'browser-status', 'browser-acceptance', 'browser-telegram-start', 'browser-telegram-preflight', 'browser-telegram-cleanup'}
    if phase not in allowed:
        raise ValueError('phase')
    if (phase.startswith('browser-') and sep < 8) or (phase.startswith('telegram-') and sep == 10):
        raise ValueError('options')
    if phase in {'browser-telegram-preflight', 'browser-telegram-start', 'browser-telegram-cleanup'} and sep != 10:
        raise ValueError('telegram-attempt')
except (ValueError, KeyError, IndexError, UnicodeError, TypeError):
    print('BOCA_NO_GO: telegram_stdin_frame_invalid', file=sys.stderr)
    raise SystemExit(2) from None

# This sys.argv mutation is Python-memory-only, never an OS process argv.
# It preserves host_first_deploy.py's existing argparse and host checks.
sys.argv = ['host_first_deploy.py', *argv]
exec(compile(source, '<boca-reviewed-host-helper>', 'exec'),
     {'__name__': '__main__', '__file__': '<boca-reviewed-host-helper>'})
""".strip()


class TelegramTransportError(ValueError):
    """Redacted invalid transport coordinates, never echoing input values."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value or any(ch in value for ch in ("\x00", "\n", "\r")):
        raise TelegramTransportError("invalid_transport_coordinates")
    return value


def phase_arguments(env: Mapping[str, str]) -> list[str]:
    """Build exact host parser args using env only; never print/return to shell."""
    operation = _required(env, "BOCA_OPERATION")
    mode = env.get("BOCA_TELEGRAM_TRANSPORT_MODE", "custody")
    if mode == "custody" and operation in TELEGRAM_PHASES:
        phase = operation
    elif mode == "preflight" and operation == "beta-browser-telegram-start":
        phase = "browser-telegram-preflight"
    elif mode == "lifecycle" and operation in BROWSER_OPERATIONS:
        phase = operation.removeprefix("beta-")
    elif mode == "cleanup" and operation in {
        "beta-browser-telegram-start",
        "beta-browser-telegram-recover",
    }:
        phase = "browser-telegram-cleanup"
    else:
        raise TelegramTransportError("invalid_transport_phase")
    image = _required(env, "BOCA_IMAGE_REF")
    source_sha = _required(env, "BOCA_SOURCE_SHA")
    compose_sha = _required(env, "BOCA_TELEGRAM_COMPOSE_SHA")
    origin = _required(env, "BOCA_BETA_PANEL_ORIGIN")
    owner = _required(env, "BOCA_BETA_OWNER_SUBJECT")
    envelope = env.get("BOCA_TELEGRAM_ENVELOPE", "")
    if (
        phase not in REMOTE_PHASES
        or _IMAGE.fullmatch(image) is None
        or _SHA40.fullmatch(source_sha) is None
        or _SHA64.fullmatch(compose_sha) is None
        or origin != "http://localhost:8443"
        or len(owner) > 256
        or (phase == "telegram-install") != bool(envelope)
        or (envelope and _ENVELOPE.fullmatch(envelope) is None)
    ):
        raise TelegramTransportError("invalid_transport_coordinates")

    bot = ""
    chat_hmac = ""
    owner_ready = env.get("BOCA_TELEGRAM_OWNER_READY", "") == "ready"
    if phase in {"telegram-test", "browser-telegram-preflight", "browser-telegram-cleanup"} or (
        mode == "lifecycle" and owner_ready
    ):
        bot = _required(env, "BOCA_TELEGRAM_EXPECTED_BOT_ID")
        chat_hmac = _required(env, "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC")
        if _BOT_ID.fullmatch(bot) is None or _SHA64.fullmatch(chat_hmac) is None:
            raise TelegramTransportError("invalid_transport_coordinates")

    browser_image = env.get("BOCA_BROWSER_IMAGE_REF", "")
    if mode != "custody" and not browser_image:
        raise TelegramTransportError("invalid_transport_browser")
    browser_args: list[str] = []
    if browser_image:
        overlay = _required(env, "BOCA_BROWSER_OVERLAY_SHA")
        seccomp = _required(env, "BOCA_BROWSER_SECCOMP_SHA")
        if (
            _BROWSER_IMAGE.fullmatch(browser_image) is None
            or _SHA64.fullmatch(overlay) is None
            or _SHA64.fullmatch(seccomp) is None
        ):
            raise TelegramTransportError("invalid_transport_browser")
        browser_args = [
            "--browser-image",
            browser_image,
            "--browser-overlay-sha",
            overlay,
            "--browser-seccomp-sha",
            seccomp,
            "--browser-attempt-id",
            "existing",
        ]
    telegram_args: list[str] = []
    if mode in {"preflight", "cleanup"} or phase == "browser-telegram-start":
        attempt = _required(env, "GITHUB_RUN_ID")
        if mode == "cleanup" and operation == "beta-browser-telegram-recover":
            attempt = _required(env, "BOCA_FAILED_TELEGRAM_RUN_ID")
        if _ATTEMPT.fullmatch(attempt) is None:
            raise TelegramTransportError("invalid_transport_attempt")
        telegram_args = ["--telegram-attempt-id", attempt]
    if phase == "browser-telegram-start" and not owner_ready:
        raise TelegramTransportError("invalid_transport_readiness")
    return [
        *browser_args,
        *telegram_args,
        "--",
        phase,
        image,
        source_sha,
        compose_sha,
        origin,
        owner,
        envelope,
        bot,
        chat_hmac,
    ]


def build_frame(script: bytes, env: Mapping[str, str]) -> bytes:
    """A single bounded payload for an authenticated SSH stdin, with no disk IO."""
    if not script or len(script) > MAX_SCRIPT:
        raise TelegramTransportError("invalid_transport_source")
    try:
        text = script.decode("utf-8")
    except UnicodeError as exc:
        raise TelegramTransportError("invalid_transport_source") from exc
    encoded = json.dumps(
        {
            "version": 1,
            "script": text,
            "sha256": hashlib.sha256(script).hexdigest(),
            "argv": phase_arguments(env),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) + len(MAGIC) + 4 > MAX_FRAME:
        raise TelegramTransportError("invalid_transport_length")
    return MAGIC + len(encoded).to_bytes(4, "big") + encoded


def remote_command() -> str:
    """Return a static shell-quoted command, never a Telegram operand."""
    return shlex.join(["python3", "-c", REMOTE_CODE])


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise TelegramTransportError("invalid_transport_mode")
        if sys.argv[1] == "command":
            print(remote_command())
        elif sys.argv[1] == "emit":
            script = sys.stdin.buffer.read(MAX_SCRIPT + 1)
            sys.stdout.buffer.write(build_frame(script, os.environ))
            sys.stdout.buffer.flush()
        else:
            raise TelegramTransportError("invalid_transport_mode")
    except (TelegramTransportError, OSError):
        print("BOCA_NO_GO: telegram_stdin_transport_invalid", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
