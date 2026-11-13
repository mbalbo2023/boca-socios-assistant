"""R278: fail-closed, incident-scoped immutable physical journal evidence."""

from __future__ import annotations

import hashlib
import json

import pytest

from boca_socios import host_boca_park_incident_readonly as forensic

OLD_SHA = "b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72"
CONTROLLER = "a" * 64
WORKER = "b" * 64
CONTROL = "c" * 64


def _canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii")


def _journal() -> tuple[bytes, bytes, bytes]:
    plan = {
        "attempt_id": forensic.INCIDENT,
        "observation_run_id": "43478093888",
        "old_attempt_id": "43237528968",
        "old_source_sha": OLD_SHA,
        "old_controller_id": CONTROLLER,
        "old_worker_id": WORKER,
        "old_controller_image_id": "sha256:" + "d" * 64,
        "old_worker_image_id": "sha256:" + "e" * 64,
        "new_source_sha": forensic.INCIDENT_SOURCE_SHA,
        "release_run_id": "43478524966",
        "controller_ref": forensic.CONTROLLER_REF,
        "worker_ref": forensic.WORKER_REF,
    }
    witness = {
        "observation_run_id": plan["observation_run_id"],
        "old_attempt_id": plan["old_attempt_id"],
        "old_source_sha": OLD_SHA,
        "controller_id": CONTROLLER,
        "worker_id": WORKER,
        "controller_image_id": plan["old_controller_image_id"],
        "worker_image_id": plan["old_worker_image_id"],
        "control_inode_sha256": CONTROL,
        "retained": {},
    }
    evidence = _canonical(
        {
            "version": "boca-successor-pair-intent-evidence-v1",
            "plan": plan,
            "witness": witness,
            "release": {
                "source_sha": forensic.INCIDENT_SOURCE_SHA,
                "release_run_id": forensic.RELEASE_RUN,
                "controller_ref": forensic.CONTROLLER_REF,
                "worker_ref": forensic.WORKER_REF,
                "controller_manifest_sha256": "2" * 64,
                "paired_manifest_sha256": "3" * 64,
            },
        }
    )
    intent = _canonical(
        {
            "attempt": forensic.INCIDENT,
            "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
            "old_controller": CONTROLLER,
            "old_worker": WORKER,
            "old_source": OLD_SHA,
            "new_source": forensic.INCIDENT_SOURCE_SHA,
            "release": plan["release_run_id"],
        }
    )
    terminal = (
        b"BOCA_PAIR_UPGRADE "
        + _canonical(
            {
                "schema": 1,
                "attempt_id": forensic.INCIDENT,
                "state": "NO_GO",
                "cleanup": "INDETERMINATE",
                "old_restored": False,
                "commit_started": False,
                "controller_id": None,
                "worker_id": None,
                "failed_phase": "CREATE_WORKER",
            }
        )
        + b"\n"
    )
    return evidence, intent, terminal


def test_verified_original_journal_pins_exact_ids_and_inode() -> None:
    pins = forensic.verify_journal(*_journal(), commit_present=False)
    assert pins.old_controller_id == CONTROLLER
    assert pins.old_worker_id == WORKER
    assert pins.control_inode_sha256 == CONTROL
    assert pins.old_source_sha == OLD_SHA


@pytest.mark.parametrize(
    "attack", ["commit", "intent_hash", "mismatched_witness", "terminal_success", "empty_release"]
)
def test_forensic_journal_rejects_commit_and_identity_drift(attack: str) -> None:
    evidence, intent, terminal = _journal()
    if attack == "intent_hash":
        intent = intent.replace(b'"evidence_sha256":"', b'"evidence_sha256":"0', 1)
    elif attack == "mismatched_witness":
        evidence = evidence.replace(
            b'"control_inode_sha256":"' + CONTROL.encode(),
            b'"control_inode_sha256":"' + ("e" * 64).encode(),
        )
    elif attack == "terminal_success":
        terminal = terminal.replace(b'"state":"NO_GO"', b'"state":"ACCEPTED"')
    elif attack == "empty_release":
        evidence = evidence.replace(
            b'"release":'
            + _canonical(
                {
                    "source_sha": forensic.INCIDENT_SOURCE_SHA,
                    "release_run_id": forensic.RELEASE_RUN,
                    "controller_ref": forensic.CONTROLLER_REF,
                    "worker_ref": forensic.WORKER_REF,
                    "controller_manifest_sha256": "2" * 64,
                    "paired_manifest_sha256": "3" * 64,
                }
            ),
            b'"release":{}',
        )
    with pytest.raises(forensic.ParkIncidentNoGo):
        forensic.verify_journal(evidence, intent, terminal, commit_present=attack == "commit")


def _record(cid: str, role: str, *, parked: bool = True) -> dict[str, object]:
    return {
        "Id": cid,
        "Image": "sha256:" + ("d" if role == "controller" else "e") * 64,
        "Name": f"/boca-socios-{role if role == 'controller' else 'browser-worker'}-legacy-{forensic.INCIDENT}"
        if parked
        else f"/boca-socios-{role}-1",
        "State": {
            "Status": "exited" if role == "controller" else "created",
            "Running": False,
            "Pid": 0,
            "ExitCode": 0,
        },
        "HostConfig": {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
        "Config": {
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": role,
                "boca.socios.browser-ipc-attempt": "43237528968",
                "org.opencontainers.image.revision": OLD_SHA,
            }
        },
    }


def test_only_original_parked_pair_is_recognized() -> None:
    pins = forensic.verify_journal(*_journal(), commit_present=False)
    records = [_record(CONTROLLER, "controller"), _record(WORKER, "browser-worker")]
    forensic.verify_parked_containers(pins, [CONTROLLER, WORKER], records)
    records[0]["Name"] = "/boca-socios-controller-1"
    with pytest.raises(forensic.ParkIncidentNoGo):
        forensic.verify_parked_containers(pins, [CONTROLLER, WORKER], records)


def test_no_foreign_or_candidate_cid_can_be_silently_accepted() -> None:
    pins = forensic.verify_journal(*_journal(), commit_present=False)
    records = [_record(CONTROLLER, "controller"), _record(WORKER, "browser-worker")]
    with pytest.raises(forensic.ParkIncidentNoGo):
        forensic.verify_parked_containers(pins, [CONTROLLER, WORKER, "3" * 64], records)


def test_public_failure_preserves_fixed_stage_without_host_details() -> None:
    for category in (
        "HOST_IDENTITY_UNVERIFIED",
        "JOURNAL_UNVERIFIED",
        "PARKED_BINDING_UNVERIFIED",
        "PAIR_UNVERIFIED",
        "RETAINED_NAMES_UNVERIFIED",
        "DOUBLE_READ_DRIFT",
    ):
        raw = (
            f"BOCA_PARK_INCIDENT_READONLY state=NO_GO reason={category} "
            "observer_writes=0 deploy=NO_GO\n"
        ).encode("ascii")
        assert forensic.classify_failure(raw).endswith("observer_writes=0 deploy=NO_GO")
    with pytest.raises(forensic.ParkIncidentNoGo):
        forensic.classify_failure(raw.replace(b"JOURNAL", b"PRIVATE_HOST_ENV") + b"secret")
