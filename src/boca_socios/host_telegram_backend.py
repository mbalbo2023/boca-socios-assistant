"""Installed Telegram transactions."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_lifecycle_rootless_adapter import LifecycleDockerIO
from boca_socios.host_telegram_egress_helper import TelegramHelperPhaseProof
from boca_socios.host_telegram_installed_context import (
    InstalledTelegramContext,
    resolve_installed_context,
)
from boca_socios.host_telegram_maintenance import InstalledMaintenance
from boca_socios.host_telegram_owner_stage import _controller_owner_subject
from boca_socios.host_telegram_protected_custody_caller import run_bound_telegram_staged_custody
from boca_socios.telegram_pairing_cutover import (
    _PURPOSE,
    CutoverCoordinates,
    HostRecheckReceipt,
    _owner_payload,
)
from boca_socios.telegram_pairing_issuer import issue_owner_pairing_receipt


@dataclass(frozen=True)
class TelegramBackendReceipt:
    operation: str
    attempt_id: str
    source_sha: str
    state: str
    restoration: str
    sender_state: str = "OFF"
    human_receipt: str = "UNVERIFIED"

    def redacted_json(self) -> bytes:
        return bootstrap._canonical({"version": 1, **asdict(self)})


class TelegramBackendError(ValueError):
    def __init__(
        self,
        receipt: TelegramBackendReceipt,
        *,
        primary_error: Exception | None = None,
        cleanup_error: Exception | None = None,
    ):
        self.receipt = receipt
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error
        super().__init__("telegram_protected_transaction_failed")


def migrate_installed_telegram(
    attempt_id: str,
    *,
    lease: BocaJobLease,
    reader: LifecycleDockerIO | None = None,
    expected_source_sha: str,
    workflow_sha: str,
) -> TelegramBackendReceipt:
    """Migrate installed schema."""
    context = resolve_installed_context(
        attempt_id,
        lease=lease,
        reader=reader,
        expected_source_sha=expected_source_sha,
        workflow_sha=workflow_sha,
    )
    storage = InstalledMaintenance(context)
    stopped = False
    state = "FAILED_STATE_PRESERVED"
    restoration = "NOT_NEEDED"
    primary_error: Exception | None = None
    cleanup_error: Exception | None = None
    try:
        schema = storage.call("verify-schema", {})
        if schema not in ({"schema": 7}, {"prerequisite": "SCHEMA_0007_REQUIRED"}):
            raise ValueError("schema_unverified")
        context.healthy()
        if context.installation.pair.sender_running:
            raise ValueError("sender_must_be_off")
        stopped = True  # lost stop ACK still requires exact-controller restoration
        context.stop()
        context.stopped()
        if storage.call("migrate-schema", {}) != {"schema": 7}:
            raise ValueError("migration_unverified")
    except Exception as error:
        primary_error = getattr(error, "primary_error", error)
        cleanup_error = getattr(error, "cleanup_error", None)
    finally:
        if stopped:
            if not storage.migration_helper_retired:
                state, restoration = "CLEANUP_INDETERMINATE", "INDETERMINATE"
            else:
                try:
                    context.restore()
                    restoration = "CONTROLLER_HEALTHY_ENGINE_OFF"
                except Exception as error:
                    cleanup_error = error
                    restoration = "INDETERMINATE"
    if (
        primary_error is None
        and cleanup_error is None
        and restoration == "CONTROLLER_HEALTHY_ENGINE_OFF"
    ):
        try:
            context.healthy()
            if storage.call("verify-schema", {}) != {"schema": 7}:
                raise ValueError("schema_postverify_unverified")
            state = "SCHEMA_READY"
        except Exception as error:
            primary_error = error
    receipt = TelegramBackendReceipt("migrate", attempt_id, expected_source_sha, state, restoration)
    if state != "SCHEMA_READY":
        raise TelegramBackendError(
            receipt, primary_error=primary_error, cleanup_error=cleanup_error
        )
    return receipt


def _execute(
    operation: str,
    attempt_id: str,
    *,
    lease: BocaJobLease,
    reader: LifecycleDockerIO | None,
    expected_source_sha: str,
    workflow_sha: str,
) -> TelegramBackendReceipt:
    context = resolve_installed_context(
        attempt_id,
        lease=lease,
        reader=reader,
        expected_source_sha=expected_source_sha,
        workflow_sha=workflow_sha,
    )
    storage = InstalledMaintenance(context)
    stopped = False
    succeeded = False
    restoration = "NOT_NEEDED"
    state = "PREFLIGHT_FAILED"
    sender_state = "OFF"
    try:
        # A read-only mapped-UID probe establishes capability before stopping.
        schema = storage.call("verify-schema", {})
        if schema == {"prerequisite": "SCHEMA_0007_REQUIRED"}:
            state = "SCHEMA_0007_REQUIRED"
            raise ValueError("schema_0007_required")
        if schema != {"schema": 7}:
            raise ValueError("schema_unverified")
        if operation == "observe":
            context.healthy()
            succeeded = True
            return TelegramBackendReceipt(
                operation, attempt_id, expected_source_sha, "SCHEMA_READY", restoration
            )
        owner = storage.call("owner-identity", {})["owner_digest"]
        stopped = True  # even lost stop acknowledgement requires exact-ID restoration
        context.stop()
        state = "STOPPED"
        if operation == "prepare":
            storage.provision()
            recipient = bootstrap.RecipientReceipt(**storage.call("prepare", {}))
            recipient = replace(recipient, state="PREPARED")
            context.bind(recipient, owner)
            storage.call(
                "publish-recipient",
                {
                    "recipient": asdict(recipient),
                    "source_sha": expected_source_sha,
                    "installation_fingerprint": context.installation.fingerprint(),
                },
            )
            context.stopped()
            state = "PREPARED"
        elif operation == "renew":
            recipient = bootstrap.RecipientReceipt(**storage.call("recipient", {}))
            context.bind(recipient, owner)
            context.stopped()
            assert context.coordinates is not None
            if storage.call(
                "archive-stage",
                {
                    "coordinates": asdict(context.coordinates),
                    "owner_subject": _controller_owner_subject(
                        context.reader, context.installation.controller_id
                    ),
                    "installation_fingerprint": context.installation.fingerprint(),
                    "now": int(time.time()),
                },
            ) != {"archived": True}:
                raise ValueError("stage_archive_unverified")
            context.stopped()
            state = "STAGE_ARCHIVED"
        else:
            recipient = bootstrap.RecipientReceipt(**storage.call("recipient", {}))
            context.bind(recipient, owner)
            context.stopped()
            assert context.coordinates is not None and context.pins is not None
            coords, pins = context.coordinates, context.pins
            subject = _controller_owner_subject(context.reader, coords.controller_id)
            stage = storage.read_stage(
                Path("/data"), coordinates=coords, lease=lease, trusted_now=int(time.time())
            )
            owner_request = {
                "coordinates": asdict(coords),
                "now": int(time.time()),
                "owner_subject": subject,
            }
            expected_owner = {
                "envelope_sha256": stage.envelope_sha256,
                "staged_at": stage.staged_at,
            }
            if storage.call("verify-owner", owner_request) != expected_owner:
                raise ValueError("owner_stage_unverified")
            key = secrets.token_bytes(32)
            grant = issue_owner_pairing_receipt(
                coords, stage.envelope, key, int(time.time()), discovery_not_before=stage.staged_at
            )
            # The original stage has one durable fence across retries/run IDs.
            # Changing the HMAC signing nonce cannot authorize the same stage again.
            grant = replace(
                grant,
                nonce=hashlib.sha256(("stage-v2:" + stage.stage_id).encode("ascii")).hexdigest(),
                auth_tag=b"",
            )
            grant = replace(
                grant,
                auth_tag=hmac.new(key, _PURPOSE + _owner_payload(grant), hashlib.sha256).digest(),
            )

            def attest(
                phase: str, proof: TelegramHelperPhaseProof, checked: CutoverCoordinates
            ) -> HostRecheckReceipt:
                if (
                    checked != coords
                    or proof.attempt_id != attempt_id
                    or proof.source_sha != expected_source_sha
                    or proof.phase != phase
                ):
                    raise ValueError("phase_changed")
                context.stopped(active_helper=True)
                if storage.call("verify-schema", {}) != {"schema": 7}:
                    raise ValueError("schema_changed")
                owner_request["now"] = int(time.time())
                if storage.call("verify-owner", owner_request) != expected_owner:
                    raise ValueError("owner_changed")
                if phase == "AFTER_COMMIT":
                    custody = storage.verify(
                        Path("/run/telegram"), expected_source_sha=expected_source_sha
                    )
                    if custody.recipient_fingerprint != recipient.fingerprint:
                        raise ValueError("custody_changed")
                elif bootstrap.RecipientReceipt(**storage.call("recipient", {})) != recipient:
                    raise ValueError("recipient_changed")
                context.stopped(active_helper=True)
                # Each field below follows observations above and the caller's
                # fresh R32 exact-helper/no-competing-poller topology witness.
                return HostRecheckReceipt(
                    coords,
                    phase,
                    int(time.time()),
                    context.reader.uid,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                )

            result = run_bound_telegram_staged_custody(
                pins,
                coords,
                lease=lease,
                stage_directory=Path("/data"),
                custody_directory=Path("/run/telegram"),
                owner_receipt=grant,
                owner_receipt_key=key,
                recipient=recipient,
                private_key=None,
                trusted_clock=lambda: int(time.time()),
                phase_host_attestor=attest,
                reader=context.reader,
                storage=storage,
            )
            context.stopped()
            if result.state != "CUSTODY_COMMITTED_NO_SEND":
                raise ValueError("custody_not_committed")
            state = result.state
            from boca_socios.host_telegram_sender import activate_installed_sender

            sender_state = "UNVERIFIED"
            sender = activate_installed_sender(
                context,
                lease=lease,
                maintenance=storage,
                expected_source_sha=expected_source_sha,
                attempt_id=attempt_id,
            )
            if (
                sender.state != "VERIFIED"
                or sender.source_sha != expected_source_sha
                or re.fullmatch(r"[a-f0-9]{64}", sender.sender_id) is None
            ):
                raise ValueError("sender_unverified")
            sender_state = "VERIFIED"
            state = "READY"
        succeeded = True
    except Exception:
        if state != "SCHEMA_0007_REQUIRED":
            state = "FAILED_STATE_PRESERVED"
    finally:
        if not succeeded:
            try:
                storage.cleanup_failed_provision()
            except Exception:
                state = "CLEANUP_INDETERMINATE"
        if stopped:
            try:
                context.restore()
                restoration = "CONTROLLER_HEALTHY_ENGINE_OFF"
            except Exception:
                restoration = "INDETERMINATE"
                state = "FAILED_STATE_PRESERVED"
                succeeded = False
    if succeeded and restoration == "CONTROLLER_HEALTHY_ENGINE_OFF":
        try:
            from boca_socios.host_telegram_status import publish_installed_status

            publish_installed_status(
                context, storage, expected_custody="VERIFIED" if state == "READY" else "ABSENT"
            )
        except Exception:
            state = "FAILED_STATE_PRESERVED"
            succeeded = False
    receipt = TelegramBackendReceipt(
        operation, attempt_id, expected_source_sha, state, restoration, sender_state
    )
    if not succeeded:
        raise TelegramBackendError(receipt)
    return receipt


def prepare_installed_telegram(
    attempt_id: str,
    *,
    lease: BocaJobLease,
    reader: LifecycleDockerIO | None = None,
    expected_source_sha: str,
    workflow_sha: str,
) -> TelegramBackendReceipt:
    return _execute(
        "prepare",
        attempt_id,
        lease=lease,
        reader=reader,
        expected_source_sha=expected_source_sha,
        workflow_sha=workflow_sha,
    )


def activate_installed_telegram(
    attempt_id: str,
    *,
    lease: BocaJobLease,
    reader: LifecycleDockerIO | None = None,
    expected_source_sha: str,
    workflow_sha: str,
) -> TelegramBackendReceipt:
    return _execute(
        "activate",
        attempt_id,
        lease=lease,
        reader=reader,
        expected_source_sha=expected_source_sha,
        workflow_sha=workflow_sha,
    )


def renew_installed_telegram_stage(
    attempt_id: str,
    *,
    lease: BocaJobLease,
    reader: LifecycleDockerIO | None = None,
    expected_source_sha: str,
    workflow_sha: str,
) -> TelegramBackendReceipt:
    return _execute(
        "renew",
        attempt_id,
        lease=lease,
        reader=reader,
        expected_source_sha=expected_source_sha,
        workflow_sha=workflow_sha,
    )


def verify_backend_receipt(
    raw: bytes,
    *,
    attempt_id: str,
    expected_source_sha: str,
    operation: str,
    allow_failure: bool = False,
) -> bytes:
    """Verify strict receipts."""
    try:
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= 1024
            or operation
            not in {"prepare", "activate", "recover", "renew", "complete", "migrate", "observe"}
        ):
            raise ValueError("frame")
        raw = raw.removesuffix(b"\n")
        value = json.loads(raw, object_pairs_hook=bootstrap._unique)
        expected_fields = {
            "version",
            "operation",
            "attempt_id",
            "source_sha",
            "state",
            "restoration",
            "sender_state",
            "human_receipt",
        }
        if (
            type(value) is not dict
            or set(value) != expected_fields
            or bootstrap._canonical(value) != raw
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["operation"] != operation
            or value["attempt_id"] != attempt_id
            or re.fullmatch(r"[1-9][0-9]{0,19}", attempt_id) is None
            or value["source_sha"] != expected_source_sha
            or re.fullmatch(r"[a-f0-9]{40}", expected_source_sha) is None
            or type(allow_failure) is not bool
            or value["human_receipt"] != "UNVERIFIED"
        ):
            raise ValueError("receipt")
        success = (
            value["state"]
            == {
                "prepare": "PREPARED",
                "activate": "READY",
                "recover": "RECOVERED",
                "renew": "STAGE_ARCHIVED",
                "complete": "READY",
                "migrate": "SCHEMA_READY",
                "observe": "SCHEMA_READY",
            }[operation]
            and value["restoration"]
            == ("NOT_NEEDED" if operation == "observe" else "CONTROLLER_HEALTHY_ENGINE_OFF")
            and value["sender_state"]
            in {
                "prepare": {"OFF"},
                "activate": {"VERIFIED"},
                "recover": {"OFF", "VERIFIED"},
                "renew": {"OFF"},
                "complete": {"VERIFIED"},
                "migrate": {"OFF"},
                "observe": {"OFF"},
            }[operation]
        )
        failure = (
            allow_failure
            and value["state"]
            in {"FAILED_STATE_PRESERVED", "CLEANUP_INDETERMINATE", "SCHEMA_0007_REQUIRED"}
            and value["restoration"]
            in (
                {"NOT_NEEDED"}
                if operation == "observe" and value["state"] == "SCHEMA_0007_REQUIRED"
                else {"NOT_NEEDED", "INDETERMINATE"}
                if operation == "observe"
                else {"NOT_NEEDED", "CONTROLLER_HEALTHY_ENGINE_OFF", "INDETERMINATE"}
            )
            and value["sender_state"]
            in (
                {"OFF", "UNVERIFIED"}
                if operation in {"prepare", "renew", "migrate", "observe"}
                else {"OFF", "VERIFIED", "UNVERIFIED"}
            )
        )
        preflight = (
            allow_failure
            and value["state"] == "PREFLIGHT_FAILED"
            and value["restoration"] == "NOT_NEEDED"
            and value["sender_state"] == "UNVERIFIED"
        )
        if not success and not failure and not preflight:
            raise ValueError("receipt")
        return raw
    except Exception:
        raise ValueError("telegram_backend_receipt_unverified") from None


DIAGNOSIS_PREFIX = b"BOCA_TELEGRAM_PREPARE_DIAGNOSIS_V1 "
DIAGNOSIS_SOURCE = "845f31abfb1762dff27e6fc3274fcc40507f3f18"
DIAGNOSIS_APPLY = "43704768556"
DIAGNOSIS_INCIDENT = "43738415332"
DIAGNOSIS_CONTROLLER = "b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1"
DIAGNOSIS_WORKER = "c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce"
_DIAGNOSIS_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0"
)
_DIAGNOSIS_BROWSER = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe"
)
_DIAGNOSIS_VOLUME = "boca-socios_boca_telegram"
_DIAGNOSIS_MOUNT = "/home/boca-deploy/.local/share/docker/volumes/" + _DIAGNOSIS_VOLUME + "/_data"
_RECIPIENT_FIELDS = ("source_sha", "installation_fingerprint", "fingerprint")
_ADMIN_FIELDS = (
    "source_sha",
    "observation_run_id",
    "installation_run_id",
    "controller_id",
    "worker_id",
    "sender_id",
    "observed_at",
    "configured",
    "paired",
    "sender",
    "human_receipt",
)


def _empty_public(kind: str, state: str = "NOT_READ") -> dict[str, Any]:
    fields = _RECIPIENT_FIELDS if kind == "recipient" else _ADMIN_FIELDS
    return {"state": state, "digest": None, "witness": None, **dict.fromkeys(fields)}


def _diagnosis_initial(attempt_id: str, workflow_sha: str) -> dict[str, Any]:
    return {
        "version": 1,
        "operation": "telegram-prepare-diagnose",
        "source_sha": DIAGNOSIS_SOURCE,
        "workflow_source_sha": workflow_sha,
        "attempt_id": attempt_id,
        "installation_run_id": DIAGNOSIS_APPLY,
        "incident_run_id": DIAGNOSIS_INCIDENT,
        "controller_id": DIAGNOSIS_CONTROLLER,
        "worker_id": DIAGNOSIS_WORKER,
        "state": "INCOMPLETE_NO_GO",
        "phase": "PREFLIGHT",
        "reason": "GUARD_UNVERIFIED",
        "guards": "NOT_READ",
        "binding_fingerprint": None,
        "recipient": _empty_public("recipient"),
        "admin": _empty_public("admin"),
        "volume": "NOT_READ",
        "custody": {
            "state": "NOT_READ",
            "entries": "NOT_READ",
            "fingerprint": None,
            "witness": None,
            "samples": 0,
        },
        "key_match": "NOT_COMPARED",
        "helper": {
            "id": None,
            "create_attempted": False,
            "start_attempted": False,
            "stop_attempted": False,
            "remove_attempted": False,
            "retirement": "NOT_ATTEMPTED",
        },
        "engine": "NOT_READ",
        "sender": "NOT_READ",
        "stage": "NOT_INSPECTED",
        "historical_cause": "UNDETERMINED",
        "recommendation": "PRESERVE_REVIEW",
        "data_writes": 0,
        "custody_writes": 0,
        "status_writes": 0,
        "prepare_authorized": False,
        "adopt_authorized": False,
    }


def _diagnosis_text(value: Any, pattern: str, *, optional: bool = False) -> bool:
    return (optional and value is None) or (
        type(value) is str and re.fullmatch(pattern, value) is not None
    )


def _validate_public(value: Any, kind: str, *, installed: bool = False) -> None:
    fields = _RECIPIENT_FIELDS if kind == "recipient" else _ADMIN_FIELDS
    valid_states = {"VALID"} if installed else {"MATCH_R", "MISMATCH"}
    if (
        type(value) is not dict
        or set(value) != {"state", "digest", "witness", *fields}
        or value["state"] not in valid_states | {"ABSENT", "INVALID", "NOT_READ", "CHANGED"}
        or not _diagnosis_text(value["witness"], r"[a-f0-9]{64}", optional=True)
        or (value["state"] == "ABSENT" and value["witness"] is None)
    ):
        raise ValueError("public")
    if value["state"] not in valid_states:
        if any(value[key] is not None for key in ("digest", *fields)):
            raise ValueError("public")
        return
    if not all(
        _diagnosis_text(value[key], pattern)
        for key, pattern in (
            ("digest", r"[a-f0-9]{64}"),
            ("witness", r"[a-f0-9]{64}"),
            ("source_sha", r"[a-f0-9]{40}"),
        )
    ):
        raise ValueError("public")
    if kind == "recipient":
        if not all(_diagnosis_text(value[key], r"[a-f0-9]{64}") for key in fields[1:]):
            raise ValueError("public")
    else:
        if (
            not all(
                _diagnosis_text(value[key], r"[1-9][0-9]{0,19}")
                for key in ("observation_run_id", "installation_run_id")
            )
            or not all(
                _diagnosis_text(value[key], r"[a-f0-9]{64}")
                for key in ("controller_id", "worker_id")
            )
            or not _diagnosis_text(value["sender_id"], r"[a-f0-9]{64}", optional=True)
            or not _diagnosis_text(value["observed_at"], r"[0-9T:.+Z-]{20,40}")
            or datetime.fromisoformat(value["observed_at"]).tzinfo is None
            or value["configured"] not in {"ABSENT", "VERIFIED", "UNVERIFIED"}
            or value["paired"] not in {"NOT_PAIRED", "VERIFIED", "UNVERIFIED"}
            or value["sender"] not in {"ABSENT", "STOPPED", "RUNNING", "UNVERIFIED"}
            or value["human_receipt"] != "UNVERIFIED"
            or datetime.fromisoformat(value["observed_at"]) > datetime.now(UTC)
            or (value["sender"] == "ABSENT" and value["sender_id"] is not None)
            or (value["sender"] in {"STOPPED", "RUNNING"} and value["sender_id"] is None)
            or (value["paired"] == "VERIFIED" and value["configured"] != "VERIFIED")
            or value["controller_id"] == value["worker_id"]
            or value["sender_id"] in {value["controller_id"], value["worker_id"]}
        ):
            raise ValueError("public")
    if value["state"] == "MATCH_R" and (
        value["source_sha"] != DIAGNOSIS_SOURCE
        or (
            kind == "admin"
            and any(
                value[key] != expected
                for key, expected in (
                    ("installation_run_id", DIAGNOSIS_APPLY),
                    ("controller_id", DIAGNOSIS_CONTROLLER),
                    ("worker_id", DIAGNOSIS_WORKER),
                )
            )
        )
    ):
        raise ValueError("public_coordinates")


def _validate_custody(value: Any) -> None:
    if (
        type(value) is not dict
        or set(value) != {"state", "entries", "fingerprint", "witness", "samples"}
        or value["state"] not in {"VALID", "ABSENT", "INVALID", "NOT_READ", "CHANGED"}
        or value["entries"]
        not in {"EMPTY", "KEY_ONLY", "EXTRA_ENTRIES_PRESENT", "NOT_READ", "CHANGED"}
        or type(value["samples"]) is not int
        or value["samples"] not in {0, 2}
        or not _diagnosis_text(value["witness"], r"[a-f0-9]{64}", optional=True)
        or not _diagnosis_text(value["fingerprint"], r"[a-f0-9]{64}", optional=True)
        or (value["fingerprint"] is not None) != (value["state"] == "VALID")
        or (
            value["state"] == "VALID"
            and (
                value["entries"] != "KEY_ONLY" or value["samples"] != 2 or value["witness"] is None
            )
        )
        or (value["state"] == "ABSENT" and value["entries"] != "EMPTY")
        or (
            value["samples"] == 2
            and (value["state"] == "ABSENT" or value["entries"] == "EXTRA_ENTRIES_PRESENT")
            and value["witness"] is None
        )
        or (value["entries"] == "EXTRA_ENTRIES_PRESENT" and value["state"] != "NOT_READ")
        or (
            value["state"] == "CHANGED"
            and (value["entries"] != "CHANGED" or value["witness"] is not None)
        )
    ):
        raise ValueError("custody")


def _diagnosis_recommendation(value: dict[str, Any]) -> str:
    public, admin, custody = value["recipient"], value["admin"], value["custody"]
    if admin["state"] not in {"MATCH_R", "ABSENT"} or public["state"] not in {"MATCH_R", "ABSENT"}:
        return "PRESERVE_REVIEW"
    if custody["entries"] == "EXTRA_ENTRIES_PRESENT":
        return "CUSTODY_PRESENT_REVIEW"
    if public["state"] == "ABSENT":
        if custody["state"] == "VALID" and custody["entries"] == "KEY_ONLY":
            return "PREPARE_FINAL_REUSE_KEY"
        if custody["state"] == "ABSENT" and custody["entries"] == "EMPTY":
            return "PREPARE_FINAL_CREATE_KEY"
    if public["state"] == "MATCH_R":
        if value["key_match"] == "MATCH":
            return "PUBLIC_REBIND_REQUIRED"
        if custody["state"] == "ABSENT" and custody["entries"] == "EMPTY":
            return "INCONSISTENT_PRESERVE"
    return "PRESERVE_REVIEW"


def verify_prepare_diagnosis(
    raw: bytes,
    *,
    attempt_id: str,
    source_sha: str,
    workflow_sha: str,
    allow_failure: bool = False,
) -> dict[str, Any]:
    """Closed, framed diagnosis codec, separate from every V1 backend receipt."""
    try:
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= 4096
            or not raw.startswith(DIAGNOSIS_PREFIX)
            or not raw.endswith(b"\n")
            or not _diagnosis_text(attempt_id, r"[1-9][0-9]{0,19}")
            or not _diagnosis_text(workflow_sha, r"[a-f0-9]{40}")
            or source_sha != DIAGNOSIS_SOURCE
            or type(allow_failure) is not bool
        ):
            raise ValueError("frame")
        value = json.loads(raw[len(DIAGNOSIS_PREFIX) : -1], object_pairs_hook=bootstrap._unique)
        initial = _diagnosis_initial(attempt_id, workflow_sha)
        if (
            type(value) is not dict
            or set(value) != set(initial)
            or DIAGNOSIS_PREFIX + bootstrap._canonical(value) + b"\n" != raw
            or type(value["version"]) is not int
            or value["version"] != 1
            or any(
                value[key] != initial[key]
                for key in (
                    "operation",
                    "source_sha",
                    "workflow_source_sha",
                    "attempt_id",
                    "installation_run_id",
                    "incident_run_id",
                    "controller_id",
                    "worker_id",
                    "stage",
                    "historical_cause",
                )
            )
            or any(
                type(value[key]) is not int or value[key] != 0
                for key in ("data_writes", "custody_writes", "status_writes")
            )
            or value["prepare_authorized"] is not False
            or value["adopt_authorized"] is not False
            or value["phase"]
            not in {
                "LEASE",
                "PREFLIGHT",
                "PUBLIC_A",
                "RECIPIENT",
                "PUBLIC_B",
                "POSTFLIGHT",
                "COMPLETE",
            }
            or value["reason"]
            not in {
                "NONE",
                "GUARD_UNVERIFIED",
                "PUBLIC_UNVERIFIED",
                "CUSTODY_UNVERIFIED",
                "HELPER_UNVERIFIED",
                "PUBLIC_CHANGED",
                "LEASE_UNVERIFIED",
                "TRANSPORT_UNVERIFIED",
            }
            or value["guards"] not in {"NOT_READ", "BEFORE", "BEFORE_AFTER"}
            or value["engine"] not in {"NOT_READ", "STOPPED"}
            or value["sender"] not in {"NOT_READ", "ABSENT"}
            or value["volume"] not in {"NOT_READ", "ABSENT", "PRESENT"}
            or not _diagnosis_text(value["binding_fingerprint"], r"[a-f0-9]{64}", optional=True)
            or (value["guards"] != "NOT_READ" and value["binding_fingerprint"] is None)
        ):
            raise ValueError("fields")
        for kind in ("recipient", "admin"):
            _validate_public(value[kind], kind)
        if (
            value["recipient"]["state"] == "MATCH_R"
            and value["recipient"]["installation_fingerprint"] != value["binding_fingerprint"]
        ):
            raise ValueError("public_binding")
        custody, helper = value["custody"], value["helper"]
        _validate_custody(custody)
        if (
            type(helper) is not dict
            or set(helper) != set(initial["helper"])
            or not _diagnosis_text(helper["id"], r"[a-f0-9]{64}", optional=True)
            or any(
                type(helper[key]) is not bool
                for key in (
                    "create_attempted",
                    "start_attempted",
                    "stop_attempted",
                    "remove_attempted",
                )
            )
            or helper["retirement"] not in {"NOT_ATTEMPTED", "RETIRED", "INDETERMINATE"}
            or (not helper["create_attempted"] and helper != initial["helper"])
            or (helper["create_attempted"] and helper["retirement"] == "NOT_ATTEMPTED")
            or (
                any(
                    helper[key] for key in ("start_attempted", "stop_attempted", "remove_attempted")
                )
                and helper["id"] is None
            )
            or (helper["retirement"] == "RETIRED" and not helper["remove_attempted"])
            or (value["volume"] != "PRESENT" and helper != initial["helper"])
        ):
            raise ValueError("helper")
        comparison = "NOT_COMPARED"
        if value["recipient"]["state"] == "MATCH_R" and custody["state"] == "VALID":
            comparison = (
                "MATCH"
                if hmac.compare_digest(value["recipient"]["fingerprint"], custody["fingerprint"])
                else "MISMATCH"
            )
        if value["key_match"] != comparison:
            raise ValueError("comparison")
        complete = value["state"] == "OBSERVED_NO_GO"
        if complete:
            if (
                value["phase"] != "COMPLETE"
                or value["reason"] != "NONE"
                or value["guards"] != "BEFORE_AFTER"
                or value["engine"] != "STOPPED"
                or value["sender"] != "ABSENT"
                or value["volume"] == "NOT_READ"
                or any(
                    value[kind]["state"] in {"NOT_READ", "CHANGED"}
                    for kind in ("recipient", "admin")
                )
                or custody["state"] == "CHANGED"
                or (
                    custody["state"] == "NOT_READ" and custody["entries"] != "EXTRA_ENTRIES_PRESENT"
                )
                or (
                    value["volume"] == "PRESENT"
                    and (
                        helper["retirement"] != "RETIRED"
                        or not helper["start_attempted"]
                        or custody["samples"] != 2
                    )
                )
                or (
                    value["volume"] == "ABSENT"
                    and (
                        custody
                        != {
                            "state": "ABSENT",
                            "entries": "EMPTY",
                            "fingerprint": None,
                            "witness": None,
                            "samples": 0,
                        }
                    )
                )
                or value["recommendation"] != _diagnosis_recommendation(value)
            ):
                raise ValueError("complete")
        elif (
            not allow_failure
            or value["state"] != "INCOMPLETE_NO_GO"
            or value["phase"] == "COMPLETE"
            or value["reason"] == "NONE"
            or value["recommendation"] != "PRESERVE_REVIEW"
        ):
            raise ValueError("incomplete")
        return value
    except Exception:
        raise ValueError("telegram_prepare_diagnosis_unverified") from None


def _diagnosis_frame(value: dict[str, Any]) -> bytes:
    raw = DIAGNOSIS_PREFIX + bootstrap._canonical(value) + b"\n"
    verify_prepare_diagnosis(
        raw,
        attempt_id=value["attempt_id"],
        source_sha=DIAGNOSIS_SOURCE,
        workflow_sha=value["workflow_source_sha"],
        allow_failure=True,
    )
    return raw


def _diagnosis_guard(context: InstalledTelegramContext) -> None:
    context.healthy()
    item = context.installation
    if (
        item.source_sha != DIAGNOSIS_SOURCE
        or item.installation_run_id != DIAGNOSIS_APPLY
        or item.controller_id != DIAGNOSIS_CONTROLLER
        or item.worker_id != DIAGNOSIS_WORKER
        or item.controller_image != _DIAGNOSIS_IMAGE
        or item.worker_image != _DIAGNOSIS_BROWSER
        or item.pair.sender_id
        or item.pair.sender_running
    ):
        raise ValueError("diagnosis_target_unverified")
    inventory = context.reader.inventory()
    if len(inventory.containers) != 2 or {entry.ident for entry in inventory.containers} != {
        DIAGNOSIS_CONTROLLER,
        DIAGNOSIS_WORKER,
    }:
        raise ValueError("diagnosis_writers_unverified")
    present = _DIAGNOSIS_VOLUME in {entry.name for entry in inventory.volumes}
    if present != (_DIAGNOSIS_VOLUME in dict(context.volumes)):
        raise ValueError("diagnosis_volume_changed")
    if present and (
        context.reader.field("volume", _DIAGNOSIS_VOLUME, "Name") != _DIAGNOSIS_VOLUME
        or context.reader.field("volume", _DIAGNOSIS_VOLUME, "Mountpoint") != _DIAGNOSIS_MOUNT
    ):
        raise ValueError("diagnosis_volume_unverified")
    for ident in (DIAGNOSIS_CONTROLLER, DIAGNOSIS_WORKER):
        mounts = context.reader.field("container", ident, "Mounts")
        if type(mounts) is not list or any(
            (
                mount.get("Type") == "volume"
                and mount.get("Source")
                != "/home/boca-deploy/.local/share/docker/volumes/"
                + str(mount.get("Name"))
                + "/_data"
            )
            or mount.get("Name") == _DIAGNOSIS_VOLUME
            or mount.get("Source") == _DIAGNOSIS_MOUNT
            or str(mount.get("Source", "")).startswith(_DIAGNOSIS_MOUNT + "/")
            or mount.get("Destination") == "/run/telegram"
            for mount in mounts
        ):
            raise ValueError("diagnosis_custody_writer_unverified")
    context.check_binding()


def diagnose_installed_telegram(
    attempt_id: str,
    *,
    lease: BocaJobLease,
    reader: LifecycleDockerIO | None = None,
    expected_source_sha: str,
    workflow_sha: str,
) -> bytes:
    """Observe the fixed failed prepare target; no publication or authorization."""
    from boca_socios.host_telegram_status import observe_installed_public

    value = _diagnosis_initial(attempt_id, workflow_sha)
    _diagnosis_frame(value)
    storage: InstalledMaintenance | None = None
    try:
        if expected_source_sha != DIAGNOSIS_SOURCE:
            raise ValueError("diagnosis_source_unverified")
        context = resolve_installed_context(
            attempt_id,
            lease=lease,
            reader=reader,
            expected_source_sha=expected_source_sha,
            workflow_sha=workflow_sha,
        )
        _diagnosis_guard(context)
        value.update(
            guards="BEFORE",
            binding_fingerprint=context.installation.fingerprint(),
            engine="STOPPED",
            sender="ABSENT",
            volume="PRESENT" if _DIAGNOSIS_VOLUME in dict(context.volumes) else "ABSENT",
        )
        value.update(phase="PUBLIC_A", reason="PUBLIC_UNVERIFIED")
        before = observe_installed_public(context)
        if set(before) != {"recipient", "admin"}:
            raise ValueError("public")
        for kind in before:
            _validate_public(before[kind], kind, installed=True)
            document = dict(before[kind])
            if document["state"] == "VALID":
                matched = document["source_sha"] == DIAGNOSIS_SOURCE
                if kind == "recipient":
                    matched = (
                        matched
                        and document["installation_fingerprint"]
                        == context.installation.fingerprint()
                    )
                else:
                    matched = matched and all(
                        document[field] == expected
                        for field, expected in (
                            ("installation_run_id", DIAGNOSIS_APPLY),
                            ("controller_id", DIAGNOSIS_CONTROLLER),
                            ("worker_id", DIAGNOSIS_WORKER),
                        )
                    )
                document["state"] = "MATCH_R" if matched else "MISMATCH"
            value[kind] = document
        value.update(phase="RECIPIENT", reason="HELPER_UNVERIFIED")
        if value["volume"] == "PRESENT":
            storage = InstalledMaintenance(context)
            custody = storage.call("recipient-observe", {})
            _validate_custody(custody)
            value["custody"] = custody
        else:
            value["custody"] = {
                "state": "ABSENT",
                "entries": "EMPTY",
                "fingerprint": None,
                "witness": None,
                "samples": 0,
            }
        value.update(phase="PUBLIC_B", reason="PUBLIC_UNVERIFIED")
        after = observe_installed_public(context)
        if set(after) != {"recipient", "admin"}:
            raise ValueError("public")
        for kind in after:
            _validate_public(after[kind], kind, installed=True)
            if before[kind] != after[kind]:
                value[kind] = _empty_public(kind, "CHANGED")
        value.update(phase="POSTFLIGHT", reason="GUARD_UNVERIFIED")
        _diagnosis_guard(context)
        value["guards"] = "BEFORE_AFTER"
        if any(value[kind]["state"] in {"NOT_READ", "CHANGED"} for kind in before):
            value.update(
                phase="PUBLIC_B",
                reason="PUBLIC_CHANGED"
                if any(value[kind]["state"] == "CHANGED" for kind in before)
                else "PUBLIC_UNVERIFIED",
            )
        elif value["custody"]["state"] == "CHANGED" or (
            value["custody"]["state"] == "NOT_READ"
            and value["custody"]["entries"] != "EXTRA_ENTRIES_PRESENT"
        ):
            value.update(phase="RECIPIENT", reason="CUSTODY_UNVERIFIED")
        else:
            value.update(state="OBSERVED_NO_GO", phase="COMPLETE", reason="NONE")
    except Exception:
        # Finite phase/reason already records the failed boundary; never serialize exceptions.
        if value["phase"] == "POSTFLIGHT":
            value.update(engine="NOT_READ", sender="NOT_READ")
    if storage is not None:
        value["helper"] = dict(storage.recipient_observation)
    if value["recipient"]["state"] == "MATCH_R" and value["custody"]["state"] == "VALID":
        value["key_match"] = (
            "MATCH"
            if hmac.compare_digest(
                value["recipient"]["fingerprint"], value["custody"]["fingerprint"]
            )
            else "MISMATCH"
        )
    if value["state"] == "OBSERVED_NO_GO":
        value["recommendation"] = _diagnosis_recommendation(value)
    return _diagnosis_frame(value)
