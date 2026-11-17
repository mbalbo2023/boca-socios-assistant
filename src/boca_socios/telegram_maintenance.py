"""Fixed network-none storage operations inside the exact installed image.

Only the parent protected host process holds authority and the lease. This
process has no Docker socket, external transport, host key or arbitrary path.
Its binary response is private pipe data, never a workflow log.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.telegram_maintenance_contract import MAX_FRAME, MOUNTS

DATA = Path("/data")
CUSTODY = Path("/run/telegram")
OWNER = Path("/run/owner")


def execute(operation: str, request: dict[str, Any]) -> dict[str, Any]:
    """No caller-selected filesystem path, Python expression, or network method."""
    from boca_socios.telegram_owner_webauthn import witness_document
    from boca_socios.telegram_pairing_cutover import CutoverCoordinates, _coordinates_valid
    from boca_socios.telegram_same_lease_stage import consume_nonce_storage, read_stage_storage

    if operation == "initialize-volume":
        bootstrap._identity(0)
        if request != {"new_empty_volume": "boca-socios_boca_telegram"}:
            raise ValueError("new_volume_required")
        descriptor = os.open(CUSTODY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.listdir(descriptor) or os.fstat(descriptor).st_uid != 0:
                raise ValueError("empty_new_volume_required")
            os.fchmod(descriptor, 0o700)
            os.fchown(descriptor, 10001, 10001)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {"initialized": True}
    bootstrap._identity(bootstrap.UID)
    if operation not in MOUNTS or type(request) is not dict:
        raise ValueError("maintenance_operation_unverified")
    if operation in {"inspect-direct", "install-direct", "verify-direct"}:
        from boca_socios.telegram_direct_custody import execute_direct

        return execute_direct(operation, DATA, CUSTODY, request)
    coords = CutoverCoordinates(**request["coordinates"]) if "coordinates" in request else None
    if coords is not None and not _coordinates_valid(coords):
        raise ValueError("maintenance_coordinates_unverified")
    if operation == "verify-schema":
        from boca_socios.telegram_storage_gate import StorageGateError, verify

        try:
            verify(DATA / "boca.sqlite3")
        except StorageGateError as exc:
            if str(exc) != "schema_ledger":
                raise
            # Exact legacy verification proves this is only the missing additive
            # prerequisite, rather than corrupt/unknown storage.
            verify(DATA / "boca.sqlite3", require_telegram=False)
            return {"prerequisite": "SCHEMA_0007_REQUIRED"}
        return {"schema": 7}
    if operation == "recipient":
        parent = bootstrap._directory(CUSTODY, bootstrap.UID)
        try:
            return asdict(
                bootstrap._receipt(
                    bootstrap._read(parent, bootstrap.PRIVATE_KEY, bootstrap.UID, maximum=32),
                    "PREPARED",
                )
            )
        finally:
            os.close(parent)
    if operation == "prepare":
        parent = bootstrap._directory(CUSTODY, bootstrap.UID)
        try:
            if set(os.listdir(parent)) - {bootstrap.PRIVATE_KEY}:
                raise ValueError("custody_present")
        finally:
            os.close(parent)
        return asdict(bootstrap.prepare(CUSTODY))
    if operation == "owner-identity":
        from boca_socios.host_telegram_owner_stage import _read_owner_public_file

        credential = _read_owner_public_file(OWNER, "credential_id", 1024)
        public = _read_owner_public_file(OWNER, "public_key.der", 4096)
        return {"owner_digest": hashlib.sha256(credential + b"\0" + public).hexdigest()}
    if operation in {"publish-status", "publish-status-absent"}:
        from boca_socios.telegram_status_publication import publish

        return publish(DATA, CUSTODY if operation == "publish-status" else None, request)
    if operation == "sender-evidence":
        from boca_socios.telegram_sender_evidence import inspect_sender_evidence

        if coords is None or set(request) != {
            "coordinates",
            "owner_subject",
            "installation_fingerprint",
        }:
            raise ValueError("sender_evidence_request_unverified")
        verified = execute("verify-owner", {**request, "now": None})
        return inspect_sender_evidence(
            DATA, CUSTODY, coords, request["installation_fingerprint"], verified
        )
    if operation == "archive-stage":
        from boca_socios.panel.telegram_recipient import (
            FILENAME,
            _document,
            _public_data_directory,
        )
        from boca_socios.telegram_same_lease_stage import archive_stage_storage

        if coords is None:
            raise ValueError("maintenance_coordinates_required")
        # Any installed or partial custody forbids renewal. Only the prepared
        # recipient key may exist; unknown files are preserved as NO_GO.
        parent = bootstrap._directory(CUSTODY, bootstrap.UID)
        try:
            if set(os.listdir(parent)) != {bootstrap.PRIVATE_KEY}:
                raise ValueError("custody_present")
            recipient = bootstrap._receipt(
                bootstrap._read(parent, bootstrap.PRIVATE_KEY, bootstrap.UID, maximum=32),
                "PREPARED",
            )
            if recipient.fingerprint != coords.recipient_fingerprint:
                raise ValueError("recipient_changed")
        finally:
            os.close(parent)
        parent = _public_data_directory(DATA)
        try:
            prepared, installation = _document(
                bootstrap._read(parent, FILENAME, bootstrap.UID, maximum=1024), coords.target_sha
            )
            if prepared != recipient or installation != request["installation_fingerprint"]:
                raise ValueError("prepared_binding_changed")
        finally:
            os.close(parent)
        # Static cryptographic owner verification intentionally has no freshness
        # clock: explicit renewal must admit an expired valid owner stage.
        verified = execute("verify-owner", {**request, "now": None})
        stage = read_stage_storage(DATA, coordinates=coords, trusted_now=None)
        if verified != {"envelope_sha256": stage.envelope_sha256, "staged_at": stage.staged_at}:
            raise ValueError("stage_changed")
        archive_stage_storage(DATA, coordinates=coords, stage=stage, now=request["now"])
        return {"archived": True}
    if operation in {"read-stage", "verify-owner", "consume-nonce"}:
        if coords is None:
            raise ValueError("maintenance_coordinates_required")
        if operation == "consume-nonce":
            return {"consumed": consume_nonce_storage(DATA, request["nonce"], coords)}
        stage = read_stage_storage(DATA, coordinates=coords, trusted_now=request["now"])
        if operation == "verify-owner":
            from boca_socios.host_telegram_owner_stage import (
                _OWNER_PERMISSIONS,
                _read_owner_public_file,
            )
            from boca_socios.panel.passkey import PasskeyOwnerAuthentication
            from boca_socios.telegram_owner_webauthn import verify_stage_owner_witness

            credential = _read_owner_public_file(OWNER, "credential_id", 1024)
            public = _read_owner_public_file(OWNER, "public_key.der", 4096)
            if hashlib.sha256(credential + b"\0" + public).hexdigest() != coords.owner_digest:
                raise ValueError("owner_drift")
            verifier = PasskeyOwnerAuthentication(
                credential_id=credential,
                public_key_der=public,
                rp_id="localhost",
                origin="http://localhost:8443",
                owner_subject=request["owner_subject"],
                permissions=_OWNER_PERMISSIONS,
            )
            if stage.owner_witness is None or not verify_stage_owner_witness(
                stage.owner_witness, stage.envelope, verifier, staged_at=stage.staged_at
            ):
                raise ValueError("owner_unverified")
            return {"envelope_sha256": stage.envelope_sha256, "staged_at": stage.staged_at}
        return {
            "stage_id": stage.stage_id,
            "staged_at": stage.staged_at,
            "envelope_sha256": stage.envelope_sha256,
            "recipient_fingerprint": stage.recipient_fingerprint,
            "file_identity": list(stage.file_identity),
            "envelope": bootstrap._b64(stage.envelope),
            "owner_witness": None
            if stage.owner_witness is None
            else witness_document(stage.owner_witness),
        }
    if operation in {"unseal", "seal"}:
        recipient = bootstrap.RecipientReceipt(**request["recipient"])
        if operation == "seal":
            return {
                "envelope": bootstrap._b64(
                    bootstrap.seal_for_recipient(recipient, request["token"], request["chat"])
                )
            }
        from boca_socios.telegram_pairing_bootstrap import unseal_pairing

        parent = bootstrap._directory(CUSTODY, bootstrap.UID)
        try:
            private = bootstrap._read(parent, bootstrap.PRIVATE_KEY, bootstrap.UID, maximum=32)
            if bootstrap._receipt(private, "PREPARED") != recipient:
                raise ValueError("recipient_changed")
            token, code = unseal_pairing(
                bootstrap._unb64(request["envelope"], maximum=4096), private, recipient
            )
            return {"token": token.decode("ascii"), "code": code}
        finally:
            os.close(parent)
    if operation in {"install-v2", "verify-v2"}:
        from boca_socios.telegram_pairing_install import install_v2_plan, verify_v2_custody
        from boca_socios.telegram_pairing_resolver import PairingInstallPlan, PairingInstallReceipt

        if operation == "install-v2":
            plan = PairingInstallPlan(
                PairingInstallReceipt(**request["receipt"]),
                bootstrap._unb64(request["envelope"], maximum=4096),
            )
            return asdict(
                install_v2_plan(
                    CUSTODY, plan, expected_source_sha=request["source_sha"], now=request["now"]
                )
            )
        return asdict(verify_v2_custody(CUSTODY, expected_source_sha=request["source_sha"]))
    if operation == "publish-recipient":
        from boca_socios.panel.telegram_recipient import publish_prepared_recipient

        publish_prepared_recipient(
            DATA,
            bootstrap.RecipientReceipt(**request["recipient"]),
            source_sha=request["source_sha"],
            installation_fingerprint=request["installation_fingerprint"],
        )
        return {"published": True}
    raise ValueError("maintenance_operation_unverified")


def main() -> int:
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in MOUNTS:
            return 2
        raw = sys.stdin.buffer.read(MAX_FRAME + 1)
        if not 0 < len(raw) <= MAX_FRAME:
            return 2
        value = json.loads(raw, object_pairs_hook=bootstrap._unique)
        result = bootstrap._canonical(execute(sys.argv[1], value))
        if not 0 < len(result) <= MAX_FRAME:
            return 2
        sys.stdout.buffer.write(result)
        return 0
    except Exception:
        # No stderr, traceback, token, chat ID, owner assertion or ciphertext.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
