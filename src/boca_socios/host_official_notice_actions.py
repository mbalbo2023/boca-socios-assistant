"""Protected import coordinates for ONE reviewed public Boca notice artifact.

Runner verification is pure/read-only; the only writer lives inside the
already-reviewed Boca controller image and accepts a bounded ZIP on stdin.
The host workflow must separately attest the exact controller ID, image,
UID, rootless Docker socket and held Boca job flock before invoking it.

No network, Docker, SSH, owner credentials, ticket I/O or new volume here.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shlex
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from boca_socios.events.host_official_notice_import import (
    OfficialImportError,
    ReviewedOfficialArtifactPin,
    _verified_jsonl,
    import_reviewed_official_artifact,
)
from boca_socios.events.official_news_receipt import OFFICIAL_NEWS_URL
from boca_socios.prepared_go_runner import (
    PreparedGoError,
    hash_reviewed_file,
    verify_legacy_prepared_go,
)

_REPOSITORY = "mbalbo2023/boca-socios-assistant"
_REPOSITORY_ID = 1_437_453_367
_SOURCE_WORKFLOW_ID = 407_700_710
_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_CONTAINER_ID = _SHA256
_POSITIVE = re.compile(r"[1-9][0-9]{0,19}\Z")
_GO_SCHEMA = "boca-official-notice-import-go-v1"
_PREPARED_REVIEW_SCHEMA = "boca-official-import-prepared-review-v1"
_COORDINATES_VERSION = "boca-official-notice-import-v1"
_PREPARED_COORDINATES_VERSION = "boca-official-notice-import-prepared-v2"
_MAX_TOKEN = 2048
_MAX_ZIP = 128 * 1024
_DATA = Path("/data")
_HOST_SH = r"""
set -euo pipefail
cid="$1"
image="$2"
token="$3"
[[ "$cid" =~ ^[0-9a-f]{64}$ ]]
[[ "$image" =~ ^ghcr[.]io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}$ ]]
[[ "$token" =~ ^[A-Za-z0-9_-]{1,4096}$ ]]
[[ "$(id -u)" = 10001 ]]
socket=/run/user/10001/docker.sock
lock=/run/user/10001/boca-socios-protected-job.lock
[[ -S "$socket" && ! -L "$socket" && -f "$lock" && ! -L "$lock" ]]
[[ "$(stat -c '%u:%a:%h:%F' "$lock")" = '10001:600:1:regular file' ]]
exec 9<>"$lock"
flock -n -x 9
d=(docker --host unix:///run/user/10001/docker.sock)
options="$(timeout 15s "${d[@]}" info --format '{{json .SecurityOptions}}' 2>/dev/null)"
[[ "$options" == *'name=rootless'* ]]
expected_image_id="$(timeout 15s "${d[@]}" image inspect --format '{{.Id}}' "$image" 2>/dev/null)"
[[ "$expected_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
probe() { timeout 15s "${d[@]}" container inspect --format "$1" "$cid" 2>/dev/null; }
[[ "$(probe '{{.Id}}')" = "$cid" ]]
[[ "$(probe '{{.Name}}')" = /boca-socios-controller-1 ]]
[[ "$(probe '{{index .Config.Labels "com.docker.compose.project"}}')" = boca-socios ]]
[[ "$(probe '{{index .Config.Labels "com.docker.compose.service"}}')" = controller ]]
[[ "$(probe '{{.Config.User}}')" = 10001:10001 ]]
[[ "$(probe '{{.Image}}')" = "$expected_image_id" ]]
[[ "$(probe '{{.State.Running}}')" = true ]]
[[ "$(probe '{{.State.Health.Status}}')" = healthy ]]
[[ "$(probe '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}|{{.Name}}|{{.RW}}{{end}}{{end}}')" = volume\|boca-socios_boca_data\|true ]]
# Only the verified Boca container is executed; no host write, no second SSH.
receipt="$(timeout 30s "${d[@]}" exec -i --user 10001:10001 "$cid" \
  python -m boca_socios.host_official_notice_actions container-import "$token")"
[[ "${#receipt}" -le 360 ]]
[[ "$receipt" =~ ^BOCA_OFFICIAL_IMPORT\ state=(CREATED|UNCHANGED)\ main_sha=[0-9a-f]{40}\ artifact_sha256=[0-9a-f]{64}\ snapshot_sha256=[0-9a-f]{64}\ windows=5\ actionable=false\ data=preserved\ readback=PASS$ ]]
# Recheck the exact instance after the write; drift makes the job NO_GO.
[[ "$(probe '{{.Id}}')" = "$cid" ]]
[[ "$(probe '{{.Image}}')" = "$expected_image_id" ]]
[[ "$(probe '{{.State.Running}}')" = true ]]
printf '%s\n' "$receipt"
""".strip()


class OfficialImportActionError(ValueError):
    """Canonical coordinates, GitHub provenance or authorization is unproven."""


@dataclass(frozen=True)
class OfficialImportCoordinates:
    main_sha: str
    controller_image: str
    controller_release_run_id: str
    controller_id: str
    source_run_id: str
    source_head_sha: str
    artifact_id: str
    artifact_sha256: str
    snapshot_sha256: str
    source_sha256: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        if (
            not all(type(value) is str for value in asdict(self).values())
            or not _SHA40.fullmatch(self.main_sha)
            or not _IMAGE.fullmatch(self.controller_image)
            or not _POSITIVE.fullmatch(self.controller_release_run_id)
            or not _CONTAINER_ID.fullmatch(self.controller_id)
            or not _POSITIVE.fullmatch(self.source_run_id)
            or not _SHA40.fullmatch(self.source_head_sha)
            or not _POSITIVE.fullmatch(self.artifact_id)
            or not all(
                _SHA256.fullmatch(value)
                for value in (
                    self.artifact_sha256,
                    self.snapshot_sha256,
                    self.source_sha256,
                )
            )
            or not 20 <= len(self.observed_at_utc) <= 45
        ):
            raise OfficialImportActionError("official import coordinates malformed")
        _ = self.pin  # validates UTC and exact public article URL

    @property
    def pin(self) -> ReviewedOfficialArtifactPin:
        pin = ReviewedOfficialArtifactPin(
            artifact_url=(
                f"https://github.com/{_REPOSITORY}/actions/runs/"
                f"{self.source_run_id}/artifacts/{self.artifact_id}"
            ),
            artifact_sha256=self.artifact_sha256,
            snapshot_sha256=self.snapshot_sha256,
            source_url=OFFICIAL_NEWS_URL,
            source_sha256=self.source_sha256,
            observed_at_utc=self.observed_at_utc,
        )
        return pin


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _decode_object(data: bytes, *, expected: set[str]) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (UnicodeError, ValueError):
        raise OfficialImportActionError("official import token malformed") from None
    if type(payload) is not dict or set(payload) != expected or _canonical(payload) != data:
        raise OfficialImportActionError("official import token is not canonical")
    return payload


def _nested_dict(obj: dict[str, Any], name: str) -> dict[str, Any]:
    value = obj.get(name)
    return value if type(value) is dict else {}


def encode_coordinates(coords: OfficialImportCoordinates) -> str:
    raw = _canonical({"schema": _COORDINATES_VERSION, **asdict(coords)})
    if len(raw) > _MAX_TOKEN:
        raise OfficialImportActionError("official import token exceeds budget")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_coordinates(token: str) -> OfficialImportCoordinates:
    if (
        type(token) is not str
        or not token
        or len(token) > 2 * _MAX_TOKEN
        or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None
    ):
        raise OfficialImportActionError("official import token not bounded")
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, binascii.Error):
        raise OfficialImportActionError("official import token base64 invalid") from None
    if len(raw) > _MAX_TOKEN or encode_raw(raw) != token:
        raise OfficialImportActionError("official import token encoding not canonical")
    fields = set(OfficialImportCoordinates.__dataclass_fields__)
    obj = _decode_object(raw, expected={"schema", *fields})
    if obj.pop("schema") != _COORDINATES_VERSION or not all(type(v) is str for v in obj.values()):
        raise OfficialImportActionError("official import token schema invalid")
    return OfficialImportCoordinates(**obj)


def encode_prepared_coordinates(coords: OfficialImportCoordinates, *, prepare_run_id: str) -> str:
    """Public v2 coordinates; PREPARE identity is not an independent GO."""
    if type(prepare_run_id) is not str or _POSITIVE.fullmatch(prepare_run_id) is None:
        raise OfficialImportActionError("official PREPARE run identity invalid")
    raw = _canonical(
        {
            "schema": _PREPARED_COORDINATES_VERSION,
            "prepare_run_id": prepare_run_id,
            "coordinates": asdict(coords),
        }
    )
    if not 0 < len(raw) <= _MAX_TOKEN:
        raise OfficialImportActionError("prepared import token exceeds budget")
    return encode_raw(raw)


def decode_prepared_coordinates(token: str) -> tuple[OfficialImportCoordinates, str]:
    if (
        type(token) is not str
        or len(token) > 2 * _MAX_TOKEN
        or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None
    ):
        raise OfficialImportActionError("prepared import token malformed")
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, binascii.Error):
        raise OfficialImportActionError("prepared import base64 invalid") from None
    if not 0 < len(raw) <= _MAX_TOKEN or encode_raw(raw) != token:
        raise OfficialImportActionError("prepared import token not canonical")
    record = _decode_object(raw, expected={"schema", "prepare_run_id", "coordinates"})
    prepare = record["prepare_run_id"]
    coordinates = record["coordinates"]
    if (
        record["schema"] != _PREPARED_COORDINATES_VERSION
        or type(prepare) is not str
        or _POSITIVE.fullmatch(prepare) is None
        or type(coordinates) is not dict
        or set(coordinates) != set(OfficialImportCoordinates.__dataclass_fields__)
        or any(type(value) is not str for value in coordinates.values())
    ):
        raise OfficialImportActionError("prepared import coordinates invalid")
    return OfficialImportCoordinates(**coordinates), prepare


def encode_raw(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def expected_go_sha256(
    coords: OfficialImportCoordinates, *, operation_run_id: str, actor: str
) -> str:
    if not _POSITIVE.fullmatch(operation_run_id) or actor != "mbalbo2023":
        raise OfficialImportActionError("official import GO actor or run invalid")
    return hashlib.sha256(
        _canonical(
            {
                "schema": _GO_SCHEMA,
                "repository": _REPOSITORY,
                "ref": "refs/heads/main",
                "run_attempt": 1,
                "operation_run_id": operation_run_id,
                "actor": actor,
                "destination": "/data/boca_official_notices.jsonl",
                **asdict(coords),
            }
        )
    ).hexdigest()


def official_prepared_context_sha256(
    coords: OfficialImportCoordinates, *, prepare_run_id: str, actor: str
) -> str:
    """Bind the official source/destination to a completed PREPARE identity.

    This is a public, inert, domain-separated hash for the future reviewed
    PREPARE artifact. It is NOT an independent GO: the separate GitHub runner
    must authenticate PREPARE success, artifact bytes, actor/main, exact source,
    Environment GO, replay and freshness before any host call. The existing
    exact-current-run GO check and ZIP import path are deliberately unchanged.
    """
    reviewed = expected_go_sha256(coords, operation_run_id=prepare_run_id, actor=actor)
    return hashlib.sha256(
        _canonical(
            {
                "schema": _PREPARED_REVIEW_SCHEMA,
                "operation": "official-notice-import",
                "prepare_run_id": prepare_run_id,
                "reviewed_authorization_sha256": reviewed,
            }
        )
    ).hexdigest()


def verify_artifact_from_github(
    coords: OfficialImportCoordinates,
    *,
    source_run: dict[str, Any],
    artifact: dict[str, Any],
    archive: bytes,
    independent_go_sha256: str,
    operation_run_id: str,
    actor: str,
) -> str:
    """Legacy current-run GO path unchanged, then authenticate exact source."""
    approved = expected_go_sha256(coords, operation_run_id=operation_run_id, actor=actor)
    if independent_go_sha256 != approved:
        raise OfficialImportActionError("independent official import GO absent or mismatched")
    return _verify_github_reviewed_source(
        coords, source_run=source_run, artifact=artifact, archive=archive
    )


def _verify_github_reviewed_source(
    coords: OfficialImportCoordinates,
    *,
    source_run: dict[str, Any],
    artifact: dict[str, Any],
    archive: bytes,
) -> str:
    """Shared immutable GitHub source validation after the correct GO gate."""
    if (
        type(source_run) is not dict
        or source_run.get("id") != int(coords.source_run_id)
        or source_run.get("workflow_id") != _SOURCE_WORKFLOW_ID
        or source_run.get("event") != "pull_request"
        or source_run.get("conclusion") != "success"
        or source_run.get("head_sha") != coords.source_head_sha
        or _nested_dict(source_run, "repository").get("id") != _REPOSITORY_ID
        or _nested_dict(source_run, "head_repository").get("id") != _REPOSITORY_ID
        or type(artifact) is not dict
        or artifact.get("id") != int(coords.artifact_id)
        or artifact.get("expired") is not False
        or artifact.get("name") != f"boca-official-news-receipt-{coords.source_run_id}"
        or artifact.get("digest") != f"sha256:{coords.artifact_sha256}"
        or artifact.get("size_in_bytes", 0) > _MAX_ZIP
        or artifact.get("size_in_bytes", 0) <= 0
        or _nested_dict(artifact, "workflow_run").get("id") != int(coords.source_run_id)
        or _nested_dict(artifact, "workflow_run").get("repository_id") != _REPOSITORY_ID
        or _nested_dict(artifact, "workflow_run").get("head_repository_id") != _REPOSITORY_ID
        or _nested_dict(artifact, "workflow_run").get("head_sha") != coords.source_head_sha
    ):
        raise OfficialImportActionError("GitHub source run or artifact identity not reviewed")
    try:
        _verified_jsonl(archive, coords.pin)
    except OfficialImportError:
        raise OfficialImportActionError("public source ZIP/JSONL receipt proof failed") from None
    return encode_coordinates(coords)


def _prepared_marker_bytes(coords: OfficialImportCoordinates, prepare_run_id: str) -> bytes:
    context = official_prepared_context_sha256(
        coords, prepare_run_id=prepare_run_id, actor="mbalbo2023"
    )
    return _canonical(
        {
            "schema": "boca-official-import-prepared-use-v1",
            "prepare_run_id": prepare_run_id,
            "reviewed_context_sha256": context,
            "main_sha": coords.main_sha,
            "artifact_sha256": coords.artifact_sha256,
            "destination": "/data/boca_official_notices.jsonl",
        }
    )


def _prepared_marker_name(prepare_run_id: str) -> str:
    if type(prepare_run_id) is not str or _POSITIVE.fullmatch(prepare_run_id) is None:
        raise OfficialImportActionError("official PREPARE identity untrusted")
    return f".boca-official-import-go-{prepare_run_id}.json"


def _prepared_marker_readback(
    directory: int, marker: str, expected: bytes, expected_uid: int
) -> None:
    try:
        fd = os.open(
            marker,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        try:
            before = os.fstat(fd)
            received = os.read(fd, 2049)
            after = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError:
        raise OfficialImportActionError("official PREPARE marker readback unavailable") from None
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != expected_uid
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size != len(expected)
        or received != expected
        or (before.st_dev, before.st_ino, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_mtime_ns)
    ):
        raise OfficialImportActionError("official PREPARE durable marker readback differs")


def _consume_prepared_import_once(
    coords: OfficialImportCoordinates, prepare_run_id: str, *, data_dir: Path
) -> bytes:
    """Write one O_EXCL+fsync receipt inside the already attested Boca /data.

    Caller is the UID10001 image with the host's exact-CID rootless volume
    identity + canonical BocaJobLease already verified by the fixed SSH script.
    The marker is NEVER removed after an ambiguous import/crash.
    """
    marker = _prepared_marker_name(prepare_run_id)
    record = _prepared_marker_bytes(coords, prepare_run_id)
    if not 0 < len(record) <= 2048:
        raise OfficialImportActionError("official PREPARE marker payload unbounded")
    try:
        directory = os.open(data_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise OfficialImportActionError("official PREPARE volume unavailable") from None
    try:
        boundary = os.fstat(directory)
        capacity = os.statvfs(directory)
        if (
            not stat.S_ISDIR(boundary.st_mode)
            or stat.S_IMODE(boundary.st_mode) & 0o022
            or capacity.f_bavail * capacity.f_frsize < 8192
            or capacity.f_favail < 2
        ):
            raise OfficialImportActionError("official PREPARE volume identity/capacity unproven")
        try:
            handle = os.open(
                marker,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
        except FileExistsError:
            raise OfficialImportActionError("official PREPARE GO already consumed") from None
        except OSError:
            raise OfficialImportActionError("official PREPARE marker creation uncertain") from None
        try:
            with os.fdopen(handle, "wb", closefd=False) as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(record)
                output.flush()
                os.fsync(output.fileno())
        except OSError:
            raise OfficialImportActionError("official PREPARE marker outcome uncertain") from None
        finally:
            os.close(handle)
        try:
            os.fsync(directory)
        except OSError:
            raise OfficialImportActionError(
                "official PREPARE directory durability unproven"
            ) from None
        _prepared_marker_readback(directory, marker, record, boundary.st_uid)
    finally:
        os.close(directory)
    return record


def _verify_prepared_import_marker(
    coords: OfficialImportCoordinates, prepare_run_id: str, *, data_dir: Path
) -> None:
    marker = _prepared_marker_name(prepare_run_id)
    try:
        directory = os.open(data_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            boundary = os.fstat(directory)
            _prepared_marker_readback(
                directory, marker, _prepared_marker_bytes(coords, prepare_run_id), boundary.st_uid
            )
        finally:
            os.close(directory)
    except OSError:
        raise OfficialImportActionError(
            "official PREPARE post-import readback unavailable"
        ) from None


def import_from_container_stdin(
    coords: OfficialImportCoordinates,
    archive: bytes,
    *,
    data_dir: Path = _DATA,
    prepare_run_id: str | None = None,
) -> str:
    """Create/replay one non-actionable snapshot with optional single-use GO.

    PREPARE mode requires the fixed host shell to attest Boca rootless/volume,
    controller exact-ID, held canonical flock and image BEFORE this UID10001
    container call. ZIP bytes are preverified BEFORE durable GO consumption.
    Any later crash leaves the marker quarantined; no automatic retry.
    """
    if os.geteuid() != 10_001 or data_dir != _DATA:
        raise OfficialImportActionError("official import requires Boca container UID and /data")
    if prepare_run_id is not None:
        try:
            _verified_jsonl(archive, coords.pin)
        except OfficialImportError:
            raise OfficialImportActionError("official PREPARE source invalid before use") from None
        _consume_prepared_import_once(coords, prepare_run_id, data_dir=data_dir)
    try:
        result = import_reviewed_official_artifact(
            data_dir, artifact_zip=archive, reviewed_pin=coords.pin
        )
    except OfficialImportError:
        raise OfficialImportActionError("Boca data import or readback failed") from None
    if result.outcome not in ("CREATED", "UNCHANGED") or result.actionable is not False:
        raise OfficialImportActionError("official notice import not non-actionable")
    if prepare_run_id is not None:
        _verify_prepared_import_marker(coords, prepare_run_id, data_dir=data_dir)
    return (
        "BOCA_OFFICIAL_IMPORT state="
        f"{result.outcome} main_sha={coords.main_sha} "
        f"artifact_sha256={coords.artifact_sha256} "
        f"snapshot_sha256={coords.snapshot_sha256} "
        "windows=5 actionable=false data=preserved readback=PASS"
    )


def build_single_ssh_host_command(
    coords: OfficialImportCoordinates, token: str, *, prepare_run_id: str | None = None
) -> str:
    """Fixed host Bash: only the reviewed Boca CID, rootless lease and volume.

    The default v1 operation is unchanged; PREPARE v2 is separate and opt-in
    after the runner's independent receipt/environment GO review. No token,
    credential or site operation enters the shell.
    """
    if decode_coordinates(token) != coords:
        raise OfficialImportActionError("official import token/CID source mismatch")
    host_script = _HOST_SH
    if prepare_run_id is not None:
        token = encode_prepared_coordinates(coords, prepare_run_id=prepare_run_id)
        previous = 'container-import "$token"'
        if host_script.count(previous) != 1:
            raise OfficialImportActionError("official PREPARE fixed host route unavailable")
        host_script = host_script.replace(previous, 'container-import-prepared "$token"')
    return shlex.join(
        ("bash", "-c", host_script, "--", coords.controller_id, coords.controller_image, token)
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 100_000:
        raise OfficialImportActionError("GitHub artifact metadata file unavailable")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError, OSError):
        raise OfficialImportActionError("GitHub artifact metadata malformed") from None
    if type(obj) is not dict:
        raise OfficialImportActionError("GitHub artifact metadata invalid")
    return obj


def _coords_from_env() -> OfficialImportCoordinates:
    env = os.environ
    return OfficialImportCoordinates(
        main_sha=env.get("BOCA_SOURCE_SHA", ""),
        controller_image=env.get("BOCA_IMAGE_REF", ""),
        controller_release_run_id=env.get("BOCA_RELEASE_RUN_ID", ""),
        controller_id=env.get("BOCA_OFFICIAL_CONTROLLER_ID", ""),
        source_run_id=env.get("BOCA_OFFICIAL_NEWS_RUN_ID", ""),
        source_head_sha=env.get("BOCA_OFFICIAL_NEWS_SOURCE_SHA", ""),
        artifact_id=env.get("BOCA_OFFICIAL_NEWS_ARTIFACT_ID", ""),
        artifact_sha256=env.get("BOCA_OFFICIAL_NEWS_ZIP_SHA256", ""),
        snapshot_sha256=env.get("BOCA_OFFICIAL_NEWS_JSONL_SHA256", ""),
        source_sha256=env.get("BOCA_OFFICIAL_NEWS_HTML_SHA256", ""),
        observed_at_utc=env.get("BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC", ""),
    )


def _load_token(path: Path) -> str:
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 4096:
        raise OfficialImportActionError("official import runner token file missing")
    try:
        return path.read_text(encoding="ascii").strip()
    except (UnicodeError, OSError):
        raise OfficialImportActionError("official import runner token unreadable") from None


def _private_write_once(path: Path, data: bytes) -> None:
    if not path.is_absolute() or not path.parent.is_dir() or len(data) > 4096:
        raise OfficialImportActionError("official import token destination invalid")
    fd = -1
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        raise OfficialImportActionError("official import token write failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _prepared_official_runner_proof(
    coords: OfficialImportCoordinates, *, archive_sha256: str
) -> str:
    """Verify independent GO_B and rehash exact official release artifacts."""
    env = os.environ
    runner = Path(env.get("RUNNER_TEMP", ""))
    try:
        proof = verify_legacy_prepared_go(
            operation="official-notice-import",
            expected_public_context_sha256=lambda prepare_id: official_prepared_context_sha256(
                coords, prepare_run_id=prepare_id, actor=env.get("GITHUB_ACTOR", "")
            ),
            source_sha=coords.main_sha,
            release_run_id=coords.controller_release_run_id,
            release_manifest_sha256=hash_reviewed_file(
                runner / "boca-release-manifest/boca-release-manifest.json"
            ),
            browser_manifest_sha256=hash_reviewed_file(
                runner / "boca-browser-release-manifest/boca-browser-release-manifest.json"
            ),
            bundle_sha256=archive_sha256,
            owner_subject=env.get("BOCA_BETA_OWNER_SUBJECT", ""),
            environ=env,
        )
    except (PreparedGoError, OfficialImportActionError) as exc:
        raise OfficialImportActionError(
            "official prepared runner source, release or GO_B unavailable"
        ) from exc
    return proof.prepare_run_id


def _prepared_reviewed_source_zip(path: Path) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise OfficialImportActionError("prepared official ZIP path unavailable")
    try:
        if not 0 < path.stat().st_size <= _MAX_ZIP:
            raise OfficialImportActionError("prepared official ZIP size unsafe")
        raw = path.read_bytes()
    except OSError:
        raise OfficialImportActionError("prepared official ZIP unreadable") from None
    if not 0 < len(raw) <= _MAX_ZIP:
        raise OfficialImportActionError("prepared official ZIP length differs")
    return raw


def _runner_preflight_prepared(argv: list[str]) -> int:
    """No host action; v2 PREPARE proof precedes GitHub artifact parsing."""
    if len(argv) != 6:
        raise OfficialImportActionError("official prepared preflight arguments incomplete")
    coords = _coords_from_env()
    archive = _prepared_reviewed_source_zip(Path(argv[4]))
    _prepared_official_runner_proof(coords, archive_sha256=hashlib.sha256(archive).hexdigest())
    token = _verify_github_reviewed_source(
        coords,
        source_run=_load_json(Path(argv[2])),
        artifact=_load_json(Path(argv[3])),
        archive=archive,
    )
    _private_write_once(Path(argv[5]), (token + "\n").encode("ascii"))
    print("BOCA_OFFICIAL_IMPORT_PREPARED_PREFLIGHT state=READY host=untouched")
    return 0


def _runner_host_command_prepared(argv: list[str]) -> int:
    """Reverify GO_B source pins before printing fixed Boca-only SSH command."""
    if len(argv) != 4:
        raise OfficialImportActionError("official prepared host command arguments invalid")
    coords = _coords_from_env()
    token = _load_token(Path(argv[2]))
    archive = _prepared_reviewed_source_zip(Path(argv[3]))
    prepare_run_id = _prepared_official_runner_proof(
        coords, archive_sha256=hashlib.sha256(archive).hexdigest()
    )
    print(build_single_ssh_host_command(coords, token, prepare_run_id=prepare_run_id))
    return 0


def _runner_preflight(argv: list[str]) -> int:
    if len(argv) != 6:
        raise OfficialImportActionError("official import runner arguments incomplete")
    coords = _coords_from_env()
    actor = os.environ.get("GITHUB_ACTOR", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    approved = os.environ.get("BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256", "")
    if approved != expected_go_sha256(coords, operation_run_id=run_id, actor=actor):
        raise OfficialImportActionError("official import independent GO invalid")
    zip_path = Path(argv[4])
    if not zip_path.is_absolute() or zip_path.stat().st_size > _MAX_ZIP:
        raise OfficialImportActionError("official import ZIP path/size invalid")
    try:
        archive = zip_path.read_bytes()
    except OSError:
        raise OfficialImportActionError("official import ZIP unavailable") from None
    token = verify_artifact_from_github(
        coords,
        source_run=_load_json(Path(argv[2])),
        artifact=_load_json(Path(argv[3])),
        archive=archive,
        independent_go_sha256=approved,
        operation_run_id=run_id,
        actor=actor,
    )
    _private_write_once(Path(argv[5]), (token + "\n").encode("ascii"))
    print("BOCA_OFFICIAL_IMPORT_PREFLIGHT state=READY host=untouched")
    return 0


def _runner_host_command(argv: list[str]) -> int:
    if len(argv) != 3:
        raise OfficialImportActionError("official import host command args invalid")
    coords = _coords_from_env()
    token = _load_token(Path(argv[2]))
    print(build_single_ssh_host_command(coords, token))
    return 0


def _assert_runner_host_receipt(argv: list[str]) -> int:
    if len(argv) != 3:
        raise OfficialImportActionError("official import host receipt args invalid")
    if (
        os.environ.get("BOCA_OFFICIAL_IMPORT_PREFLIGHT") != "success"
        or os.environ.get("BOCA_OFFICIAL_IMPORT_HOST_APPLY") != "success"
    ):
        raise OfficialImportActionError("official import go or host outcome not positive")
    coords = _coords_from_env()
    path = Path(argv[2])
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 360:
        raise OfficialImportActionError("official import host terminal receipt absent")
    try:
        receipt = path.read_text(encoding="ascii")
    except (UnicodeError, OSError):
        raise OfficialImportActionError(
            "official import host terminal receipt unreadable"
        ) from None
    for state in ("CREATED", "UNCHANGED"):
        expected = (
            f"BOCA_OFFICIAL_IMPORT state={state} main_sha={coords.main_sha} "
            f"artifact_sha256={coords.artifact_sha256} "
            f"snapshot_sha256={coords.snapshot_sha256} "
            "windows=5 actionable=false data=preserved readback=PASS\n"
        )
        if receipt == expected:
            print("BOCA_OFFICIAL_IMPORT_ASSERT state=ACCEPTED receipt=EXACT source=UNVERIFIED")
            return 0
    raise OfficialImportActionError("official import terminal receipt identity mismatch")


def _run_cli(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] in ("container-import", "container-import-prepared"):
        prepared = argv[1] == "container-import-prepared"
        if prepared:
            coords, prepare_run_id = decode_prepared_coordinates(argv[2])
        else:
            coords = decode_coordinates(argv[2])
            prepare_run_id = None
        archive = sys.stdin.buffer.read(_MAX_ZIP + 1)
        if not 0 < len(archive) <= _MAX_ZIP:
            raise OfficialImportActionError("official import archive size invalid")
        print(import_from_container_stdin(coords, archive, prepare_run_id=prepare_run_id))
        return 0
    if len(argv) >= 2 and argv[1] == "runner-preflight-prepared":
        return _runner_preflight_prepared(argv)
    if len(argv) >= 2 and argv[1] == "runner-host-command-prepared":
        return _runner_host_command_prepared(argv)
    if len(argv) >= 2 and argv[1] == "runner-preflight":
        return _runner_preflight(argv)
    if len(argv) >= 2 and argv[1] == "runner-host-command":
        return _runner_host_command(argv)
    if len(argv) >= 2 and argv[1] == "assert-host-receipt":
        return _assert_runner_host_receipt(argv)
    raise OfficialImportActionError("official import CLI mode not permitted")


if __name__ == "__main__":
    try:
        raise SystemExit(_run_cli(sys.argv))
    except OfficialImportActionError:
        print("BOCA_OFFICIAL_IMPORT state=NO_GO reason=import_contract_unverified", file=sys.stderr)
        raise SystemExit(3) from None
