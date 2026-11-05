"""Runner-only gate for two Boca protected post-Cutover operations (#352).

Never contacts GitHub, Docker, Telegram, SSH, public Boca, or any volume.
A dispatch input carries only canonical PUBLIC coordinates. It cannot approve
itself: a different protected GitHub Environment variable must match a
run-specific GO digest before the workflow may even configure SSH.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "boca-protected-action-v1"
GO_VERSION = "boca-protected-operation-go-v1"
REPOSITORY = "mbalbo2023/boca-socios-assistant"
OWNER = "mbalbo2023"
MAX_CONTEXT_BYTES = 2048
_MAX_ENCODED = 2732

_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,2732}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_CONTROLLER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z"
)
_WORKER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
_SAFE_PATH = re.compile(r"/[A-Za-z0-9._/-]{1,255}\Z")
_OPERATIONS = {"lifecycle-apply": "lifecycle", "telegram-activate": "telegram"}
_COMMON = frozenset(
    {
        "version",
        "kind",
        "attempt_id",
        "source_sha",
        "controller_id",
        "controller_image",
        "worker_id",
        "worker_image",
        "browser_attempt",
        "controller_config_hash",
        "worker_config_hash",
        "data_mountpoint",
    }
)
_LIFECYCLE = frozenset({"expected_component", "expected_target"})
_TELEGRAM = frozenset(
    {
        "cutover_attempt",
        "cutover_receipt_sha256",
        "owner_digest",
        "recipient_fingerprint",
        "sender_expected_state",
    }
)
_LIFECYCLE_SENDER = frozenset({"sender_id", "sender_config_hash", "sender_attempt_id", "sender_state"})
_TELEGRAM_SENDER = frozenset({"sender_id", "sender_image", "sender_config_hash", "sender_attempt"})
_GO_NAMES = {
    "lifecycle-apply": "BOCA_LIFECYCLE_GO_BINDING_SHA256",
    "telegram-activate": "BOCA_TELEGRAM_ACTIVATE_GO_BINDING_SHA256",
}


class ProtectedActionError(ValueError):
    """NO_GO before SSH; never include private or untrusted source values."""


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtectedActionError("duplicate protected action context fields")
        result[key] = value
    return result


def _environment(environ: Mapping[str, str]) -> None:
    expected = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_ACTOR": OWNER,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_SERVICE": "controller",
    }
    if any(environ.get(key) != value for key, value in expected.items()):
        raise ProtectedActionError("protected Boca Actions identity invalid")
    if (
        _SHA.fullmatch(environ.get("GITHUB_SHA", "")) is None
        or environ.get("BOCA_SOURCE_SHA") != environ.get("GITHUB_SHA")
        or _ATTEMPT.fullmatch(environ.get("GITHUB_RUN_ID", "")) is None
        or _ATTEMPT.fullmatch(environ.get("BOCA_RELEASE_RUN_ID", "")) is None
        or _CONTROLLER_IMAGE.fullmatch(environ.get("BOCA_IMAGE_REF", "")) is None
        or _WORKER_IMAGE.fullmatch(environ.get("BOCA_BROWSER_IMAGE_REF", "")) is None
    ):
        raise ProtectedActionError("source, immutable release or run pin invalid")


def _decode_bytes(encoded: str) -> dict[str, Any]:
    if type(encoded) is not str or _TOKEN.fullmatch(encoded) is None:
        raise ProtectedActionError("protected context token malformed")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * ((-len(encoded)) % 4))
        if (
            not 0 < len(raw) <= MAX_CONTEXT_BYTES
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != encoded
        ):
            raise ProtectedActionError("protected context not canonical/size bounded")
        parsed = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProtectedActionError("protected context JSON invalid") from exc
    if (
        type(parsed) is not dict
        or any(type(key) is not str or type(value) is not str for key, value in parsed.items())
        or _canonical(parsed) != raw
    ):
        raise ProtectedActionError("protected context must use canonical string fields")
    return parsed


def _checked_absolute_path(raw: str, *, telegram: bool) -> None:
    if telegram:
        if raw != "/data":
            raise ProtectedActionError("Telegram stage mountpoint must be /data")
        return
    if (
        _SAFE_PATH.fullmatch(raw) is None
        or raw == "/"
        or "//" in raw
        or any(part in ("", ".", "..") for part in raw.split("/")[1:])
        or str(PurePosixPath(raw)) != raw
    ):
        raise ProtectedActionError("lifecycle host volume mountpoint path malformed")
    # A future real-rootless volume path is NOT guessed from a laptop.
    # The host probe must check equality with the actual Boca Docker volume.


def _validate_payload(
    payload: dict[str, Any], *, operation: str, environ: Mapping[str, str]
) -> dict[str, str]:
    _environment(environ)
    kind = _OPERATIONS.get(operation)
    if kind is None or payload.get("kind") != kind or payload.get("version") != VERSION:
        raise ProtectedActionError("protected action kind/version mismatched")
    expected = _COMMON | (_LIFECYCLE if kind == "lifecycle" else _TELEGRAM)
    keys = set(payload)
    if kind == "lifecycle":
        permitted = (expected, expected | _LIFECYCLE_SENDER)
    else:
        permitted = (expected, expected | _TELEGRAM_SENDER)
    if keys not in permitted:
        raise ProtectedActionError("protected action keys not allowlisted")
    if (
        _ATTEMPT.fullmatch(payload["attempt_id"]) is None
        or payload["attempt_id"] != environ["GITHUB_RUN_ID"]
        or _SHA.fullmatch(payload["source_sha"]) is None
        or payload["source_sha"] != environ["BOCA_SOURCE_SHA"]
        or _HASH.fullmatch(payload["controller_id"]) is None
        or _HASH.fullmatch(payload["worker_id"]) is None
        or payload["controller_id"] == payload["worker_id"]
        or _CONTROLLER_IMAGE.fullmatch(payload["controller_image"]) is None
        or payload["controller_image"] != environ["BOCA_IMAGE_REF"]
        or _WORKER_IMAGE.fullmatch(payload["worker_image"]) is None
        or payload["worker_image"] != environ["BOCA_BROWSER_IMAGE_REF"]
        or _ATTEMPT.fullmatch(payload["browser_attempt"]) is None
        or _HASH.fullmatch(payload["controller_config_hash"]) is None
        or _HASH.fullmatch(payload["worker_config_hash"]) is None
    ):
        raise ProtectedActionError("reviewed controller/worker coordinates invalid")
    _checked_absolute_path(payload["data_mountpoint"], telegram=(kind == "telegram"))
    if kind == "lifecycle":
        if payload["expected_component"] not in ("bot", "chromium") or payload[
            "expected_target"
        ] not in ("start", "stop"):
            raise ProtectedActionError("unreviewed lifecycle command requested")
        if _LIFECYCLE_SENDER.issubset(keys):
            if (
                _HASH.fullmatch(payload["sender_id"]) is None
                or _HASH.fullmatch(payload["sender_config_hash"]) is None
                or _ATTEMPT.fullmatch(payload["sender_attempt_id"]) is None
                or payload["sender_state"] not in ("on", "off")
                or payload["sender_id"] in (payload["controller_id"], payload["worker_id"])
            ):
                raise ProtectedActionError("lifecycle sender identity pin invalid")
    else:
        if (
            _ATTEMPT.fullmatch(payload["cutover_attempt"]) is None
            or payload["cutover_attempt"] == payload["attempt_id"]
            or any(
                _HASH.fullmatch(payload[name]) is None
                for name in (
                    "cutover_receipt_sha256",
                    "owner_digest",
                    "recipient_fingerprint",
                )
            )
            or payload["sender_expected_state"] not in ("absent", "stopped")
        ):
            raise ProtectedActionError("Telegram not bound to prior Cutover and sender OFF")
        sender_pinned = _TELEGRAM_SENDER.issubset(keys)
        if (payload["sender_expected_state"] == "stopped") != sender_pinned:
            raise ProtectedActionError("Telegram sender pins contradict expected state")
        if sender_pinned and (
            _HASH.fullmatch(payload["sender_id"]) is None
            or payload["sender_id"] in (payload["controller_id"], payload["worker_id"])
            or payload["sender_image"] != payload["controller_image"]
            or _HASH.fullmatch(payload["sender_config_hash"]) is None
            or _ATTEMPT.fullmatch(payload["sender_attempt"]) is None
        ):
            raise ProtectedActionError("Telegram stopped sender pins invalid")
    return payload


def decode_context(
    encoded: str, *, operation: str, environ: Mapping[str, str]
) -> dict[str, str]:
    """Only canonical, nonsecret exact coordinates are permitted by Actions."""
    payload = _decode_bytes(encoded)
    return _validate_payload(payload, operation=operation, environ=environ)


def expected_go_binding(
    context: dict[str, str], *, operation: str, environ: Mapping[str, str]
) -> str:
    """Hash an independent, run/actor/source/release-bound authorization record."""
    _validate_payload(context, operation=operation, environ=environ)
    record = {
        "version": GO_VERSION,
        "repository": environ["GITHUB_REPOSITORY"],
        "actor": environ["GITHUB_ACTOR"],
        "ref": environ["GITHUB_REF"],
        "source_sha": environ["BOCA_SOURCE_SHA"],
        "run_id": environ["GITHUB_RUN_ID"],
        "run_attempt": environ["GITHUB_RUN_ATTEMPT"],
        "release_run_id": environ["BOCA_RELEASE_RUN_ID"],
        "operation": operation,
        "context_sha256": hashlib.sha256(_canonical(context)).hexdigest(),
    }
    return hashlib.sha256(b"boca-protected-operation-go-v1:\x00" + _canonical(record)).hexdigest()


def require_go_binding(
    context: dict[str, str],
    *,
    operation: str,
    environ: Mapping[str, str],
    approved: str,
) -> None:
    """A variable in the protected Environment, never dispatch input, is GO."""
    expected = expected_go_binding(context, operation=operation, environ=environ)
    if (
        type(approved) is not str
        or _HASH.fullmatch(approved) is None
        or not hmac.compare_digest(expected, approved)
    ):
        raise ProtectedActionError("independent protected operation GO absent/mismatched")


def _write_private(path: Path, text: str) -> None:
    """Create one output token with O_EXCL; never overwrite a stale job receipt."""
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(text.encode("ascii"))
            stream.flush()
            os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise ProtectedActionError("protected runner output inode invalid")
    finally:
        os.close(descriptor)


def main() -> int:
    """Runner-only: validate exact source/GO, then stage nonsecret host pins."""
    environ = os.environ
    operation = environ.get("BOCA_OPERATION", "")
    go_name = _GO_NAMES.get(operation)
    try:
        if len(sys.argv) != 2 or sys.argv[1] != "--from-actions" or go_name is None:
            raise ProtectedActionError("unreviewed protected action invocation")
        encoded = environ.get("BOCA_PROTECTED_ACTION_CONTEXT", "")
        payload = decode_context(encoded, operation=operation, environ=environ)
        approved = environ.get(go_name, "")
        require_go_binding(payload, operation=operation, environ=environ, approved=approved)
        runner = Path(environ.get("RUNNER_TEMP", ""))
        if not runner.is_absolute() or not runner.is_dir():
            raise ProtectedActionError("protected runner temp directory unavailable")
        _write_private(runner / "boca-protected-action.token", encoded + "\n")
        _write_private(runner / "boca-protected-action.approved", approved + "\n")
        print("BOCA_PROTECTED_ACTION state=REVIEWED host=untouched approved_context=exact")
        return 0
    except (ProtectedActionError, OSError, UnicodeError):
        print(
            "BOCA_PROTECTED_ACTION state=NO_GO host=untouched reason=invalid_go_or_context",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
