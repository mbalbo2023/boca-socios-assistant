"""STDIN-only protected owner/Site credential custody (issue #321).

This runner-side module never opens an SSH connection.  It emits a bounded
single SSH-stdin frame containing the reviewed host helper and its operands.
The remote command is constant; owner/Site values never enter OS argv.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from collections.abc import Mapping

MAGIC = b"BOCA-OWNER-SITE-SSH-STDIN-V1\0"
MAX_SCRIPT = 1_048_576
MAX_FRAME = 1_200_000
OWNER_PHASES = frozenset({"owner-prepare", "owner-install", "owner-verify"})
ENROLL_PHASES = frozenset({"owner-enroll-start", "owner-enroll-wait", "owner-enroll-finish"})
SITE_PHASES = frozenset({"site-prepare", "site-install", "site-verify"})
_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_CIPHERTEXT = re.compile(r"[A-Za-z0-9_-]+\Z")

# Identical boundary design to the separately owned Telegram transport, but
# with distinct phase/operand grammar.  All remote validation is stdlib-only.
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
    magic = b'BOCA-OWNER-SITE-SSH-STDIN-V1\0'
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
    if len(argv) not in (6, 11, 12) or any(not isinstance(x, str) or '\0' in x or len(x) > 45000 for x in argv):
        raise ValueError('argv')
    if argv[0] != '--':
        raise ValueError('separator')
    phase = argv[1]
    site = {'site-prepare', 'site-install', 'site-verify'}
    owner = {'owner-prepare', 'owner-install', 'owner-verify'}
    enroll = {'owner-enroll-start', 'owner-enroll-wait', 'owner-enroll-finish'}
    if not ((phase in site and len(argv) == 6) or (phase in owner and len(argv) == 11) or (phase in enroll and len(argv) == 12)):
        raise ValueError('phase')
    if re.fullmatch(r'ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}', argv[2]) is None or re.fullmatch(r'[0-9a-f]{40}', argv[3]) is None or re.fullmatch(r'[0-9a-f]{64}', argv[4]) is None:
        raise ValueError('coordinates')
    if phase in owner | enroll:
        if argv[5] != 'http://localhost:8443' or not (0 < len(argv[6]) <= 256):
            raise ValueError('owner')
        if any(argv[i] for i in (7, 8, 9)):
            raise ValueError('optional')
        if (phase == 'owner-install') != bool(argv[10]):
            raise ValueError('owner-envelope')
        if phase in enroll and re.fullmatch(r'[0-9a-f]{64}', argv[11]) is None:
            raise ValueError('enroll-digest')
    elif (phase == 'site-install') != bool(argv[5]):
        raise ValueError('site-envelope')
except (ValueError, KeyError, IndexError, UnicodeError, TypeError):
    print('BOCA_NO_GO: owner_site_stdin_frame_invalid', file=sys.stderr)
    raise SystemExit(2) from None

# sys.argv mutation exists solely in the Python child memory, never OS argv.
sys.argv = ['host_first_deploy.py', *argv]
exec(compile(source, '<boca-reviewed-host-helper>', 'exec'),
     {'__name__': '__main__', '__file__': '<boca-reviewed-host-helper>'})
""".strip()


class OwnerSiteTransportError(ValueError):
    """Redacted invalid source/coordinates; never embeds a supplied value."""


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "")
    if not value or any(c in value for c in ("\x00", "\n", "\r")):
        raise OwnerSiteTransportError("invalid_transport_coordinates")
    return value


def phase_arguments(env: Mapping[str, str]) -> list[str]:
    """Reconstruct existing host CLI arguments in-memory from runner env only."""
    operation = _required(env, "BOCA_OPERATION")
    phase = env.get("BOCA_OWNER_SITE_TRANSPORT_PHASE", "") or operation
    if phase in OWNER_PHASES and phase != operation:
        raise OwnerSiteTransportError("invalid_transport_phase")
    if phase in SITE_PHASES and phase != operation:
        raise OwnerSiteTransportError("invalid_transport_phase")
    if phase in ENROLL_PHASES and operation != "owner-enroll":
        raise OwnerSiteTransportError("invalid_transport_phase")
    if phase not in OWNER_PHASES | SITE_PHASES | ENROLL_PHASES:
        raise OwnerSiteTransportError("invalid_transport_phase")

    image = _required(env, "BOCA_IMAGE_REF")
    source_sha = _required(env, "BOCA_SOURCE_SHA")
    compose_sha = _required(env, "BOCA_OWNER_SITE_COMPOSE_SHA")
    if (
        _IMAGE.fullmatch(image) is None
        or _SHA40.fullmatch(source_sha) is None
        or _SHA64.fullmatch(compose_sha) is None
    ):
        raise OwnerSiteTransportError("invalid_transport_coordinates")

    if phase in SITE_PHASES:
        envelope = env.get("BOCA_SITE_ENVELOPE", "")
        if (phase == "site-install") != bool(envelope) or (
            envelope and (len(envelope) > 10923 or _CIPHERTEXT.fullmatch(envelope) is None)
        ):
            raise OwnerSiteTransportError("invalid_transport_site")
        return ["--", phase, image, source_sha, compose_sha, envelope]

    origin = _required(env, "BOCA_BETA_PANEL_ORIGIN")
    subject = _required(env, "BOCA_BETA_OWNER_SUBJECT")
    if origin != "http://localhost:8443" or len(subject) > 256:
        raise OwnerSiteTransportError("invalid_transport_owner")
    owner_envelope = env.get("BOCA_OWNER_ENVELOPE", "")
    if (phase == "owner-install") != bool(owner_envelope) or (
        owner_envelope
        and (len(owner_envelope) > 43691 or _CIPHERTEXT.fullmatch(owner_envelope) is None)
    ):
        raise OwnerSiteTransportError("invalid_transport_owner")
    argv = [
        "--",
        phase,
        image,
        source_sha,
        compose_sha,
        origin,
        subject,
        "",
        "",
        "",
        owner_envelope,
    ]
    if phase in ENROLL_PHASES:
        digest = _required(env, "BOCA_OWNER_CAPABILITY_SHA256")
        if owner_envelope or _SHA64.fullmatch(digest) is None:
            raise OwnerSiteTransportError("invalid_transport_enroll")
        argv.append(digest)
    return argv


def build_frame(script: bytes, env: Mapping[str, str]) -> bytes:
    """Build one binary frame; never log secrets or write them to disk."""
    if not script or len(script) > MAX_SCRIPT:
        raise OwnerSiteTransportError("invalid_transport_source")
    try:
        text = script.decode("utf-8")
    except UnicodeError as exc:
        raise OwnerSiteTransportError("invalid_transport_source") from exc
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
        raise OwnerSiteTransportError("invalid_transport_length")
    return MAGIC + len(encoded).to_bytes(4, "big") + encoded


def remote_command() -> str:
    """Constant quoted remote command, independent of sensitive coordinates."""
    return shlex.join(["python3", "-c", REMOTE_CODE])


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise OwnerSiteTransportError("invalid_transport_mode")
        if sys.argv[1] == "command":
            print(remote_command())
        elif sys.argv[1] == "emit":
            script = sys.stdin.buffer.read(MAX_SCRIPT + 1)
            sys.stdout.buffer.write(build_frame(script, os.environ))
            sys.stdout.buffer.flush()
        else:
            raise OwnerSiteTransportError("invalid_transport_mode")
    except (OwnerSiteTransportError, OSError):
        print("BOCA_NO_GO: owner_site_stdin_transport_invalid", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
