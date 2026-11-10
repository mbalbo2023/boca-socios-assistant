"""One-incident Boca Cutover A stage recovery after independently proved old-ID restoration.

The host entry point is effectful but *only* on the authenticated, uncommitted
``cutover-a-<incident>`` directory.  It never invokes a Docker mutation, changes
the live Compose inode, or treats this cleanup as permission to retry a cutover.

Transport this reviewed script, its READ_ONLY postapply observer and the
reviewed ``boca_socios`` source package together via the protected workflow.
Invoke ``python3 -m scripts.host_cutover_stage_recovery host INCIDENT PREPARE``
with both package roots on PYTHONPATH.  The runner uses ``verify`` and receives
only the bounded, canonical host JSON receipt on stdin.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_cutover_stage as stage
from scripts import host_cutover_postapply_reconcile as observer

VERSION = "boca-stage-recovery-v1"
MAX_RECEIPT = 2048
FIELDS = {
    "version",
    "incident_run_id",
    "prepare_run_id",
    "state",
    "stage_before",
    "stage_after",
    "legacy_controller_id",
    "legacy_source_sha",
    "legacy_compose_sha",
    "terminal_state",
    "cleanup",
    "root_entries_after",
    "docker_writes",
    "foreign_resources_touched",
    "go_for_retry",
}


class StageRecoveryError(ValueError):
    """Stage recovery identity or physical postcondition could not be proven."""


def _verified_records(incident: str) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Authenticate both durable records, including their byte-exact linkage."""
    folder = observer._private_home() / observer.RECEIPT_DIR
    intent_raw = observer._read_private(f"boca-cutover-a-intent-{incident}.json", directory=folder)
    result_raw = observer._read_private(f"boca-cutover-a-result-{incident}.json", directory=folder)
    intent = observer._record(intent_raw, incident, kind="intent")
    result = observer._record(result_raw, incident, kind="result")
    if intent is None or result is None or intent_raw is None or result_raw is None:
        raise StageRecoveryError("durable attempt identity is absent")
    if (
        result["intent_sha256"] != hashlib.sha256(intent_raw).hexdigest()
        or result["legacy_id"] != intent["legacy_id"]
        or result["legacy_source_sha"] != intent["legacy_source_sha"]
        or result["target_source_sha"] != intent["target_source_sha"]
        or intent["origin"] != "http://localhost:8443"
        or result["state"] != "NO_GO"
        or result["cleanup"] != "INDETERMINATE"
        or result["original_restored"] is not True
        or result["irreversible_commit_started"] is not False
    ):
        raise StageRecoveryError("only an uncommitted, recovered original is eligible")
    if (
        not observer.IDENT.fullmatch(str(intent["legacy_compose_sha"]))
        or not observer.SOURCE.fullmatch(str(intent["legacy_source_sha"]))
        or not observer.SOURCE.fullmatch(str(intent["target_source_sha"]))
        or not stage.CONTROLLER.fullmatch(str(intent["target_image_ref"]))
        or not stage.WORKER.fullmatch(str(intent["browser_image_ref"]))
        or any(
            not observer.IDENT.fullmatch(str(intent[key]))
            for key in ("target_compose_sha", "overlay_sha", "seccomp_sha")
        )
    ):
        raise StageRecoveryError("durable reviewed plan has invalid coordinates")
    return (
        intent,
        result,
        hashlib.sha256(intent_raw).hexdigest(),
        hashlib.sha256(result_raw).hexdigest(),
    )


