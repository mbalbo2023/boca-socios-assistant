"""Boca GO_B PREPARE/APPLY dispatch evidence; no authorization from input alone.

GitHub Actions alone downloads reviewed immutable artifacts. This module never
connects to the host, alters Docker/SQLite, or reads credentials. All host
commands remain in the existing protected workflow after independent GO_B.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from boca_socios.events.host_official_notice_import import _read_exact_artifact_parts
from boca_socios.host_official_notice_actions import (
    OfficialImportCoordinates,
    _verify_github_reviewed_source,
    official_prepared_context_sha256,
)
from boca_socios.prepared_go_runner import GO_DOMAINS, RECEIPT_KEYS, VERSION, hash_reviewed_file

_REPO = "mbalbo2023/boca-socios-assistant"
_OWNER = "mbalbo2023"
_IMAGE_WORKFLOW = 400106577
_OFFICIAL_WORKFLOW = 407700710
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")
_OPS = frozenset({"cutover-a-apply", "official-notice-import"})
_ARTIFACT = "boca-protected-legacy-go-prepare"
_COORDS_VERSION = "boca-legacy-prepared-coordinates-v1"
_COORDS_FIELDS = frozenset(
    {
        "version",
        "operation",
        "source_sha",
        "image_ref",
        "browser_image_ref",
        "release_run_id",
        "legacy_source_sha",
        "legacy_image_ref",
        "legacy_release_run_id",
        "legacy_controller_id",
        "official_controller_id",
        "official_news_run_id",
        "official_news_source_sha",
        "official_news_artifact_id",
        "official_news_zip_sha256",
        "official_news_jsonl_sha256",
        "official_news_html_sha256",
        "official_news_observed_at_utc",
    }
)
_INVENTORY_BASE = frozenset(
    {
        "version",
        "kind",
        "observe_run_id",
        "target_source_sha",
        "target_release_run_id",
        "legacy_controller_id",
        "legacy_source_sha",
        "legacy_image_ref",
        "legacy_image_id",
        "legacy_compose_config_hash",
        "compose_project",
        "compose_service",
        "port",
        "data_volume",
        "key_volume",
        "owner_volume",
        "controller_health",
        "observed_at_utc",
    }
)


class LegacyGoDispatchError(ValueError):
    """An independently reviewed GO_B coordinate or receipt is not proven."""


def _require(value: bool, reason: str) -> None:
    if not value:
        raise LegacyGoDispatchError(reason)


def _canonical(record: Any) -> bytes:
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in out, "duplicate reviewed JSON key")
        out[key] = value
    return out


def _strict_json(data: bytes, *, maximum: int = 100_000) -> dict[str, Any]:
    _require(0 < len(data) <= maximum, "reviewed JSON length untrusted")
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
    except (UnicodeError, ValueError) as exc:
        raise LegacyGoDispatchError("reviewed JSON malformed") from exc
    _require(type(parsed) is dict, "reviewed JSON must be object")
    return parsed


def _file(path: Path, *, maximum: int = 100_000, canonical: bool = False) -> bytes:
    _require(path.is_absolute() and not path.is_symlink(), "reviewed path untrusted")
    try:
        before = path.stat(follow_symlinks=False)
        _require(
            stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum,
            "reviewed file type or bounds untrusted",
        )
        raw = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise LegacyGoDispatchError("reviewed file unavailable") from exc
    _require(
        len(raw) == before.st_size
        and (before.st_dev, before.st_ino, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_mtime_ns),
        "reviewed file bytes changed during read",
    )
    if canonical:
        _require(_canonical(_strict_json(raw, maximum=maximum)) == raw, "JSON not canonical")
    return raw


def _write_once(path: Path, body: bytes, *, mode: int = 0o600) -> None:
    _require(
        path.is_absolute()
        and not path.is_symlink()
        and path.parent.is_dir()
        and 0 < len(body) <= 12_000,
        "private stage path invalid",
    )
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise LegacyGoDispatchError("reviewed stage must be created exactly once") from exc


def _env_file(environ: Mapping[str, str], pins: dict[str, str]) -> None:
    path = Path(environ.get("GITHUB_ENV", ""))
    _require(path.is_absolute() and path.parent.is_dir(), "GitHub env missing")
    valid = {
        "BOCA_SOURCE_SHA",
        "BOCA_IMAGE_REF",
        "BOCA_BROWSER_IMAGE_REF",
        "BOCA_RELEASE_RUN_ID",
        "BOCA_LEGACY_SOURCE_SHA",
        "BOCA_LEGACY_IMAGE_REF",
        "BOCA_LEGACY_RELEASE_RUN_ID",
        "BOCA_LEGACY_CONTROLLER_ID",
        "BOCA_OFFICIAL_CONTROLLER_ID",
        "BOCA_OFFICIAL_NEWS_RUN_ID",
        "BOCA_OFFICIAL_NEWS_SOURCE_SHA",
        "BOCA_OFFICIAL_NEWS_ARTIFACT_ID",
        "BOCA_OFFICIAL_NEWS_ZIP_SHA256",
        "BOCA_OFFICIAL_NEWS_JSONL_SHA256",
        "BOCA_OFFICIAL_NEWS_HTML_SHA256",
        "BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC",
    }
    _require(set(pins) <= valid, "unapproved environment key")
    _require(
        all(type(v) is str and v and "\n" not in v and "\r" not in v for v in pins.values()),
        "untrusted environment value",
    )
    # GITHUB_ENV is runner-created; only pinned, non-secret reviewed coordinates.
    with path.open("a", encoding="ascii") as stream:
        for key, value in pins.items():
            stream.write(f"{key}={value}\n")


def _main(environ: Mapping[str, str]) -> None:
    _require(
        environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and environ.get("GITHUB_REPOSITORY") == _REPO
        and environ.get("GITHUB_ACTOR") == _OWNER
        and environ.get("GITHUB_REF") == "refs/heads/main"
        and environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and environ.get("BOCA_OPERATION") in _OPS
        and _SHA.fullmatch(environ.get("GITHUB_SHA", "")) is not None,
        "Actions main/owner/operation context untrusted",
    )
    _require(_RUN.fullmatch(environ.get("GITHUB_RUN_ID", "")) is not None, "run ID invalid")


def _positive(run_id: str) -> str:
    _require(type(run_id) is str and _RUN.fullmatch(run_id) is not None, "run ID untrusted")
    return run_id


def _sha(value: str, length: int = 64) -> str:
    pattern = _HEX if length == 64 else _SHA
    _require(type(value) is str and pattern.fullmatch(value) is not None, "SHA invalid")
    return value


def _pins_from_coords(coords: dict[str, str]) -> dict[str, str]:
    return {
        "BOCA_" + key.upper(): value
        for key, value in coords.items()
        if key not in {"version", "operation"} and value
    }


def _env_coords(environ: Mapping[str, str]) -> dict[str, str]:
    _main(environ)
    fields = {"version": _COORDS_VERSION, "operation": environ["BOCA_OPERATION"]}
    for field in sorted(_COORDS_FIELDS - {"version", "operation"}):
        fields[field] = environ.get("BOCA_" + field.upper(), "")
    return _validate_coords(fields)


def _validate_coords(coords: dict[str, Any]) -> dict[str, str]:
    _require(
        type(coords) is dict
        and set(coords) == _COORDS_FIELDS
        and all(type(value) is str for value in coords.values())
        and coords["version"] == _COORDS_VERSION
        and coords["operation"] in _OPS
        and _SHA.fullmatch(coords["source_sha"]) is not None
        and _CONTROLLER.fullmatch(coords["image_ref"]) is not None
        and _WORKER.fullmatch(coords["browser_image_ref"]) is not None
        and _RUN.fullmatch(coords["release_run_id"]) is not None,
        "prepared public coordinates schema/current release invalid",
    )
    if coords["operation"] == "cutover-a-apply":
        for key, pattern in (
            ("legacy_source_sha", _SHA),
            ("legacy_image_ref", _CONTROLLER),
            ("legacy_release_run_id", _RUN),
            ("legacy_controller_id", _HEX),
        ):
            _require(pattern.fullmatch(coords[key]) is not None, f"cutover {key} untrusted")
        _require(
            coords["legacy_source_sha"] != coords["source_sha"]
            and coords["legacy_image_ref"] != coords["image_ref"],
            "legacy and target controller must differ",
        )
        _require(
            all(coords[key] == "" for key in _COORDS_FIELDS if key.startswith("official_")),
            "cutover cannot carry official coordinates",
        )
    else:
        for key, pattern in (
            ("official_controller_id", _HEX),
            ("official_news_run_id", _RUN),
            ("official_news_source_sha", _SHA),
            ("official_news_artifact_id", _RUN),
            ("official_news_zip_sha256", _HEX),
            ("official_news_jsonl_sha256", _HEX),
            ("official_news_html_sha256", _HEX),
        ):
            _require(pattern.fullmatch(coords[key]) is not None, f"official {key} untrusted")
        _require(
            20 <= len(coords["official_news_observed_at_utc"]) <= 45
            and all(coords[key] == "" for key in _COORDS_FIELDS if key.startswith("legacy_")),
            "official/source and legacy coordinates mixed",
        )
        _ = _official_coords(coords)
    return coords


def _official_coords(coords: dict[str, str]) -> OfficialImportCoordinates:
    return OfficialImportCoordinates(
        main_sha=coords["source_sha"],
        controller_image=coords["image_ref"],
        controller_release_run_id=coords["release_run_id"],
        controller_id=coords["official_controller_id"],
        source_run_id=coords["official_news_run_id"],
        source_head_sha=coords["official_news_source_sha"],
        artifact_id=coords["official_news_artifact_id"],
        artifact_sha256=coords["official_news_zip_sha256"],
        snapshot_sha256=coords["official_news_jsonl_sha256"],
        source_sha256=coords["official_news_html_sha256"],
        observed_at_utc=coords["official_news_observed_at_utc"],
    )


def select_release_run(
    listing: dict[str, Any], *, source_sha: str, expected_image: str = ""
) -> str:
    """Choose unique genuine successful main image release, never newest guess."""
    _sha(source_sha, 40)
    _require(type(listing.get("workflow_runs")) is list, "GitHub run listing malformed")
    _require(
        type(listing.get("total_count")) is int and listing["total_count"] <= 100,
        "GitHub release list requires explicit complete pagination",
    )
    matches = [
        run
        for run in listing["workflow_runs"]
        if type(run) is dict
        and run.get("workflow_id") == _IMAGE_WORKFLOW
        and run.get("event") == "workflow_dispatch"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("run_attempt") == 1
        and run.get("head_branch") == "main"
        and run.get("head_sha") == source_sha
        and type(run.get("actor")) is dict
        and run["actor"].get("login") == _OWNER
    ]
    _require(
        len(matches) == 1,
        "image release source has no unique reviewed successful Actions run",
    )
    run = matches[0]
    _require(type(run.get("id")) is int, "release run identifier malformed")
    # The artifact digest is independently verified in the following command.
    _require(
        not expected_image or _CONTROLLER.fullmatch(expected_image) is not None, "image invalid"
    )
    return _positive(str(run["id"]))


def validate_release_manifest(
    controller: dict[str, Any],
    browser: dict[str, Any],
    *,
    source_sha: str,
    release_id: str,
    observed_image: str = "",
) -> dict[str, str]:
    _sha(source_sha, 40)
    _positive(release_id)
    _require(
        set(controller) == {"image_ref", "source_sha", "release_run_id"}
        and set(browser) == {"source_sha", "run_id", "controller_digest", "browser_digest"}
        and controller["source_sha"] == browser["source_sha"] == source_sha
        and str(controller["release_run_id"]) == str(browser["run_id"]) == release_id
        and controller["image_ref"] == browser["controller_digest"]
        and _CONTROLLER.fullmatch(controller["image_ref"]) is not None
        and _WORKER.fullmatch(browser["browser_digest"]) is not None
        and (not observed_image or observed_image == controller["image_ref"]),
        "release controller/browser same-run manifest or observed image mismatch",
    )
    return {
        "BOCA_SOURCE_SHA": source_sha,
        "BOCA_RELEASE_RUN_ID": release_id,
        "BOCA_IMAGE_REF": controller["image_ref"],
        "BOCA_BROWSER_IMAGE_REF": browser["browser_digest"],
    }


def observer_request(environ: Mapping[str, str], *, operation: str) -> str:
    """Runner-only six-key request. Never a host GO or user-supplied token."""
    _main(environ)
    _require(operation == environ["BOCA_OPERATION"], "observer operation differs")
    _require(operation in _OPS, "observer kind unsupported")
    source = _sha(environ.get("BOCA_SOURCE_SHA", ""), 40)
    controller = environ.get("BOCA_IMAGE_REF", "")
    browser = environ.get("BOCA_BROWSER_IMAGE_REF", "")
    release = _positive(environ.get("BOCA_RELEASE_RUN_ID", ""))
    _require(
        _CONTROLLER.fullmatch(controller) is not None and _WORKER.fullmatch(browser) is not None,
        "observer target image refs unreviewed",
    )
    kind = "cutover" if operation == "cutover-a-apply" else "official"
    payload = {
        "version": f"boca-{kind}-inventory-observe-v1",
        "target_source_sha": source,
        "target_controller_image": controller,
        "target_browser_image": browser,
        "target_release_run_id": release,
        "observe_run_id": environ["GITHUB_RUN_ID"],
    }
    raw = _canonical(payload)
    _require(len(raw) <= 2048, "observer request exceeds bound")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def validate_host_inventory(raw: bytes, *, environ: Mapping[str, str]) -> dict[str, str]:
    """Consume actual single-line host stdout; no guessed SHA/CID or releases."""
    _main(environ)
    _require(
        raw.endswith(b"\n") and raw.count(b"\n") == 1 and len(raw) <= 4096,
        "host inventory must be exactly one bounded line",
    )
    doc = _strict_json(raw[:-1], maximum=4096)
    _require(
        _canonical(doc) == raw[:-1] and all(type(value) is str for value in doc.values()),
        "host inventory must be canonical public strings",
    )
    expected_kind = "cutover" if environ["BOCA_OPERATION"] == "cutover-a-apply" else "official"
    _require(
        doc.get("version") == f"boca-{expected_kind}-inventory-observe-v1"
        and doc.get("kind") == f"{expected_kind}-inventory"
        and doc.get("observe_run_id") == environ["GITHUB_RUN_ID"],
        "observed inventory version/kind/run mismatch",
    )
    if expected_kind == "cutover":
        _require(
            set(doc) == _INVENTORY_BASE
            and doc.get("target_source_sha") == environ.get("BOCA_SOURCE_SHA")
            and doc.get("target_release_run_id") == environ.get("BOCA_RELEASE_RUN_ID")
            and doc.get("compose_project") == "boca-socios"
            and doc.get("compose_service") == "controller"
            and doc.get("port") == "127.0.0.1:8443"
            and doc.get("controller_health") == "healthy"
            and doc.get("data_volume") == "boca-socios_boca_data"
            and doc.get("key_volume") == "boca-socios_boca_key"
            and doc.get("owner_volume") == "boca-socios_boca_owner"
            and _HEX.fullmatch(doc.get("legacy_controller_id", "")) is not None
            and _SHA.fullmatch(doc.get("legacy_source_sha", "")) is not None
            and _CONTROLLER.fullmatch(doc.get("legacy_image_ref", "")) is not None
            and re.fullmatch(r"sha256:[0-9a-f]{64}", doc.get("legacy_image_id", "")) is not None
            and _HEX.fullmatch(doc.get("legacy_compose_config_hash", "")) is not None
            and doc["legacy_source_sha"] != environ["BOCA_SOURCE_SHA"]
            and doc["legacy_image_ref"] != environ["BOCA_IMAGE_REF"],
            "real legacy singleton/identity does not match original Boca topology",
        )
    else:
        required = {
            "version",
            "kind",
            "observe_run_id",
            "source_sha",
            "release_run_id",
            "controller_id",
            "controller_image",
            "worker_id",
            "worker_image",
            "browser_attempt",
            "controller_config_hash",
            "worker_config_hash",
            "port",
            "data_volume",
            "observed_at_utc",
        }
        sender = {"sender_id", "sender_config_hash", "sender_attempt_id", "sender_state"}
        _require(
            set(doc) in (required, required | sender)
            and doc.get("source_sha") == environ.get("BOCA_SOURCE_SHA")
            and doc.get("release_run_id") == environ.get("BOCA_RELEASE_RUN_ID")
            and doc.get("controller_image") == environ.get("BOCA_IMAGE_REF")
            and doc.get("worker_image") == environ.get("BOCA_BROWSER_IMAGE_REF")
            and doc.get("port") == "127.0.0.1:8443"
            and doc.get("data_volume") == "boca-socios_boca_data"
            and _HEX.fullmatch(doc.get("controller_id", "")) is not None
            and _HEX.fullmatch(doc.get("worker_id", "")) is not None
            and _HEX.fullmatch(doc.get("controller_config_hash", "")) is not None
            and _HEX.fullmatch(doc.get("worker_config_hash", "")) is not None
            and _RUN.fullmatch(doc.get("browser_attempt", "")) is not None,
            "official running controller+worker immutable topology unproven",
        )
        if set(doc) == required | sender:
            _require(
                _HEX.fullmatch(doc["sender_id"]) is not None
                and doc["sender_state"] in ("on", "off")
                and _RUN.fullmatch(doc["sender_attempt_id"]) is not None
                and _HEX.fullmatch(doc["sender_config_hash"]) is not None,
                "unexpected sender coordinates",
            )
    _require(
        re.fullmatch(
            r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z",
            doc.get("observed_at_utc", ""),
        )
        is not None,
        "observation UTC clock malformed",
    )
    return doc


def parse_official_source(
    *,
    run: dict[str, Any],
    artifact: dict[str, Any],
    archive: bytes,
    controller_id: str,
    environ: Mapping[str, str],
) -> dict[str, str]:
    """Bind actual public article receipt and exact ZIP to reviewed GH source."""
    _main(environ)
    _require(environ["BOCA_OPERATION"] == "official-notice-import", "wrong source operation")
    _sha(controller_id)
    source_id = _positive(environ.get("BOCA_OFFICIAL_NEWS_RUN_ID", ""))
    _require(
        type(run.get("id")) is int
        and str(run["id"]) == source_id
        and run.get("workflow_id") == _OFFICIAL_WORKFLOW
        and run.get("event") == "pull_request"
        and run.get("conclusion") == "success"
        and _SHA.fullmatch(run.get("head_sha", "")) is not None,
        "official chosen short run does not authenticate a successful PR source",
    )
    _require(
        type(artifact.get("id")) is int
        and type(artifact.get("digest")) is str
        and artifact["digest"].startswith("sha256:")
        and 0 < len(archive) <= 128 * 1024,
        "official archived artifact provenance unavailable",
    )
    _require(
        artifact.get("name") == f"boca-official-news-receipt-{source_id}"
        and artifact.get("digest") == f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "official artifact does not match the short reviewed run",
    )
    try:
        receipt, catalog = _read_exact_artifact_parts(archive)
    except (ValueError, zipfile.BadZipFile, OSError) as exc:
        raise LegacyGoDispatchError("official artifact receipt invalid") from exc
    _require(
        type(receipt.get("source_sha256")) is str
        and _HEX.fullmatch(receipt["source_sha256"]) is not None
        and type(receipt.get("observed_at_utc")) is str,
        "official artifact source/time absent",
    )
    coords = OfficialImportCoordinates(
        main_sha=environ["BOCA_SOURCE_SHA"],
        controller_image=environ["BOCA_IMAGE_REF"],
        controller_release_run_id=environ["BOCA_RELEASE_RUN_ID"],
        controller_id=controller_id,
        source_run_id=source_id,
        source_head_sha=run["head_sha"],
        artifact_id=str(artifact["id"]),
        artifact_sha256=hashlib.sha256(archive).hexdigest(),
        snapshot_sha256=hashlib.sha256(catalog).hexdigest(),
        source_sha256=receipt["source_sha256"],
        observed_at_utc=receipt["observed_at_utc"],
    )
    _verify_github_reviewed_source(coords, source_run=run, artifact=artifact, archive=archive)
    return {
        "BOCA_OFFICIAL_CONTROLLER_ID": controller_id,
        "BOCA_OFFICIAL_NEWS_RUN_ID": source_id,
        "BOCA_OFFICIAL_NEWS_SOURCE_SHA": run["head_sha"],
        "BOCA_OFFICIAL_NEWS_ARTIFACT_ID": str(artifact["id"]),
        "BOCA_OFFICIAL_NEWS_ZIP_SHA256": coords.artifact_sha256,
        "BOCA_OFFICIAL_NEWS_JSONL_SHA256": coords.snapshot_sha256,
        "BOCA_OFFICIAL_NEWS_HTML_SHA256": coords.source_sha256,
        "BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC": coords.observed_at_utc,
    }


def _reviewed_sha(path: Path) -> str:
    return hash_reviewed_file(path, max_bytes=2_500_000)


def _review_receipt_context(coords: dict[str, str], prepare_id: str) -> str:
    if coords["operation"] == "cutover-a-apply":
        from check_cutover_a_go import actions_request, cutover_prepared_context_sha256

        return cutover_prepared_context_sha256(
            actions_request(os.environ), prepare_run_id=prepare_id
        )
    return official_prepared_context_sha256(
        _official_coords(coords), prepare_run_id=prepare_id, actor=os.environ["GITHUB_ACTOR"]
    )


def _review_file_paths(environ: Mapping[str, str]) -> tuple[Path, Path, Path]:
    runner = Path(environ.get("RUNNER_TEMP", ""))
    _require(runner.is_absolute() and runner.is_dir(), "runner temporary root unavailable")
    release = runner / "boca-release-manifest" / "boca-release-manifest.json"
    browser = runner / "boca-browser-release-manifest" / "boca-browser-release-manifest.json"
    bundle = (
        runner / "boca-cutover-a-review.pyz"
        if environ["BOCA_OPERATION"] == "cutover-a-apply"
        else runner / "boca-official-artifact.zip"
    )
    return release, browser, bundle


def create_prepare_receipt(
    coords: dict[str, str], *, environ: Mapping[str, str], now: datetime
) -> tuple[dict[str, str], str]:
    _main(environ)
    _require(now.tzinfo is not None, "UTC review clock not known")
    _require(
        coords == _env_coords(environ),
        "PREPARE coordinates may not differ from current reviewed pins",
    )
    release, browser, bundle = _review_file_paths(environ)
    _require(environ.get("BOCA_BETA_OWNER_SUBJECT", "") != "", "owner identity not provisioned")
    issued = now.astimezone(UTC).replace(microsecond=0)
    result = {
        "version": VERSION,
        "operation": coords["operation"],
        "repository": _REPO,
        "actor": _OWNER,
        "ref": "refs/heads/main",
        "source_sha": coords["source_sha"],
        "release_run_id": coords["release_run_id"],
        "prepare_run_id": environ["GITHUB_RUN_ID"],
        "prepare_attempt": "1",
        "prepared_at_utc": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until_utc": (issued + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public_context_sha256": _review_receipt_context(coords, environ["GITHUB_RUN_ID"]),
        "release_manifest_sha256": _reviewed_sha(release),
        "browser_manifest_sha256": _reviewed_sha(browser),
        "bundle_sha256": _reviewed_sha(bundle),
        "owner_subject_sha256": hashlib.sha256(
            environ["BOCA_BETA_OWNER_SUBJECT"].encode("utf-8")
        ).hexdigest(),
    }
    _require(
        set(result) == RECEIPT_KEYS and all(type(v) is str for v in result.values()),
        "prepare receipt incomplete",
    )
    approval = hashlib.sha256(GO_DOMAINS[coords["operation"]] + _canonical(result)).hexdigest()
    return result, approval


def validate_prepared_metadata(
    run: dict[str, Any], *, prepare_id: str, environ: Mapping[str, str]
) -> None:
    _positive(prepare_id)
    _require(
        type(run.get("id")) is int
        and run["id"] == int(prepare_id)
        and run.get("event") == "workflow_dispatch"
        and run.get("run_attempt") == 1
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("workflow_id") is not None
        and run.get("path")
        in (
            ".github/workflows/boca-first-deploy.yml",
            f"{_REPO}/.github/workflows/boca-first-deploy.yml",
        )
        and run.get("head_sha") == environ["GITHUB_SHA"]
        and run.get("head_branch") == "main"
        and type(run.get("actor")) is dict
        and run["actor"].get("login") == _OWNER
        and type(run.get("repository")) is dict
        and run["repository"].get("full_name") == _REPO,
        "independent PREPARE GitHub run not exact/completed",
    )


def restore_prepared_coordinates(
    coords: dict[str, Any], *, prepare_id: str, environ: Mapping[str, str]
) -> dict[str, str]:
    _main(environ)
    _positive(prepare_id)
    _require(
        prepare_id != environ["GITHUB_RUN_ID"]
        and environ.get("BOCA_PROTECTED_ACTION_CONTEXT") == prepare_id,
        "PREPARE must be distinct from APPLY and token short",
    )
    validated = _validate_coords(coords)
    _require(
        validated["operation"] == environ["BOCA_OPERATION"]
        and validated["source_sha"] == environ["GITHUB_SHA"],
        "PREPARE cannot change main SHA or operation",
    )
    for key, value in _pins_from_coords(validated).items():
        supplied = environ.get(key, "")
        # No guessed manual pin can override a previously reviewed PREPARE.
        _require(not supplied or supplied == value, f"dispatch {key} conflicts with PREPARE")
    return _pins_from_coords(validated)


def validate_prepared_receipt(
    receipt: dict[str, Any],
    coords: dict[str, str],
    *,
    prepare_id: str,
    environ: Mapping[str, str],
    now: datetime,
) -> str:
    _main(environ)
    _require(
        type(receipt) is dict
        and set(receipt) == RECEIPT_KEYS
        and all(type(x) is str for x in receipt.values()),
        "prepared receipt schema untrusted",
    )
    _require(coords == _env_coords(environ), "reviewed coordinates drift")
    issued = receipt.get("prepared_at_utc", "")
    expires = receipt.get("valid_until_utc", "")
    try:
        _require(issued.endswith("Z") and expires.endswith("Z"), "timestamp must be UTC")
        start = datetime.fromisoformat(issued.replace("Z", "+00:00"))
        until = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LegacyGoDispatchError("prepared timestamp invalid") from exc
    _require(
        start.tzinfo is not None
        and until.tzinfo is not None
        and now.tzinfo is not None
        and start.strftime("%Y-%m-%dT%H:%M:%SZ") == issued
        and until.strftime("%Y-%m-%dT%H:%M:%SZ") == expires
        and until - start == timedelta(days=1)
        and start - timedelta(minutes=5) <= now.astimezone(UTC) <= until,
        "prepared GO has expired or clock differs",
    )
    release, browser, bundle = _review_file_paths(environ)
    expected = {
        "version": VERSION,
        "operation": coords["operation"],
        "repository": _REPO,
        "actor": _OWNER,
        "ref": "refs/heads/main",
        "source_sha": coords["source_sha"],
        "release_run_id": coords["release_run_id"],
        "prepare_run_id": prepare_id,
        "prepare_attempt": "1",
        "prepared_at_utc": issued,
        "valid_until_utc": expires,
        "public_context_sha256": _review_receipt_context(coords, prepare_id),
        "release_manifest_sha256": _reviewed_sha(release),
        "browser_manifest_sha256": _reviewed_sha(browser),
        "bundle_sha256": _reviewed_sha(bundle),
        "owner_subject_sha256": hashlib.sha256(
            environ.get("BOCA_BETA_OWNER_SUBJECT", "").encode("utf-8")
        ).hexdigest(),
    }
    _require(expected == receipt, "approved PREPARE source/manifest/owner coordinates changed")
    return hashlib.sha256(GO_DOMAINS[coords["operation"]] + _canonical(receipt)).hexdigest()


def select_official_artifact(listing: dict[str, Any], *, source_run_id: str) -> str:
    """Artifact ID is derived from exact chosen short source-run ID, never input hash."""
    _positive(source_run_id)
    _require(
        type(listing.get("artifacts")) is list
        and type(listing.get("total_count")) is int
        and listing["total_count"] <= 100,
        "official source artifact list incomplete",
    )
    chosen = [
        artifact
        for artifact in listing["artifacts"]
        if type(artifact) is dict
        and artifact.get("name") == f"boca-official-news-receipt-{source_run_id}"
        and artifact.get("expired") is False
        and type(artifact.get("digest")) is str
        and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]) is not None
        and type(artifact.get("workflow_run")) is dict
        and artifact["workflow_run"].get("id") == int(source_run_id)
    ]
    _require(len(chosen) == 1, "reviewed official source artifact absent or ambiguous")
    return _positive(str(chosen[0]["id"]))


def _observer_tokens(environ: Mapping[str, str], *, kind: str, token_path: Path) -> None:
    expected = "cutover-a-apply" if kind == "cutover" else "official-notice-import"
    request = observer_request(environ, operation=expected)
    _write_once(token_path, (request + "\n").encode("ascii"))


def _validate_official_sha_run(environ: Mapping[str, str]) -> str:
    return _positive(environ.get("BOCA_OFFICIAL_NEWS_RUN_ID", ""))


def _restore_early(
    metadata: dict[str, Any],
    *,
    coords_path: Path,
    receipt_path: Path,
    environ: Mapping[str, str],
) -> None:
    prepare_id = _positive(environ.get("BOCA_PROTECTED_ACTION_CONTEXT", ""))
    validate_prepared_metadata(metadata, prepare_id=prepare_id, environ=environ)
    coords = _strict_json(_file(coords_path, canonical=True))
    receipt = _strict_json(_file(receipt_path, canonical=True))
    pins = restore_prepared_coordinates(coords, prepare_id=prepare_id, environ=environ)
    _require(
        set(receipt) == RECEIPT_KEYS
        and receipt.get("prepare_run_id") == prepare_id
        and receipt.get("operation") == coords["operation"]
        and receipt.get("source_sha") == environ["GITHUB_SHA"]
        and receipt.get("release_run_id") == coords["release_run_id"],
        "downloaded PREPARE artifact identity differs before pin restore",
    )
    _env_file(environ, pins)


def _stage_approved(
    metadata: dict[str, Any],
    *,
    coords_path: Path,
    receipt_path: Path,
    environ: Mapping[str, str],
    now: datetime,
) -> str:
    _main(environ)
    prepare_id = _positive(environ.get("BOCA_PROTECTED_ACTION_CONTEXT", ""))
    validate_prepared_metadata(metadata, prepare_id=prepare_id, environ=environ)
    coords = _strict_json(_file(coords_path, canonical=True))
    _require(
        restore_prepared_coordinates(coords, prepare_id=prepare_id, environ=environ)
        == _pins_from_coords(_env_coords(environ)),
        "restored PREPARE coordinates mutated after review",
    )
    receipt = _strict_json(_file(receipt_path, canonical=True))
    go = validate_prepared_receipt(receipt, coords, prepare_id=prepare_id, environ=environ, now=now)
    approved_var = (
        "BOCA_CUTOVER_A_GO_BINDING_SHA256"
        if environ["BOCA_OPERATION"] == "cutover-a-apply"
        else "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256"
    )
    approved = environ.get(approved_var, "")
    _require(
        type(approved) is str
        and _HEX.fullmatch(approved) is not None
        and hmac.compare_digest(go, approved),
        "independent protected Environment GO_B not proven",
    )
    runner = Path(environ.get("RUNNER_TEMP", ""))
    _require(runner.is_absolute() and runner.is_dir(), "private runner directory missing")
    # These three private O_EXCL/0600 files are validated AGAIN by the individual
    # host runner before issuing any SSH command. Input run ID is never authority.
    _write_once(runner / "boca-protected-legacy-go.approved", (go + "\n").encode("ascii"))
    _write_once(
        runner / "boca-protected-legacy-go.prepare-id",
        (prepare_id + "\n").encode("ascii"),
    )
    _write_once(runner / "boca-protected-legacy-go.receipt.json", _canonical(receipt))
    return go


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boca read-only GO_B legacy coordinate review")
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in (
        "select-current-release",
        "verify-current-release",
        "observer-request",
        "accept-observer",
        "select-legacy-release",
        "verify-legacy-release",
        "select-official-artifact",
        "resolve-official-source",
        "prepare",
        "restore-early",
        "apply",
    ):
        sub = modes.add_parser(name)
        sub.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    env = os.environ
    _main(env)
    runner = Path(env.get("RUNNER_TEMP", ""))
    operation = env["BOCA_OPERATION"]
    paths = [Path(p) for p in args.paths]

    if args.mode == "select-current-release":
        _require(len(paths) == 2, "current release source paths missing")
        listing = _strict_json(_file(paths[0], maximum=3_000_000), maximum=3_000_000)
        run_id = select_release_run(listing, source_sha=env["GITHUB_SHA"])
        _write_once(paths[1], (run_id + "\n").encode("ascii"))
        print(f"BOCA_LEGACY_RELEASE_DISCOVERY state=PASS scope=current run={run_id}")
    elif args.mode == "verify-current-release":
        _require(len(paths) == 3, "current manifest paths missing")
        release_id = _file(paths[2], maximum=21).decode("ascii").strip()
        pins = validate_release_manifest(
            _strict_json(_file(paths[0])),
            _strict_json(_file(paths[1])),
            source_sha=env["GITHUB_SHA"],
            release_id=release_id,
        )
        _env_file(env, pins)
        print("BOCA_LEGACY_RELEASE_PINS state=PASS image_source=Actions host=untouched")
    elif args.mode == "observer-request":
        _require(len(paths) == 1, "observer request target missing")
        _observer_tokens(
            env,
            kind="cutover" if operation == "cutover-a-apply" else "official",
            token_path=paths[0],
        )
        print("BOCA_LEGACY_OBSERVER_REQUEST state=READY request=runner-generated")
    elif args.mode == "accept-observer":
        _require(len(paths) == 2, "host inventory evidence paths missing")
        observed = validate_host_inventory(_file(paths[0], maximum=4096), environ=env)
        _write_once(paths[1], _canonical(observed))
        if operation == "cutover-a-apply":
            pins = {
                "BOCA_LEGACY_SOURCE_SHA": observed["legacy_source_sha"],
                "BOCA_LEGACY_IMAGE_REF": observed["legacy_image_ref"],
                "BOCA_LEGACY_CONTROLLER_ID": observed["legacy_controller_id"],
            }
        else:
            pins = {"BOCA_OFFICIAL_CONTROLLER_ID": observed["controller_id"]}
        _env_file(env, pins)
        print("BOCA_LEGACY_OBSERVER state=PASS host_reads=1 app_mutations=0")
    elif args.mode == "select-legacy-release":
        _require(
            len(paths) == 3 and operation == "cutover-a-apply", "legacy release discovery invalid"
        )
        observed = _strict_json(_file(paths[1], canonical=True))
        source = observed.get("legacy_source_sha", "")
        _require(_SHA.fullmatch(source) is not None, "observed historical source absent")
        listing = _strict_json(_file(paths[0], maximum=3_000_000), maximum=3_000_000)
        legacy_id = select_release_run(
            listing, source_sha=source, expected_image=observed["legacy_image_ref"]
        )
        _write_once(paths[2], (legacy_id + "\n").encode("ascii"))
        _env_file(env, {"BOCA_LEGACY_RELEASE_RUN_ID": legacy_id})
        print(f"BOCA_LEGACY_SOURCE_RELEASE state=PASS historical_run={legacy_id}")
    elif args.mode == "verify-legacy-release":
        _require(len(paths) == 3 and operation == "cutover-a-apply", "historical manifest missing")
        observed = _strict_json(_file(paths[1], canonical=True))
        legacy_id = _file(paths[2], maximum=21).decode("ascii").strip()
        manifest = _strict_json(_file(paths[0]))
        _require(
            set(manifest) == {"image_ref", "source_sha", "release_run_id"}
            and manifest["image_ref"] == observed["legacy_image_ref"]
            and manifest["source_sha"] == observed["legacy_source_sha"]
            and str(manifest["release_run_id"]) == legacy_id,
            "historical installed controller release not verifiable",
        )
        print("BOCA_LEGACY_HISTORICAL_MANIFEST state=PASS")
    elif args.mode == "select-official-artifact":
        _require(
            len(paths) == 2 and operation == "official-notice-import",
            "official artifact discovery invalid",
        )
        selection = select_official_artifact(
            _strict_json(_file(paths[0], maximum=3_000_000), maximum=3_000_000),
            source_run_id=_validate_official_sha_run(env),
        )
        _write_once(paths[1], (selection + "\n").encode("ascii"))
        print(f"BOCA_LEGACY_OFFICIAL_ARTIFACT state=PASS artifact_id={selection}")
    elif args.mode == "resolve-official-source":
        _require(
            len(paths) == 4 and operation == "official-notice-import",
            "official source evidence incomplete",
        )
        observed = _strict_json(_file(paths[3], canonical=True))
        _require(observed.get("kind") == "official-inventory", "official host CID unobserved")
        pins = parse_official_source(
            run=_strict_json(_file(paths[0], maximum=80_000)),
            artifact=_strict_json(_file(paths[1], maximum=80_000)),
            archive=_file(paths[2], maximum=128 * 1024),
            controller_id=observed["controller_id"],
            environ=env,
        )
        _env_file(env, pins)
        print("BOCA_LEGACY_OFFICIAL_SOURCE state=PASS reviewed_public_source=TRUE")
    elif args.mode == "prepare":
        _require(
            len(paths) == 0 and not env.get("BOCA_PROTECTED_ACTION_CONTEXT"),
            "PREPARE must not authorize host",
        )
        coords = _env_coords(env)
        receipt, approved = create_prepare_receipt(coords, environ=env, now=datetime.now(UTC))
        _write_once(runner / "boca-legacy-prepare.coordinates.json", _canonical(coords))
        _write_once(runner / "boca-legacy-prepare.receipt.json", _canonical(receipt))
        print(
            f"BOCA_LEGACY_GO_PREPARE state=READY host_effects=0 prepare_run_id={env['GITHUB_RUN_ID']} "
            f"review_go_sha256={approved} next=distinct_protected_APPLY"
        )
        summary = Path(env.get("GITHUB_STEP_SUMMARY", ""))
        if summary.is_absolute():
            with summary.open("a", encoding="ascii") as out:
                out.write(
                    f"BOCA GO_B PREPARE READY: operation={operation}, "
                    f"PREPARE run ID={env['GITHUB_RUN_ID']}, "
                    f"independent reviewed GO SHA256={approved}. "
                    "A separate protected Environment authorization is required for APPLY. "
                    "PREPARE performed no application/Docker writes.\n"
                )
    elif args.mode == "restore-early":
        _require(
            len(paths) == 3 and env.get("BOCA_PROTECTED_ACTION_CONTEXT"),
            "APPLY PREPARE artifact missing",
        )
        _restore_early(
            _strict_json(_file(paths[0], maximum=80_000)),
            coords_path=paths[1],
            receipt_path=paths[2],
            environ=env,
        )
        print("BOCA_LEGACY_APPLY_SOURCE state=PASS reviewed_prepare=TRUE")
    elif args.mode == "apply":
        _require(
            len(paths) == 3 and env.get("BOCA_PROTECTED_ACTION_CONTEXT"),
            "APPLY immutable proof missing",
        )
        digest = _stage_approved(
            _strict_json(_file(paths[0], maximum=80_000)),
            coords_path=paths[1],
            receipt_path=paths[2],
            environ=env,
            now=datetime.now(UTC),
        )
        print(f"BOCA_LEGACY_GO_APPLY state=PASS go_sha256={digest} host_effect=not_started")
    else:
        raise LegacyGoDispatchError("unsupported protected GO_B operation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(cli())
    except (LegacyGoDispatchError, OSError, ValueError) as exc:
        print(f"BOCA_LEGACY_GO state=NO_GO reason={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(3) from None
