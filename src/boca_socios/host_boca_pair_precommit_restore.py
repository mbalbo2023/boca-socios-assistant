"""R281 fixed #1085 PRECOMMIT recovery; no new deploy, Docker pull or worker start.

One fresh, authenticated Boca rootless lease; double full preflight; durable
O_EXCL claim keyed to the failed incident; only exact predecessor IDs and
the original parked binding may be restored. Never replay the failed APPLY.
The old journal is immutable, and ambiguity after claim is INDETERMINATE.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_park_incident_readonly as incident
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_cutover_stage as stage
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_replace as replace
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_upgrade_adapters import ResourcePins
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

INCIDENT = incident.INCIDENT
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SOURCE = re.compile(r"[0-9a-f]{40}\Z")
_JOURNAL = ".boca-pair-upgrade-" + INCIDENT
_RESTORE = ".boca-precommit-restore-" + INCIDENT
_PREFIX = b"BOCA_PRECOMMIT_RESTORE "
_VOLUMES = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_site_config",
        "boca-socios_boca_browser_ipc",
    }
)
_WORKER_VOLUMES = frozenset({"boca-socios_boca_site_config", "boca-socios_boca_browser_ipc"})
_PRIVATE = "boca-socios_boca_private"
_EGRESS = "boca-socios_boca_browser_egress"
_PORTS = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
_FIELDS = frozenset(
    {
        "schema",
        "incident",
        "recovery_run_id",
        "state",
        "cleanup",
        "old_pair_only",
        "worker_started",
        "foreign_resources_touched",
        "ticket_actions",
    }
)


class RecoveryNoGo(ValueError):
    """Closed public refusal; no raw Docker, journal or member data."""


def _fail() -> RecoveryNoGo:
    return RecoveryNoGo("Boca original precommit recovery not proven")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


@dataclass(frozen=True, slots=True, repr=False)
class Preflight:
    pins: incident.JournalPins
    old: OnDemandInstallation
    journal_sha256: str
    resource_pins: ResourcePins
    protected_inodes: tuple[str, str, str]
    observed_old_ids: tuple[str, str]


def _original() -> tuple[incident.JournalPins, OnDemandInstallation, str, ResourcePins]:
    evidence = incident._read_staged(_JOURNAL + ".evidence", limit=4096)
    intent = incident._read_staged(_JOURNAL + ".intent", limit=1024)
    terminal = incident._read_staged(_JOURNAL + ".terminal", limit=1024)
    pins = incident.verify_journal(
        evidence, intent, terminal, commit_present=incident._commit_present()
    )
    witness = incident._json(evidence, limit=4096)["witness"]
    if type(witness) is not dict or type(witness.get("retained")) is not dict:
        raise _fail()
    resources = ResourcePins(**witness["retained"])
    resources.validate()
    home = service._home()
    parked, _ = replace._name(home, INCIDENT)
    old, _ = service._decode(home, service._read(parked / service._BINDING, service._MAX_PLAN))
    if (
        old.installation_run_id != pins.old_attempt_id
        or old.source_sha != pins.old_source_sha
        or old.controller_id != pins.old_controller_id
        or old.worker_id != pins.old_worker_id
        or old.database_path != home / service._DB
    ):
        raise _fail()
    old.pair.require()
    replace._intended(home, old, INCIDENT)
    replace._historic(parked, home, old)
    return pins, old, hashlib.sha256(evidence + intent + terminal).hexdigest(), resources


def _parked_systemd() -> None:
    home = service._home()
    if service._present(home / service._ROOT):
        raise _fail()
    parked, _ = replace._name(home, INCIDENT)
    # The normal installer tolerates a stale control.sock while inspecting a
    # *parked* binding, but its restore path refuses a nonempty socket folder
    # with an inactive unit. Reject that condition before the durable claim.
    if any((parked / "socket").iterdir()):
        raise _fail()
    directory = service._unit_dir(home)
    if (
        any(service._present(directory / name) for name in (service._SOCKET, service._SERVICE))
        or service._enabled(directory, True)
        or service._known(home, directory, service._SOCKET, False)["LoadState"] != "not-found"
        or service._known(home, directory, service._SERVICE, False)["LoadState"] != "not-found"
    ):
        raise _fail()


def _resource_custody(
    pins: incident.JournalPins, resources: ResourcePins, old: OnDemandInstallation
) -> tuple[str, str, str]:
    """Attest historical IPC/SITE hashes, egress id and five volume mounts.

    DATA/KEY/OWNER have no persisted pre-PARK inode hash. Their immutable
    Docker volume labels/old-CID mounts plus stable nofollow inode hashes
    are verified before and after; do not assert a missing historical hash.
    """
    host._validate_data_volume()
    host._validate_key_volume()
    host._validate_owner_volume()
    incident._retained_names_present()
    all_volumes = set(incident._docker("volume", "ls", "-q").splitlines())
    all_networks = set(
        incident._docker("network", "ls", "--format", "{{.Name}}").splitlines()
    )
    if (
        not _VOLUMES <= all_volumes <= (_VOLUMES | {"boca-socios_boca_telegram"})
        or not {_PRIVATE, _EGRESS} <= all_networks
        or not all_networks <= {_PRIVATE, _EGRESS, "bridge", "host", "none"}
    ):
        raise _fail()
    if (
        retained._identity("boca-socios_boca_browser_ipc") != resources.ipc_inode_sha256
        or retained._identity("boca-socios_boca_site_config") != resources.site_inode_sha256
    ):
        raise _fail()
    for name, role, attempt in (
        ("boca-socios_boca_browser_ipc", "boca_browser_ipc", resources.ipc_creator_attempt),
        ("boca-socios_boca_site_config", "boca_site_config", resources.site_creator_attempt),
    ):
        rows = json.loads(incident._docker("volume", "inspect", name))
        if (
            type(rows) is not list
            or len(rows) != 1
            or rows[0].get("Labels")
            != {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.volume": role,
                "boca.socios.browser-ipc-attempt": attempt,
            }
        ):
            raise _fail()
    rows = json.loads(incident._docker("network", "inspect", _EGRESS))
    if (
        type(rows) is not list
        or len(rows) != 1
        or rows[0].get("Id") != resources.egress_id
        or rows[0].get("Labels")
        != {
            "com.docker.compose.project": "boca-socios",
            "com.docker.compose.network": "boca_browser_egress",
            "boca.socios.browser-ipc-attempt": resources.egress_creator_attempt,
        }
    ):
        raise _fail()
    network_rows = json.loads(incident._docker("network", "inspect", _PRIVATE))
    if type(network_rows) is not list or len(network_rows) != 1:
        raise _fail()
    known_networks = frozenset({resources.egress_id, network_rows[0]["Id"]})
    for cid, role, volumes in (
        (pins.old_controller_id, "controller", _VOLUMES),
        (pins.old_worker_id, "browser-worker", _WORKER_VOLUMES),
    ):
        record = host._browser_inspect_record(cid)
        labels = record["Config"]["Labels"]
        expected_ref = old.controller_image if role == "controller" else old.worker_image
        if (
            record["Config"].get("Image") != expected_ref
            or record.get("Image")
            != (pins.old_controller_image_id if role == "controller" else pins.old_worker_image_id)
            or labels.get("com.docker.compose.config-hash") is None
            or pair._safe_mounts(
                record["Mounts"], service=role, valid_volumes=_VOLUMES, historical=False
            )
            != sorted(volumes)
        ):
            raise _fail()
        if role == "controller" and record["HostConfig"].get("PortBindings") != _PORTS:
            raise _fail()
        expected_config_hash = (
            old.pair.controller_config_hash if role == "controller" else old.pair.worker_config_hash
        )
        if labels["com.docker.compose.config-hash"] != expected_config_hash:
            raise _fail()
        network, _ = pair._safe_network(
            record["NetworkSettings"]["Networks"],
            service=role,
            known_ids=known_networks,
            historical=False,
        )
        if network != (_PRIVATE if role == "controller" else _EGRESS):
            raise _fail()
    root = incident._DOCKER_ROOT
    return tuple(
        incident._path_inode(Path(root) / "volumes" / name / "_data")
        for name in ("boca-socios_boca_data", "boca-socios_boca_key", "boca-socios_boca_owner")
    )  # type: ignore[return-value]


def preflight(run_id: str, source_sha: str = incident.INCIDENT_SOURCE_SHA) -> Preflight:
    if _RUN.fullmatch(run_id) is None or _SOURCE.fullmatch(source_sha) is None:
        raise _fail()
    try:
        incident._require_owner()
        observed = incident.observe_host(run_id, source_sha)
        pins, old, journal_digest, resources = _original()
        if (
            observed["state"] != "OBSERVED_PARKED"
            or observed["health"] != "UNAVAILABLE"
            or observed["restore_authorized"] is not False
            or observed["control_inode_sha256"] != pins.control_inode_sha256
            or observed["controller_id"] != pins.old_controller_id
            or observed["worker_id"] != pins.old_worker_id
            or host._browser_docker_ids() != {pins.old_controller_id, pins.old_worker_id}
        ):
            raise _fail()
        # Unavailable HTTP alone does not prove that the loopback port can be
        # republished: a non-HTTP process might be holding it. Bind-probe only.
        host._browser_port_free()
        _parked_systemd()
        inodes = _resource_custody(pins, resources, old)
        if host._browser_docker_ids() != {pins.old_controller_id, pins.old_worker_id}:
            raise _fail()
        _parked_systemd()
        return Preflight(
            pins,
            old,
            journal_digest,
            resources,
            inodes,
            (pins.old_controller_id, pins.old_worker_id),
        )
    except Exception:
        raise _fail() from None


def encode(run_id: str, state: str) -> bytes:
    if (
        type(run_id) is not str
        or _RUN.fullmatch(run_id) is None
        or run_id == INCIDENT
        or state not in ("RECOVERED_OLD_PAIR", "NO_GO", "INDETERMINATE")
    ):
        raise _fail()
    record = {
        "schema": 1,
        "incident": INCIDENT,
        "recovery_run_id": run_id,
        "state": state,
        "cleanup": "ACCEPT" if state == "RECOVERED_OLD_PAIR" else state,
        "old_pair_only": state == "RECOVERED_OLD_PAIR",
        "worker_started": False,
        "foreign_resources_touched": 0,
        "ticket_actions": 0,
    }
    return _PREFIX + _canonical(record) + b"\n"


def verify(raw: bytes, run_id: str) -> bytes:
    if (
        type(raw) is not bytes
        or type(run_id) is not str
        or _RUN.fullmatch(run_id) is None
        or run_id == INCIDENT
        or not 0 < len(raw) <= 500
        or not raw.startswith(_PREFIX)
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
    ):
        raise _fail()
    try:
        record = json.loads(raw[len(_PREFIX) : -1])
    except (ValueError, UnicodeError):
        raise _fail() from None
    if (
        type(record) is not dict
        or record.keys() != _FIELDS
        or record.get("schema") != 1
        or record.get("incident") != INCIDENT
        or record.get("recovery_run_id") != run_id
        or record.get("state") not in ("RECOVERED_OLD_PAIR", "NO_GO", "INDETERMINATE")
        or record.get("cleanup")
        != {"RECOVERED_OLD_PAIR": "ACCEPT", "NO_GO": "NO_GO", "INDETERMINATE": "INDETERMINATE"}[
            record["state"]
        ]
        or record.get("old_pair_only") is not (record["state"] == "RECOVERED_OLD_PAIR")
        or record.get("worker_started") is not False
        or type(record.get("foreign_resources_touched")) is not int
        or record["foreign_resources_touched"] != 0
        or type(record.get("ticket_actions")) is not int
        or record["ticket_actions"] != 0
        or raw != _PREFIX + _canonical(record) + b"\n"
    ):
        raise _fail()
    return raw


def _claim(run_id: str, proof: Preflight) -> None:
    marker = _canonical(
        {
            "schema": 1,
            "incident": INCIDENT,
            "recovery_run_id": run_id,
            "journal_sha256": proof.journal_sha256,
        }
    )
    fd = stage._root_fd()
    try:
        stage._create_exclusive(fd, _RESTORE + ".claim", marker)
        readback, _ = stage._read_file(fd, _RESTORE + ".claim", None, limit=512)
        if readback != marker:
            raise _fail()
    finally:
        os.close(fd)


def _terminal(run_id: str, state: str) -> None:
    fd = stage._root_fd()
    try:
        stage._create_exclusive(fd, _RESTORE + ".terminal", encode(run_id, state))
    finally:
        os.close(fd)


def _restore_docker(old: OnDemandInstallation, pins: incident.JournalPins) -> None:
    """Exact predecessor rename/start only. The old worker stays CREATED."""
    if host._browser_docker_ids() != {pins.old_controller_id, pins.old_worker_id}:
        raise _fail()
    for cid, role in (
        (pins.old_controller_id, "controller"),
        (pins.old_worker_id, "browser-worker"),
    ):
        canonical = f"boca-socios-{role}-1"
        parked = f"/{canonical.removesuffix('-1')}-legacy-{INCIDENT}"
        if host._browser_inspect_record(cid).get("Name") != parked:
            raise _fail()
        host._run("docker", "rename", cid, canonical, timeout=20)
        record = host._browser_inspect_record(cid)
        if record.get("Id") != cid or record.get("Name") != "/" + canonical:
            raise _fail()
    if host._browser_inspect_record(pins.old_controller_id)["State"]["Running"] is not False:
        raise _fail()
    if host._run("docker", "start", pins.old_controller_id, timeout=30) != pins.old_controller_id:
        raise _fail()
    host._browser_wait_healthy(pins.old_controller_id)
    if (
        host._run(
            "docker", "update", "--restart=unless-stopped", pins.old_controller_id, timeout=20
        )
        != pins.old_controller_id
    ):
        raise _fail()
    if service._verified_installation(service._home()) != old:
        raise _fail()


def _postflight(run_id: str, before: Preflight) -> None:
    old, pins = before.old, before.pins
    home = service._home()
    if (
        service._verified_installation(home) != old
        or host._browser_docker_ids() != {pins.old_controller_id, pins.old_worker_id}
        or incident._path_inode(home / service._ROOT / "socket")
        != pins.control_inode_sha256
        or service._present(replace._name(home, INCIDENT)[0])
        or service._present(replace._name(home, INCIDENT)[1])
    ):
        raise _fail()
    record = host._browser_inspect_record(pins.old_controller_id)
    state = record["State"]
    policy = record.get("HostConfig", {}).get("RestartPolicy")
    if (
        record.get("Name") != "/boca-socios-controller-1"
        or record.get("Image") != pins.old_controller_image_id
        or record.get("Config", {}).get("Image") != old.controller_image
        or record.get("HostConfig", {}).get("PortBindings") != _PORTS
        or record.get("NetworkSettings", {}).get("Ports") != _PORTS
        or state.get("Running") is not True
        or state.get("Health", {}).get("Status") != "healthy"
        or policy != {"Name": "unless-stopped", "MaximumRetryCount": 0}
    ):
        raise _fail()
    host._beta_loopback_health(pins.old_controller_id, "http://localhost:8443")
    record = host._browser_inspect_record(pins.old_worker_id)
    state = record["State"]
    if (
        record.get("Name") != "/boca-socios-browser-worker-1"
        or record.get("Image") != pins.old_worker_image_id
        or record.get("Config", {}).get("Image") != old.worker_image
        or state.get("Status") != "created"
        or state.get("Running") is not False
        or state.get("Pid") != 0
        or state.get("ExitCode") != 0
        or record.get("HostConfig", {}).get("RestartPolicy")
        != {"Name": "no", "MaximumRetryCount": 0}
    ):
        raise _fail()
    if _resource_custody(pins, before.resource_pins, old) != before.protected_inodes:
        raise _fail()
    # The original failed attempt's journal remains immutable and precommit.
    evidence = incident._read_staged(_JOURNAL + ".evidence", limit=4096)
    intent = incident._read_staged(_JOURNAL + ".intent", limit=1024)
    terminal = incident._read_staged(_JOURNAL + ".terminal", limit=1024)
    incident.verify_journal(evidence, intent, terminal, commit_present=incident._commit_present())
    if hashlib.sha256(evidence + intent + terminal).hexdigest() != before.journal_sha256:
        raise _fail()


def restore(run_id: str) -> bytes:
    if type(run_id) is not str or _RUN.fullmatch(run_id) is None or run_id == INCIDENT:
        raise _fail()
    with cleanup.protected_boca_job_lease(run_id) as lease:
        cleanup.verify_protected_boca_job_lease(lease, run_id)
        first = preflight(run_id)
        second = preflight(run_id)
        if first != second:
            raise _fail()
        cleanup.verify_protected_boca_job_lease(lease, run_id)
        try:
            _claim(run_id, first)
        except Exception:
            # A failed ACK/readback can leave a durable claim. It is NOT safe
            # to report a fresh no-effect NO_GO or to retry automatically.
            return encode(run_id, "INDETERMINATE")
        try:
            # The durable claim is not authority to mutate stale objects.
            # Repeat the same exact inventory immediately before first effect.
            if preflight(run_id) != first:
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, run_id)
            replace.restore_binding_precommit_recovery(first.old, INCIDENT, run_id, lease)
            cleanup.verify_protected_boca_job_lease(lease, run_id)
            _restore_docker(first.old, first.pins)
            _postflight(run_id, first)
            cleanup.verify_protected_boca_job_lease(lease, run_id)
            _terminal(run_id, "RECOVERED_OLD_PAIR")
            return encode(run_id, "RECOVERED_OLD_PAIR")
        except Exception:
            try:
                _terminal(run_id, "INDETERMINATE")
            except Exception:
                return encode(run_id, "INDETERMINATE")
            return encode(run_id, "INDETERMINATE")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("host", "verify"):
        return 3
    if args[0] == "verify":
        try:
            raw = verify(sys.stdin.buffer.read(501), args[1])
        except Exception:
            return 3
        sys.stdout.buffer.write(raw)
        return 0
    try:
        raw = restore(args[1])
    except Exception:
        try:
            raw = encode(args[1], "NO_GO")
        except Exception:
            return 3
    sys.stdout.buffer.write(raw)
    return 0 if b'"state":"RECOVERED_OLD_PAIR"' in raw else 3


if __name__ == "__main__":
    raise SystemExit(main())
