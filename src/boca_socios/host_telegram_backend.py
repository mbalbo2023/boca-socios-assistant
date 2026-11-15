"""Installed Telegram transactions."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_lifecycle_rootless_adapter import LifecycleDockerIO
from boca_socios.host_telegram_egress_helper import TelegramHelperPhaseProof
from boca_socios.host_telegram_installed_context import resolve_installed_context
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
