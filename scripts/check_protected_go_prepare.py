"""Code-only, two-human-dispatch Boca lifecycle GO PREPARE -> APPLY (#352).

No SSH, Docker, Telegram, external navigation, host token or GitHub API calls
are made by this module. The existing workflow must separately authenticate a
successful PREPARE run and retrieve its reviewed immutable artifact. A public
context is never itself authority; an independently configured Environment GO
digest of that exact receipt is mandatory before host wiring may run.
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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import check_protected_action_context as context

RECEIPT_VERSION = "boca-protected-prepared-go-v1"
GO_DOMAIN = b"boca-protected-prepared-go-v1:\x00"
GO_TTL_SECONDS = 24 * 60 * 60
RUNNER_RECEIPT = "boca-lifecycle-prepare.receipt.json"
RUNNER_APPLY_CONTEXT = "boca-lifecycle-apply-context.txt"
RUNNER_HOST_CONTEXT = "boca-protected-action.token"
RUNNER_HOST_APPROVAL = "boca-protected-action.approved"
_ARTIFACT_MANIFEST = "boca-release-manifest/boca-release-manifest.json"
_ARTIFACT_BROWSER = "boca-browser-release-manifest/boca-browser-release-manifest.json"
_ARTIFACT_BUNDLE = "boca-protected-lifecycle-review.pyz"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PREPARE_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_APPLY_OPERATIONS = frozenset({"lifecycle-apply"})
_RECEIPT_KEYS = frozenset(
    {
        "version",
        "operation",
        "repository",
        "actor",
        "ref",
        "source_sha",
        "release_run_id",
        "prepare_run_id",
        "prepare_attempt",
        "prepared_at_utc",
        "valid_until_utc",
        "public_context_sha256",
        "release_manifest_sha256",
        "browser_manifest_sha256",
        "bundle_sha256",
        "owner_subject_sha256",
    }
)


class PreparedGoError(ValueError):
    """NO_GO before host; no secrets or source inputs in error messages."""


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_stamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PreparedGoError("prepared GO UTC timestamp invalid")
    try:
        actual = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreparedGoError("prepared GO UTC timestamp invalid") from exc
    if actual.tzinfo is None or _stamp(actual) != value:
        raise PreparedGoError("prepared GO UTC timestamp not canonical")
    return actual


def _sha_reviewed(path: Path, max_bytes: int = 2_500_000) -> str:
    """Bounded, regular, non-symlink reviewed source file from runner temp."""
    if not path.is_absolute() or path.is_symlink():
        raise PreparedGoError("reviewed file identity invalid")
    try:
        meta = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(meta.st_mode) or not (0 < meta.st_size <= max_bytes):
            raise PreparedGoError("reviewed file size/type invalid")
        raw = path.read_bytes()
    except OSError as exc:
        raise PreparedGoError("reviewed runner artifact unavailable") from exc
    if len(raw) != meta.st_size:
        raise PreparedGoError("reviewed file changed while hashing")
    return hashlib.sha256(raw).hexdigest()


def _reviewed_evidence(environ: Mapping[str, str]) -> dict[str, str]:
    runner = Path(environ.get("RUNNER_TEMP", ""))
    if not runner.is_absolute() or not runner.is_dir():
        raise PreparedGoError("runner review directory unavailable")
    return {
        "release_manifest_sha256": _sha_reviewed(runner / _ARTIFACT_MANIFEST),
        "browser_manifest_sha256": _sha_reviewed(runner / _ARTIFACT_BROWSER),
        "bundle_sha256": _sha_reviewed(runner / _ARTIFACT_BUNDLE, 5_000_000),
    }


def _owner_digest(environ: Mapping[str, str]) -> str:
    subject = environ.get("BOCA_BETA_OWNER_SUBJECT", "")
    if not subject or len(subject) > 1024:
        raise PreparedGoError("owner subject custody unavailable")
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _host_context(
    payload: dict[str, str], *, prepare_id: str, environ: Mapping[str, str]
) -> dict[str, str]:
    if _PREPARE_ID.fullmatch(prepare_id) is None:
        raise PreparedGoError("prepared run ID invalid")
    current_id = environ.get("GITHUB_RUN_ID", "")
    if current_id == prepare_id:
        raise PreparedGoError("PREPARE and APPLY must be separate GitHub runs")
    candidate = payload | {"prepare_run_id": prepare_id, "attempt_id": current_id}
    try:
        return context._validate_payload(  # noqa: SLF001 - one owner, shared checker
            candidate, operation="lifecycle-apply", environ=environ
        )
    except context.ProtectedActionError as exc:
        raise PreparedGoError("prepared host context differs from reviewed release") from exc


def _untrusted_public(encoded: str) -> dict[str, str]:
    try:
        payload = context._decode_bytes(encoded)  # noqa: SLF001 - shared canonical codec
    except context.ProtectedActionError as exc:
        raise PreparedGoError("protected public context invalid") from exc
    if payload.get("kind") != "lifecycle" or payload.get("version") != context.VERSION:
        raise PreparedGoError("only reviewed lifecycle PREPARE implemented")
    return payload


def decode_prepare_input(
    encoded: str, *, environ: Mapping[str, str]
) -> dict[str, str]:
    """Dispatch PREPARE has no unknowable current-run attempt or PREPARE ID."""
    context._environment(environ)  # noqa: SLF001 - exact Actions identity
    payload = _untrusted_public(encoded)
    keys = set(payload)
    common = context._COMMON - {"attempt_id", "prepare_run_id"}  # noqa: SLF001
    required = common | context._LIFECYCLE  # noqa: SLF001
    sender = context._LIFECYCLE_SENDER  # noqa: SLF001
    if keys not in (required, required | sender):
        raise PreparedGoError("unreviewed lifecycle PREPARE input fields")
    # Shape validation uses a synthetic second-run marker solely in memory;
    # the PREPARE receipt still records the REAL original GITHUB_RUN_ID.
    prepare_id = environ["GITHUB_RUN_ID"]
    hypothetical_apply = "1" if prepare_id != "1" else "2"
    hypothetical_environment = dict(environ, GITHUB_RUN_ID=hypothetical_apply)
    _host_context(payload, prepare_id=prepare_id, environ=hypothetical_environment)
    return payload


def decode_apply_input(
    encoded: str, *, environ: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Dispatch APPLY contains a known prior PREPARE ID; runner adds its own."""
    context._environment(environ)  # noqa: SLF001
    body = _untrusted_public(encoded)
    prepare_id = body.get("prepare_run_id", "")
    if not prepare_id:
        raise PreparedGoError("APPLY missing immutable PREPARE reference")
    static = dict(body)
    del static["prepare_run_id"]
    hosted = _host_context(static, prepare_id=prepare_id, environ=environ)
    return static, hosted