def _safe_snapshot(
    record: dict[str, Any],
    incident: str,
    prepared: str | None,
    legacy: str,
    revision: str,
    *,
    stage_present: bool,
    source_sha: str | None = None,
) -> None:
    """Prove exactly one healthy original; no Boca candidate or browser worker."""
    expected_stage = "PRESENT" if stage_present else "ABSENT"
    if (
        record.get("version")
        != ("boca-postapply-reconcile-v2" if source_sha else "boca-postapply-reconcile-v1")
        or record.get("incident_run_id") != incident
        or record.get("prepare_run_id") != prepared
        or record.get("intent") != "PRESENT"
        or record.get("result") != "PRESENT"
        or record.get("terminal_state") != "NO_GO"
        or record.get("cleanup") != "INDETERMINATE"
        or record.get("original_restored") is not True
        or record.get("commit_started") is not False
        or record.get("legacy_id") != legacy
        or record.get("stage") != expected_stage
        or record.get("promotion_intent") != "ABSENT"
        or record.get("promotion_result") != "ABSENT"
        or record.get("boca_containers") != 1
        or record.get("port_8443") != "BOCA_CONTROLLER_DOCKER_BOUND"
        or record.get("candidate_controllers") != []
        or record.get("browser_workers") != []
        or record.get("runtime_attested") is not False
        or record.get("go_for_retry") is not False
        or record.get("foreign_resources_touched") is not False
        or (source_sha is not None and record.get("incident_source_sha") != source_sha)
    ):
        raise StageRecoveryError("postapply observer cannot prove a safe Boca singleton")
    original = record.get("original")
    if (
        not isinstance(original, dict)
        or record.get("boca_inventory") != [original]
        or original.get("id") != legacy
        or original.get("service") != "controller"
        or original.get("revision") != revision
        or original.get("running") is not True
        or original.get("health") != "healthy"
        or original.get("port_binding")
        != {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    ):
        raise StageRecoveryError("original exact ID / health / loopback 8443 not proven")
    preflight = record.get("stage_preflight")
    if not isinstance(preflight, dict):
        raise StageRecoveryError("stage root preflight is not a record")
    if stage_present:
        if (
            preflight.get("reason") != "STAGE_ROOT_ENTRIES"
            or preflight.get("root_entries_count") != 2
            or preflight.get("root_entries_expected") is not False
            or preflight.get("plan_hashes_unique") is not True
        ):
            raise StageRecoveryError("expected two-entry stage root not independently observed")
    elif (
        preflight.get("reason") != "STAGE_PREFLIGHT_MATCH"
        or preflight.get("root_entries_count") != 1
        or preflight.get("root_entries_expected") is not True
        or preflight.get("compose_digest_match") is not True
        or preflight.get("compose_legacy_mode_accepted") is not True
        or preflight.get("plan_hashes_unique") is not True
    ):
        raise StageRecoveryError("live singleton Compose not proved after stage removal")


def _stage_identity(incident: str, intent: dict[str, Any]) -> None:
    """Authenticate exact root entry, marker, inode, and each staged reviewed SHA.

    This additionally protects against READ_ONLY ``root_entries_count=2``
    concealing an unrelated second directory or symlink.
    """
    root, child, marker = stage._authenticated_stage(incident, intent["legacy_compose_sha"])
    try:
        expected = {
            "attempt_id": incident,
            "legacy_controller_id": intent["legacy_id"],
            "legacy_source_sha": intent["legacy_source_sha"],
            "legacy_compose_sha": intent["legacy_compose_sha"],
            "target_source_sha": intent["target_source_sha"],
            "target_image": intent["target_image_ref"],
            "browser_image": intent["browser_image_ref"],
            "target_compose_sha": intent["target_compose_sha"],
            "overlay_compose_sha": intent["overlay_sha"],
            "seccomp_sha": intent["seccomp_sha"],
        }
        if any(marker.get(key) != value for key, value in expected.items()):
            raise StageRecoveryError("stage marker differs from durable reviewed attempt")
        entries = set(os.listdir(child))
        if (
            not {stage.MARKER}
            <= entries
            <= {stage.MARKER, *(name for name, _ in stage.FILES.values())}
        ):
            raise StageRecoveryError("stage contains unreviewed or partial entries")
        for filename, sha_field in stage.FILES.values():
            if filename in entries:
                stage._read_file(child, filename, str(marker[sha_field]), limit=stage.MAX_FILE)
        # _authenticated_stage required the *exact* root entry set, including
        # the exact incident ID, and checked the original Compose SHA+inode.
    finally:
        os.close(child)
        os.close(root)


def _recover(incident: str, prepared: str | None, source_sha: str | None) -> dict[str, Any]:
    """Single deliberate guarded removal; never promote or retry Cutover A."""
    if (
        not observer.RUN.fullmatch(incident)
        or (
            source_sha is None
            and (prepared is None or not observer.RUN.fullmatch(prepared) or incident == prepared)
        )
        or (
            source_sha is not None
            and (prepared is not None or not observer.SOURCE.fullmatch(source_sha))
        )
    ):
        raise StageRecoveryError("incident or prepare run ID invalid")
    with cleanup.protected_boca_job_lease(incident) as lease:
        cleanup.verify_protected_boca_job_lease(lease, incident)
        intent, _result, intent_digest, result_digest = _verified_records(incident)
        if source_sha is not None and intent["target_source_sha"] != source_sha:
            raise StageRecoveryError("incident source does not match durable intent")

        def observe() -> dict[str, Any]:
            return (
                observer._host(incident, prepared, source_sha=source_sha)
                if source_sha
                else observer._host(incident, prepared)
            )

        before = observe()
        _safe_snapshot(
            before,
            incident,
            prepared,
            intent["legacy_id"],
            intent["legacy_source_sha"],
            stage_present=True,
            source_sha=source_sha,
        )
        _stage_identity(incident, intent)
        # Fresh second runtime read immediately before the bounded effect.
        immediate = observe()
        _safe_snapshot(
            immediate,
            incident,
            prepared,
            intent["legacy_id"],
            intent["legacy_source_sha"],
            stage_present=True,
            source_sha=source_sha,
        )
        if immediate != before:
            raise StageRecoveryError("Boca physical observation changed before cleanup")
        cleanup.verify_protected_boca_job_lease(lease, incident)
        stage.discard_recovered(incident, intent["legacy_compose_sha"])
        after = observe()
        _safe_snapshot(
            after,
            incident,
            prepared,
            intent["legacy_id"],
            intent["legacy_source_sha"],
            stage_present=False,
            source_sha=source_sha,
        )
        if after["boca_inventory"] != before["boca_inventory"]:
            raise StageRecoveryError("Boca singleton changed across stage cleanup")
        _, _, intent_digest_after, result_digest_after = _verified_records(incident)
        if (intent_digest_after, result_digest_after) != (intent_digest, result_digest):
            raise StageRecoveryError("durable Cutover receipts changed across stage cleanup")
        receipt = {
            "version": "boca-stage-recovery-v2" if source_sha else VERSION,
            "incident_run_id": incident,
            "prepare_run_id": prepared,
            "state": "STAGE_CLEARED",
            "stage_before": "PRESENT",
            "stage_after": "ABSENT",
            "legacy_controller_id": intent["legacy_id"],
            "legacy_source_sha": intent["legacy_source_sha"],
            "legacy_compose_sha": intent["legacy_compose_sha"],
            "terminal_state": "NO_GO",
            "cleanup": "INDETERMINATE",
            "root_entries_after": 1,
            "docker_writes": 0,
            "foreign_resources_touched": False,
            "go_for_retry": False,
        }
        if source_sha is not None:
            receipt["incident_source_sha"] = source_sha
        return receipt


def recover(incident: str, prepared: str) -> dict[str, Any]:
    return _recover(incident, prepared, None)


def recover_v3(incident: str, source_sha: str) -> dict[str, Any]:
    if incident == observer.R904:
        raise StageRecoveryError("incident requires its exact controller recovery")
    return _recover(incident, None, source_sha)


def _verify_runner(
    raw: bytes, incident: str, prepared: str | None, source_sha: str | None
) -> dict[str, Any]:
    """Validate only successful, canonical, bounded host receipts."""
    if (
        not observer.RUN.fullmatch(incident)
        or (
            source_sha is None
            and (prepared is None or not observer.RUN.fullmatch(prepared) or incident == prepared)
        )
        or (
            source_sha is not None
            and (prepared is not None or not observer.SOURCE.fullmatch(source_sha))
        )
        or not 0 < len(raw) <= MAX_RECEIPT
    ):
        raise StageRecoveryError("runner identity or receipt bounds invalid")
    try:
        record = json.loads(raw.decode("ascii"), object_pairs_hook=stage._unique)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise StageRecoveryError("runner receipt JSON invalid") from exc
    if (
        not isinstance(record, dict)
        or set(record) != (FIELDS | {"incident_source_sha"} if source_sha else FIELDS)
        or record.get("version") != ("boca-stage-recovery-v2" if source_sha else VERSION)
        or (source_sha is not None and record.get("incident_source_sha") != source_sha)
        or record.get("incident_run_id") != incident
        or record.get("prepare_run_id") != prepared
        or record.get("state") != "STAGE_CLEARED"
        or record.get("stage_before") != "PRESENT"
        or record.get("stage_after") != "ABSENT"
        or not stage.CONTAINER.fullmatch(str(record.get("legacy_controller_id")))
        or not stage.SOURCE.fullmatch(str(record.get("legacy_source_sha")))
        or not stage.SHA.fullmatch(str(record.get("legacy_compose_sha")))
        or record.get("terminal_state") != "NO_GO"
        or record.get("cleanup") != "INDETERMINATE"
        or type(record.get("root_entries_after")) is not int
        or record.get("root_entries_after") != 1
        or type(record.get("docker_writes")) is not int
        or record.get("docker_writes") != 0
        or record.get("foreign_resources_touched") is not False
        or record.get("go_for_retry") is not False
        or observer._canonical(record) + b"\n" != raw
    ):
        raise StageRecoveryError("runner host stage receipt contract invalid")
    return record


def verify_runner(raw: bytes, incident: str, prepared: str) -> dict[str, Any]:
    return _verify_runner(raw, incident, prepared, None)


def verify_runner_v3(raw: bytes, incident: str, source_sha: str) -> dict[str, Any]:
    if incident == observer.R904:
        raise StageRecoveryError("incident requires its exact controller recovery")
    return _verify_runner(raw, incident, None, source_sha)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or args[0] not in ("host", "verify", "host-v3", "verify-v3"):
        print("BOCA_STAGE_RECOVERY state=NO_GO reason=INPUT", file=sys.stderr)
        return 3
    mode, incident, prepared = args
    try:
        if mode in ("host", "host-v3"):
            result = (
                recover_v3(incident, prepared) if mode == "host-v3" else recover(incident, prepared)
            )
            receipt = observer._canonical(result) + b"\n"
            if len(receipt) > MAX_RECEIPT:
                raise StageRecoveryError("host receipt exceeds bound")
            sys.stdout.buffer.write(receipt)
        else:
            raw = sys.stdin.buffer.read(MAX_RECEIPT + 1)
            record = (
                verify_runner_v3(raw, incident, prepared)
                if mode == "verify-v3"
                else verify_runner(raw, incident, prepared)
            )
            print(
                "BOCA_STAGE_RECOVERY state=STAGE_CLEARED"
                f" incident={record['incident_run_id']}"
                f" legacy={record['legacy_controller_id']}"
                " compose=UNCHANGED docker_writes=0"
                " foreign_resources_touched=false retry=NO_GO"
            )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        cleanup.CleanupError,
        stage.StageError,
        observer.ReconcileError,
    ):
        print("BOCA_STAGE_RECOVERY state=NO_GO reason=UNVERIFIED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
