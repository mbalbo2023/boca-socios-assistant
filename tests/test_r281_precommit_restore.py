"""Exact precommit recovery contract for the parked #1085 Boca incident."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from boca_socios import host_boca_pair_precommit_restore as recovery
from boca_socios import host_boca_park_incident_readonly as incident
from boca_socios import host_on_demand_replace as replace
from boca_socios import host_on_demand_service as service
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation


def test_restore_uses_new_lease_without_forging_failed_attempt() -> None:
    old = Mock()
    lease = Mock()
    home = Path("/unused/boca-home")
    parked = Mock()
    marker = Mock()
    with (
        patch.object(replace, "_verify_lease") as guard,
        patch.object(replace.service, "_home", return_value=home),
        patch.object(replace, "_intended", return_value=(parked, marker)),
        patch.object(replace.service, "_present", side_effect=[True, False]),
        patch.object(replace, "_restore_binding_verified") as restore,
    ):
        replace.restore_binding_precommit_recovery(old, recovery.INCIDENT, "999", lease)
    guard.assert_called_once_with(lease, "999")
    restore.assert_called_once_with(
        old, recovery.INCIDENT, lease, allow_candidate_compensation=False
    )


def test_restore_refuses_same_incident_lease() -> None:
    with pytest.raises(ValueError):
        replace.restore_binding_precommit_recovery(
            Mock(), recovery.INCIDENT, recovery.INCIDENT, Mock()
        )


@pytest.mark.parametrize("state", ["RECOVERED_OLD_PAIR", "NO_GO", "INDETERMINATE"])
def test_receipt_closed_vocabulary(state: str) -> None:
    receipt = recovery.encode("999", state)
    assert recovery.verify(receipt, "999") == receipt
    with pytest.raises(ValueError):
        recovery.verify(receipt[:-1] + b" \n", "999")


def test_receipt_refuses_original_attempt() -> None:
    with pytest.raises(ValueError):
        recovery.encode(recovery.INCIDENT, "RECOVERED_OLD_PAIR")


def test_original_parked_binding_uses_host_sqlite_path_not_container_path() -> None:
    home = Path("/test-only/boca-deploy")
    pins = incident.JournalPins(
        "43217075287",
        "b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72",
        "c" * 64,
        "d" * 64,
        "sha256:" + "1" * 64,
        "sha256:" + "2" * 64,
        "f" * 64,
        "43451486396",
    )
    old = OnDemandInstallation(
        installation_run_id=pins.old_attempt_id,
        source_sha=pins.old_source_sha,
        controller_id=pins.old_controller_id,
        controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        worker_id=pins.old_worker_id,
        worker_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64,
        database_path=home / service._DB,
        pair=ReviewedInstalledPair(pins.old_attempt_id, "3" * 64, "4" * 64),
    )
    retained = {
        "ipc_creator_attempt": "43217075287",
        "ipc_inode_sha256": "1" * 64,
        "site_creator_attempt": "43217075287",
        "site_inode_sha256": "2" * 64,
        "egress_creator_attempt": "43217075287",
        "egress_id": "3" * 64,
    }
    with (
        patch.object(
            incident, "_read_staged", side_effect=[b"evidence", b"intent", b"terminal"] * 2
        ),
        patch.object(incident, "verify_journal", return_value=pins),
        patch.object(incident, "_commit_present", return_value=False),
        patch.object(incident, "_json", return_value={"witness": {"retained": retained}}),
        patch.object(service, "_home", return_value=home),
        patch.object(service, "_read", return_value=b"binding"),
        patch.object(service, "_decode", return_value=(old, "0" * 64)),
        patch.object(replace, "_intended"),
        patch.object(replace, "_historic"),
    ):
        assert recovery._original()[1] == old
        wrong = OnDemandInstallation(
            installation_run_id=old.installation_run_id,
            source_sha=old.source_sha,
            controller_id=old.controller_id,
            controller_image=old.controller_image,
            worker_id=old.worker_id,
            worker_image=old.worker_image,
            database_path=Path("/data/boca.sqlite3"),
            pair=old.pair,
        )
        with patch.object(service, "_decode", return_value=(wrong, "0" * 64)):
            with pytest.raises(recovery.RecoveryNoGo):
                recovery._original()


def test_parked_preflight_refuses_extra_daemon_container_before_claim() -> None:
    pins = Mock()
    pins.old_controller_id, pins.old_worker_id = "a" * 64, "b" * 64
    observed = {
        "state": "OBSERVED_PARKED",
        "health": "UNAVAILABLE",
        "restore_authorized": False,
        "control_inode_sha256": "c" * 64,
        "controller_id": "a" * 64,
        "worker_id": "b" * 64,
    }
    pins.control_inode_sha256 = "c" * 64
    with (
        patch.object(incident, "_require_owner"),
        patch.object(incident, "observe_host", return_value=observed),
        patch.object(recovery, "_original", return_value=(pins, Mock(), "d" * 64, Mock())),
        patch.object(
            recovery.host, "_browser_docker_ids", return_value={"a" * 64, "b" * 64, "e" * 64}
        ),
        patch.object(recovery, "_resource_custody") as resources,
    ):
        with pytest.raises(recovery.RecoveryNoGo):
            recovery.preflight("999")
    resources.assert_not_called()


def test_parked_systemd_rejects_canonical_root_before_any_recovery() -> None:
    with (
        patch.object(service, "_home", return_value=Path("/test-only/boca-deploy")),
        patch.object(service, "_present", return_value=True),
        patch.object(service, "_unit_dir") as unit_dir,
    ):
        with pytest.raises(recovery.RecoveryNoGo):
            recovery._parked_systemd()
    unit_dir.assert_not_called()


def test_parked_systemd_refuses_stale_socket_before_durable_claim(tmp_path: Path) -> None:
    parked, _ = replace._name(tmp_path, recovery.INCIDENT)
    (parked / "socket").mkdir(parents=True)
    (parked / "socket" / service._SOCKET_NAME).touch()
    with (
        patch.object(service, "_home", return_value=tmp_path),
        patch.object(service, "_unit_dir") as unit_dir,
    ):
        with pytest.raises(recovery.RecoveryNoGo):
            recovery._parked_systemd()
    unit_dir.assert_not_called()


def test_preflight_refuses_occupied_loopback_even_if_http_unavailable() -> None:
    pins = Mock()
    pins.old_controller_id, pins.old_worker_id = "a" * 64, "b" * 64
    pins.control_inode_sha256 = "c" * 64
    observed = {
        "state": "OBSERVED_PARKED",
        "health": "UNAVAILABLE",
        "restore_authorized": False,
        "control_inode_sha256": pins.control_inode_sha256,
        "controller_id": pins.old_controller_id,
        "worker_id": pins.old_worker_id,
    }
    with (
        patch.object(incident, "_require_owner"),
        patch.object(incident, "observe_host", return_value=observed),
        patch.object(recovery, "_original", return_value=(pins, Mock(), "d" * 64, Mock())),
        patch.object(
            recovery.host,
            "_browser_docker_ids",
            return_value={pins.old_controller_id, pins.old_worker_id},
        ),
        patch.object(recovery.host, "_browser_port_free", side_effect=OSError("occupied")),
        patch.object(recovery, "_parked_systemd") as systemd,
    ):
        with pytest.raises(recovery.RecoveryNoGo):
            recovery.preflight("999")
    systemd.assert_not_called()


def test_retained_resource_inode_drift_rejects_before_mounts_and_docker_start() -> None:
    pins, old, resources = Mock(), Mock(), Mock()
    resources.ipc_inode_sha256, resources.site_inode_sha256 = "a" * 64, "b" * 64
    with (
        patch.object(recovery.host, "_validate_data_volume"),
        patch.object(recovery.host, "_validate_key_volume"),
        patch.object(recovery.host, "_validate_owner_volume"),
        patch.object(incident, "_retained_names_present"),
        patch.object(
            incident,
            "_docker",
            side_effect=[
                "\n".join(sorted(recovery._VOLUMES)),
                "bridge\nhost\nnone\n" + recovery._PRIVATE + "\n" + recovery._EGRESS,
            ],
        ),
        patch.object(recovery.retained, "_identity", return_value="c" * 64),
        patch.object(recovery.host, "_browser_inspect_record") as inspect,
    ):
        with pytest.raises(recovery.RecoveryNoGo):
            recovery._resource_custody(pins, resources, old)
    inspect.assert_not_called()


def test_recovery_docker_only_renames_two_exact_predecessors_and_starts_controller() -> None:
    controller, worker = "a" * 64, "b" * 64
    pins, old = Mock(), Mock()
    pins.old_controller_id, pins.old_worker_id = controller, worker
    names = {
        controller: "/boca-socios-controller-legacy-" + recovery.INCIDENT,
        worker: "/boca-socios-browser-worker-legacy-" + recovery.INCIDENT,
    }
    actions: list[tuple[str, ...]] = []

    def inspect(cid: str) -> dict[str, object]:
        return {"Id": cid, "Name": names[cid], "State": {"Running": False}}

    def run(*command: str, **_kwargs: object) -> str:
        actions.append(command)
        if command[1] == "rename":
            names[command[2]] = "/" + command[3]
        return command[2] if command[1] in ("rename", "start") else command[3]

    with (
        patch.object(recovery.host, "_browser_docker_ids", return_value={controller, worker}),
        patch.object(recovery.host, "_browser_inspect_record", side_effect=inspect),
        patch.object(recovery.host, "_run", side_effect=run),
        patch.object(recovery.host, "_browser_wait_healthy") as wait_healthy,
        patch.object(service, "_home", return_value=Path("/test-only/boca-deploy")),
        patch.object(service, "_verified_installation", return_value=old),
    ):
        recovery._restore_docker(old, pins)
    assert actions == [
        ("docker", "rename", controller, "boca-socios-controller-1"),
        ("docker", "rename", worker, "boca-socios-browser-worker-1"),
        ("docker", "start", controller),
        ("docker", "update", "--restart=unless-stopped", controller),
    ]
    wait_healthy.assert_called_once_with(controller)


def test_restore_preflight_failure_does_not_claim_or_mutate() -> None:
    with (
        patch.object(recovery.cleanup, "protected_boca_job_lease") as lease_context,
        patch.object(recovery.cleanup, "verify_protected_boca_job_lease"),
        patch.object(recovery, "preflight", side_effect=recovery.RecoveryNoGo("preflight")),
        patch.object(recovery, "_claim") as claim,
        patch.object(recovery.replace, "restore_binding_precommit_recovery") as restore,
    ):
        lease_context.return_value.__enter__.return_value = Mock()
        with pytest.raises(recovery.RecoveryNoGo):
            recovery.restore("999")
    claim.assert_not_called()
    restore.assert_not_called()


def test_second_preflight_drift_refuses_before_claim() -> None:
    first = Mock()
    second = Mock()
    with (
        patch.object(recovery.cleanup, "protected_boca_job_lease") as lease_context,
        patch.object(recovery.cleanup, "verify_protected_boca_job_lease"),
        patch.object(recovery, "preflight", side_effect=[first, second]),
        patch.object(recovery, "_claim") as claim,
    ):
        lease_context.return_value.__enter__.return_value = Mock()
        with pytest.raises(recovery.RecoveryNoGo):
            recovery.restore("999")
    claim.assert_not_called()


def test_after_claim_failure_is_indeterminate_with_no_retry() -> None:
    witness = Mock()
    witness.old = Mock()
    witness.pins = Mock()
    with (
        patch.object(recovery.cleanup, "protected_boca_job_lease") as lease_context,
        patch.object(recovery.cleanup, "verify_protected_boca_job_lease"),
        patch.object(recovery, "preflight", return_value=witness),
        patch.object(recovery, "_claim") as claim,
        patch.object(recovery.replace, "restore_binding_precommit_recovery", side_effect=OSError()),
        patch.object(recovery, "_terminal") as terminal,
    ):
        lease_context.return_value.__enter__.return_value = Mock()
        receipt = recovery.restore("999")
    assert b'"state":"INDETERMINATE"' in receipt
    claim.assert_called_once()
    terminal.assert_called_once_with("999", "INDETERMINATE")


def test_claim_ack_failure_is_indeterminate_without_restore() -> None:
    witness = Mock()
    with (
        patch.object(recovery.cleanup, "protected_boca_job_lease") as lease_context,
        patch.object(recovery.cleanup, "verify_protected_boca_job_lease"),
        patch.object(recovery, "preflight", return_value=witness),
        patch.object(recovery, "_claim", side_effect=OSError("uncertain fsync")),
        patch.object(recovery.replace, "restore_binding_precommit_recovery") as restore,
    ):
        lease_context.return_value.__enter__.return_value = Mock()
        receipt = recovery.restore("999")
    assert b'"state":"INDETERMINATE"' in receipt
    restore.assert_not_called()