def build_prepare_receipt(
    public: dict[str, str],
    *,
    environ: Mapping[str, str],
    now: datetime,
) -> dict[str, str]:
    """Public immutable review object; no secret owner bytes are included."""
    if now.tzinfo is None:
        raise PreparedGoError("UTC review clock unavailable")
    start = now.astimezone(UTC).replace(microsecond=0)
    if _PREPARE_ID.fullmatch(environ["GITHUB_RUN_ID"]) is None:
        raise PreparedGoError("PREPARE GitHub run ID unavailable")
    return {
        "version": RECEIPT_VERSION,
        "operation": "lifecycle-apply",
        "repository": environ["GITHUB_REPOSITORY"],
        "actor": environ["GITHUB_ACTOR"],
        "ref": environ["GITHUB_REF"],
        "source_sha": environ["BOCA_SOURCE_SHA"],
        "release_run_id": environ["BOCA_RELEASE_RUN_ID"],
        "prepare_run_id": environ["GITHUB_RUN_ID"],
        "prepare_attempt": environ["GITHUB_RUN_ATTEMPT"],
        "prepared_at_utc": _stamp(start),
        "valid_until_utc": _stamp(start + timedelta(seconds=GO_TTL_SECONDS)),
        "public_context_sha256": hashlib.sha256(_canonical(public)).hexdigest(),
        "owner_subject_sha256": _owner_digest(environ),
        **_reviewed_evidence(environ),
    }


def expected_go_for_receipt(receipt: dict[str, str]) -> str:
    """GO object is known only AFTER PREPARE; no future run ID in digest."""
    if set(receipt) != _RECEIPT_KEYS or any(type(x) is not str for x in receipt.values()):
        raise PreparedGoError("prepared receipt shape invalid")
    return hashlib.sha256(GO_DOMAIN + _canonical(receipt)).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink():
        raise PreparedGoError("prepared receipt path invalid")
    try:
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            raise PreparedGoError("prepared receipt type invalid")
        raw = path.read_bytes()
        if not 0 < len(raw) <= 4096:
            raise PreparedGoError("prepared receipt size invalid")
        parsed = json.loads(raw.decode("ascii"), object_pairs_hook=context._unique_fields)  # noqa: SLF001
    except (OSError, UnicodeError, ValueError) as exc:
        raise PreparedGoError("prepared receipt corrupt") from exc
    if not isinstance(parsed, dict) or _canonical(parsed) != raw:
        raise PreparedGoError("prepared receipt noncanonical")
    return parsed


def verify_prepared_github_run(
    metadata: dict[str, Any], *, prepare_run_id: str, environ: Mapping[str, str]
) -> None:
    """Runner's GH API GET must attest successful source run, no write APIs."""
    if (
        type(metadata) is not dict
        or metadata.get("id") != int(prepare_run_id)
        or metadata.get("event") != "workflow_dispatch"
        or metadata.get("run_attempt") != 1
        or metadata.get("status") != "completed"
        or metadata.get("conclusion") != "success"
        or metadata.get("head_sha") != environ["BOCA_SOURCE_SHA"]
        or metadata.get("head_branch") != "main"
        or metadata.get("path") not in (
            ".github/workflows/boca-first-deploy.yml",
            "mbalbo2023/boca-socios-assistant/.github/workflows/boca-first-deploy.yml",
        )
        or not isinstance(metadata.get("actor"), dict)
        or metadata["actor"].get("login") != context.OWNER
        or not isinstance(metadata.get("repository"), dict)
        or metadata["repository"].get("full_name") != context.REPOSITORY
    ):
        raise PreparedGoError("PREPARE GitHub Actions run not independently attested")


def verify_apply_go(
    public: dict[str, str],
    hosted: dict[str, str],
    receipt: dict[str, str],
    *,
    environ: Mapping[str, str],
    approved: str,
    now: datetime,
    source_run: dict[str, Any],
) -> str:
    """Only independently protected exact receipt digest approves host attempt."""
    if now.tzinfo is None:
        raise PreparedGoError("review clock unavailable")
    if hosted != _host_context(public, prepare_id=hosted.get("prepare_run_id", ""), environ=environ):
        raise PreparedGoError("runtime injected host context changed")
    expected = expected_go_for_receipt(receipt)
    if not isinstance(approved, str) or _SHA.fullmatch(approved) is None:
        raise PreparedGoError("independent reviewed GO absent")
    if not hmac.compare_digest(expected, approved):
        raise PreparedGoError("independent prepared-receipt GO mismatched")
    start = _parse_stamp(receipt["prepared_at_utc"])
    until = _parse_stamp(receipt["valid_until_utc"])
    instant = now.astimezone(UTC)
    if (
        until - start != timedelta(seconds=GO_TTL_SECONDS)
        or instant < start - timedelta(minutes=5)
        or instant > until
    ):
        raise PreparedGoError("prepared GO receipt expired or time invalid")
    if any(
        receipt.get(key) != value
        for key, value in {
            "version": RECEIPT_VERSION,
            "operation": "lifecycle-apply",
            "repository": environ["GITHUB_REPOSITORY"],
            "actor": environ["GITHUB_ACTOR"],
            "ref": environ["GITHUB_REF"],
            "source_sha": environ["BOCA_SOURCE_SHA"],
            "release_run_id": environ["BOCA_RELEASE_RUN_ID"],
            "prepare_run_id": hosted["prepare_run_id"],
            "prepare_attempt": "1",
            "public_context_sha256": hashlib.sha256(_canonical(public)).hexdigest(),
            "owner_subject_sha256": _owner_digest(environ),
            **_reviewed_evidence(environ),
        }.items()
    ):
        raise PreparedGoError("prepared reviewed source/owner/artifacts drifted")
    if hosted["attempt_id"] == hosted["prepare_run_id"]:
        raise PreparedGoError("PREPARE cannot authorize its own host effects")
    verify_prepared_github_run(
        source_run, prepare_run_id=hosted["prepare_run_id"], environ=environ
    )
    return approved


def _runner() -> Path:
    runner = Path(os.environ.get("RUNNER_TEMP", ""))
    if not runner.is_absolute() or not runner.is_dir():
        raise PreparedGoError("protected runner temp unavailable")
    return runner


def _decode_private_run(path: Path) -> dict[str, Any]:
    return _strict_json(path)


def main() -> int:
    """No path can access host. Workflow chooses later post-GO host call."""
    env = os.environ
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ("--prepare", "--prepare-ref", "--apply"):
            raise PreparedGoError("unreviewed protected GO phase")
        operation = env.get("BOCA_OPERATION", "")
        phase = sys.argv[1]
        if phase == "--prepare-ref":
            if operation != "lifecycle-apply":
                raise PreparedGoError("prepared-ref operation invalid")
            _, hosted = decode_apply_input(
                env.get("BOCA_PROTECTED_ACTION_CONTEXT", ""), environ=env
            )
            print(hosted["prepare_run_id"])
            return 0
        if phase == "--prepare":
            if operation != "protected-go-prepare":
                raise PreparedGoError("PREPARE operation invalid")
            public = decode_prepare_input(
                env.get("BOCA_PROTECTED_ACTION_CONTEXT", ""), environ=env
            )
            receipt = build_prepare_receipt(public, environ=env, now=datetime.now(UTC))
            apply_token = base64.urlsafe_b64encode(
                _canonical(public | {"prepare_run_id": env["GITHUB_RUN_ID"]})
            ).rstrip(b"=").decode("ascii")
            runner = _runner()
            context._write_private(  # noqa: SLF001
                runner / RUNNER_RECEIPT, _canonical(receipt).decode("ascii")
            )
            context._write_private(  # noqa: SLF001
                runner / RUNNER_APPLY_CONTEXT, apply_token + "\n"
            )
            print(
                "BOCA_GO_PREPARE state=REVIEWABLE host_calls=0 "
                + "prepare_run_id=" + env["GITHUB_RUN_ID"]
                + " operation=lifecycle-apply "
                + "go_sha256=" + expected_go_for_receipt(receipt)
            )
            return 0
        if operation != "lifecycle-apply":
            raise PreparedGoError("APPLY operation invalid")
        public, hosted = decode_apply_input(
            env.get("BOCA_PROTECTED_ACTION_CONTEXT", ""), environ=env
        )
        runner = _runner()
        receipt = _strict_json(runner / RUNNER_RECEIPT)
        metadata = _decode_private_run(runner / "boca-lifecycle-prepare-run.json")
        approved = verify_apply_go(
            public,
            hosted,
            receipt,
            environ=env,
            approved=env.get("BOCA_LIFECYCLE_GO_BINDING_SHA256", ""),
            now=datetime.now(UTC),
            source_run=metadata,
        )
        hosted_token = base64.urlsafe_b64encode(_canonical(hosted)).rstrip(b"=").decode("ascii")
        context._write_private(runner / RUNNER_HOST_CONTEXT, hosted_token + "\n")  # noqa: SLF001
        context._write_private(runner / RUNNER_HOST_APPROVAL, approved + "\n")  # noqa: SLF001
        print(
            "BOCA_GO_APPLY state=APPROVED host=untouched "
            + "prepare_run_id=" + hosted["prepare_run_id"]
            + " attempt=" + hosted["attempt_id"]
        )
        return 0
    except (PreparedGoError, context.ProtectedActionError, OSError, KeyError, ValueError):
        print(
            "BOCA_PROTECTED_GO state=NO_GO host=untouched reason=unreviewed_phase_or_receipt",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
