"""Recover the three immutable Boca CIDs from the precommit #904 terminal."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover_backend as backend
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios import host_cutover_stage as stage
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_service as control
from boca_socios.host_boca_cutover import CutoverPlan
from scripts import host_cutover_postapply_reconcile as observer
from scripts.host_cutover_stage_recovery import _stage_identity

INCIDENT = observer.R904
SOURCE = observer.R904_SHA
EVIDENCE = "42745950217"
EVIDENCE_SHA = "518bd31d0585deb8900d43cb4957d94b873e4bed"
LEGACY = observer.LEGACY904
CANDIDATE = observer.CANDIDATE904
WORKER = observer.WORKER904
PINS = observer._PINS904
LIMIT = 2048
_STEPS = {
    "LEASE",
    "PREFLIGHT",
    "RESTORE",
    "ORIGINAL_HEALTH",
    "WORKER_IPC",
    "IMAGES",
    "STAGE",
    "POSTFLIGHT",
}
_IMAGE_OUTCOMES = {"ABSENT", "REMOVED", "RETAINED_REFERENCED", "RETAINED_ALIAS"}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Boca #904 observation unverified")


def _coordinates(args: Sequence[str]) -> dict[str, str]:
    _require(
        len(args) == 5
        and tuple(args[:3]) == (INCIDENT, SOURCE, EVIDENCE)
        and observer.RUN.fullmatch(args[3]) is not None
        and args[3] not in (INCIDENT, EVIDENCE)
        and observer.SOURCE.fullmatch(args[4]) is not None
        and args[4] not in (SOURCE, EVIDENCE_SHA)
    )
    return {
        "version": "boca-cutover-904-recovery-v1",
        "incident_run_id": INCIDENT,
        "incident_source_sha": SOURCE,
        "evidence_run_id": EVIDENCE,
        "evidence_source_sha": EVIDENCE_SHA,
        "current_run_id": args[3],
        "current_source_sha": args[4],
    }


def _plan(owner: str) -> CutoverPlan:
    plan = CutoverPlan(
        INCIDENT,
        LEGACY,
        PINS["legacy_source_sha"],
        PINS["legacy_image_ref"],
        PINS["legacy_compose_sha"],
        SOURCE,
        PINS["target_image_ref"],
        PINS["browser_image_ref"],
        PINS["target_compose_sha"],
        PINS["overlay_sha"],
        PINS["seccomp_sha"],
        owner,
    )
    plan.validate()
    return plan


def _terminal(plan: CutoverPlan) -> None:
    # This verifies the private persisted intent byte-for-byte, including the
    # subject's digest, without passing its value in argv or a receipt.
    actual = terminal.read_persisted_record(plan)
    expected = terminal.TerminalRecord(
        INCIDENT,
        plan.legacy_sha,
        SOURCE,
        LEGACY,
        hashlib.sha256(terminal._intent_bytes(plan)).hexdigest(),
        "NO_GO",
        "NO_GO",
        False,
        False,
        CANDIDATE,
        WORKER,
    )
    _require(actual == expected)


def _stage_gate(present: bool) -> None:
    facts = observer._files904(stage.ROOT, control._home())
    _require(observer.stage_files_match_908(facts, present=present))


def _disarmed() -> None:
    home = control._home()
    folder = control._unit_dir(home)
    _require(not control._present(control.control_directory().parent))
    for unit in (control._SOCKET, control._SERVICE):
        _require(not control._present(folder / unit))
        state = control._known(home, folder, unit, False)
        _require(
            state["LoadState"] == "not-found"
            and state["ActiveState"] == "inactive"
            and state["SubState"] == "dead"
        )
    _require(not control._present(folder / "default.target.wants" / control._SOCKET))
    _require(
        not control._systemctl(
            home,
            "list-units",
            "--no-legend",
            "--plain",
            "--no-pager",
            "--state=activating,active,reloading,deactivating",
            "boca-bot-control@*.service",
        ).strip()
    )
    _require(
        not control._systemctl(
            home,
            "list-jobs",
            "--no-legend",
            "--plain",
            "--no-pager",
            control._SOCKET,
            "boca-bot-control@*.service",
        ).strip()
    )


def _ids() -> frozenset[str]:
    args = ("ps", "-a", "-q", "--no-trunc")
    ids = frozenset(cleanup._ids(*args))
    _require(LEGACY in ids and ids <= {LEGACY, CANDIDATE, WORKER})
    _require(
        ids
        == frozenset(
            cleanup._ids(*args, "--filter", "label=com.docker.compose.project=boca-socios")
        )
    )
    for cid in (LEGACY, CANDIDATE, WORKER):
        _require(cleanup._ids(*args, "--filter", "id=" + cid) == ([cid] if cid in ids else []))
    return ids


def _ipc(ids: frozenset[str]) -> bool:
    names = host._names("volume", f"name=^{host.BROWSER_IPC_VOLUME}$")
    _require(names in (set(), {host.BROWSER_IPC_VOLUME}))
    users = ids & {CANDIDATE, WORKER}
    _require(not users or bool(names))
    if names:
        host._browser_validate_ipc_volume(INCIDENT)
        bound = cleanup._ids(
            "ps", "-a", "-q", "--no-trunc", "--filter", "volume=" + host.BROWSER_IPC_VOLUME
        )
        _require(frozenset(bound) == users)
    return bool(names)


def _legacy(role: str) -> dict:
    _require(role in observer.RECOVERY_904_PROFILES)
    active = role in ("OLD_ACTIVE", "OLD_STARTED")
    record = host._cutover_legacy_record(
        LEGACY,
        PINS["legacy_image_ref"],
        PINS["legacy_source_sha"],
        name=f"boca-socios-controller-legacy-{INCIDENT}"
        if role == "OLD_PARKED"
        else host.CUTOVER_LEGACY_NAME,
        running=active,
        restart_policy="unless-stopped" if role == "OLD_ACTIVE" else "no",
    )
    state = record["State"]
    _require(
        state["Status"] == ("running" if active else "exited")
        and state["Paused"] is False
        and state["Dead"] is False
        and type(state["Pid"]) is int
        and (state["Pid"] > 0 if active else state["Pid"] == 0)
    )
    cleanup.attest_historical_legacy_image(
        record["Image"], PINS["legacy_image_ref"], PINS["legacy_source_sha"]
    )
    if active:
        _require(state["Health"]["Status"] == "healthy")
    return record


def _healthy(role: str = "OLD_ACTIVE") -> tuple[int, str]:
    state = _legacy(role)["State"]
    host._beta_loopback_health(LEGACY, "http://localhost:8443")
    started = state["StartedAt"]
    _require(isinstance(started, str) and bool(started) and started != "0001-01-01T00:00:00Z")
    return state["Pid"], started


@dataclass(frozen=True)
class Preflight:
    plan: CutoverPlan
    role: str
    candidate: bool
    worker: bool
    ipc: bool
    controller_hash: str
    seccomp: bytes
    fingerprint: str
    legacy_process: tuple[int, str] | None = None


def _preflight() -> Preflight:
    host._validate_docker_boundary()
    report = observer._host(INCIDENT, None, source_sha=SOURCE)
    role = observer.recovery_profile904(report)
    ids = _ids()
    _require(role == "OLD_PARKED" or CANDIDATE not in ids)
    for cid in (LEGACY, CANDIDATE, WORKER):
        _require(
            report["pinned_containers"][cid]["presence"] == ("PRESENT" if cid in ids else "ABSENT")
        )
    original = _legacy(role)
    owner = [
        v.removeprefix("BOCA_OWNER_SUBJECT=")
        for v in original["Config"]["Env"]
        if isinstance(v, str) and v.startswith("BOCA_OWNER_SUBJECT=")
    ]
    _require(len(owner) == 1)
    plan = _plan(owner[0])
    _terminal(plan)
    _stage_gate(True)
    _disarmed()
    _stage_identity(INCIDENT, json.loads(terminal._intent_bytes(plan)))
    seccomp = stage.read_verified(INCIDENT, plan.legacy_compose_sha, "seccomp")
    controller_hash = ""
    if CANDIDATE in ids:
        controller_hash = backend._reviewed_compose_hash(
            plan, "controller", control_directory=control.control_directory()
        )
        host._cutover_candidate_postflight(
            CANDIDATE,
            plan.target_image,
            SOURCE,
            INCIDENT,
            plan.origin,
            plan.owner_subject,
            controller_hash,
            control_directory=control.control_directory(),
            verify_runtime=False,
            compensating=True,
        )
        observed_image = cleanup._inspect_field("container", CANDIDATE, "Image")
        _require(observed_image == cleanup._inspect_field("image", plan.target_image, "Id"))
    if WORKER in ids:
        worker_hash = backend._reviewed_compose_hash(
            plan, "browser-worker", control_directory=control.control_directory()
        )
        host._cutover_idle_worker(
            WORKER, plan.browser_image, SOURCE, INCIDENT, plan.seccomp_sha, seccomp, worker_hash
        )
        host._cutover_worker_never_started(WORKER)
    ipc = _ipc(ids)
    fingerprint = hashlib.sha256(
        observer._canonical([report["pinned_containers"], report["incident_files"]])
    ).hexdigest()
    legacy_process = (
        (original["State"]["Pid"], original["State"]["StartedAt"])
        if role == "OLD_STARTED"
        else None
    )
    return Preflight(
        plan,
        role,
        CANDIDATE in ids,
        WORKER in ids,
        ipc,
        controller_hash,
        seccomp,
        fingerprint,
        legacy_process,
    )


def _restore(before: Preflight, guard: Callable[[], None]) -> None:
    plan = before.plan
    if before.role in ("OLD_RENAMED", "OLD_STARTED"):

        def canonical() -> None:
            guard()
            _require(
                not before.candidate
                and CANDIDATE not in _ids()
                and host._cutover_candidate_name_id() == LEGACY
            )

        canonical()
        _legacy(before.role)
        if before.role == "OLD_RENAMED":
            host._cutover_start_canonical_original(
                LEGACY, plan.legacy_image, plan.legacy_sha, after_candidate_removal=True
            )
        canonical()
        process = _healthy("OLD_STARTED")
        _require(before.role != "OLD_STARTED" or before.legacy_process == process)
        canonical()
        host._cutover_rearm_original(LEGACY, plan.legacy_image, plan.legacy_sha)
        canonical()
        _require(_healthy() == process)
        return
    _require(before.role == "OLD_PARKED")
    if before.candidate:
        host._cutover_compensate_candidate(
            LEGACY,
            plan.legacy_image,
            plan.legacy_sha,
            plan.target_image,
            SOURCE,
            INCIDENT,
            plan.origin,
            plan.owner_subject,
            before.controller_hash,
            control_directory=control.control_directory(),
            expected_candidate=CANDIDATE,
        )
    else:
        _require(CANDIDATE not in _ids() and host._cutover_candidate_name_id() is None)
        host._browser_port_free(after_candidate_removal=True)
        host._cutover_restore_original(LEGACY, plan.legacy_image, plan.legacy_sha, INCIDENT)


def _clean_worker(before: Preflight) -> None:
    ids = _ids()
    _require(ids == (frozenset({LEGACY, WORKER}) if before.worker else frozenset({LEGACY})))
    _require(
        _ipc(ids) == before.ipc
        and host._cutover_worker_name_id() == (WORKER if before.worker else None)
    )
    if before.worker:
        worker_hash = backend._reviewed_compose_hash(
            before.plan, "browser-worker", control_directory=control.control_directory()
        )
        host._cutover_compensate_worker(
            before.plan.browser_image,
            SOURCE,
            INCIDENT,
            before.plan.seccomp_sha,
            before.seccomp,
            WORKER,
            idle_config_hash=worker_hash,
        )
    elif before.ipc:
        host._cutover_compensate_ipc(INCIDENT)


def _only_legacy() -> None:
    ids = _ids()
    _require(ids == {LEGACY} and not _ipc(ids))


def _image(ref: str) -> tuple[str, str]:
    try:
        ident = cleanup._inspect_field("image", ref, "Id")
    except cleanup.CleanupError:
        if host._browser_image_absent(ref, SOURCE):
            return "ABSENT", ""
        raise
    _require(
        isinstance(ident, str)
        and ident.startswith("sha256:")
        and cleanup.HEX_ID.fullmatch(ident) is not None
    )
    _require(cleanup._inspect_field("image", ident, "Id") == ident)
    digests = cleanup._inspect_field("image", ident, "RepoDigests")
    tags = cleanup._inspect_field("image", ident, "RepoTags")
    _require(
        isinstance(digests, list) and ref in digests and (tags is None or isinstance(tags, list))
    )
    for key, value in (("source", cleanup.BOCA_SOURCE), ("revision", SOURCE)):
        _require(
            cleanup._inspect_image_public_oci_label(ident, "org.opencontainers.image." + key)
            == value
        )
    if tags or digests != [ref]:
        return "RETAINED_ALIAS", ident
    if cleanup._ids("ps", "-a", "-q", "--no-trunc", "--filter", "ancestor=" + ident):
        return "RETAINED_REFERENCED", ident
    return "ELIGIBLE", ident


def _clean_images() -> dict[str, str]:
    results = {}
    for name, ref in (
        ("controller_image", PINS["target_image_ref"]),
        ("worker_image", PINS["browser_image_ref"]),
    ):
        _only_legacy()
        first = _image(ref)
        _require(_image(ref) == first)
        state, ident = first
        if state == "ELIGIBLE":
            _require(ident != cleanup._inspect_field("container", LEGACY, "Image"))
            cleanup._docker("image", "rm", "--no-prune", ident)
            _require(_image(ref)[0] == "ABSENT")
            _require(
                ident not in cleanup._ids("image", "ls", "-a", "-q", "--no-trunc", dedupe=True)
            )
            state = "REMOVED"
        results[name] = state
    return results


def _wire(record: dict[str, Any]) -> bytes:
    return observer._canonical(record) + b"\n"


def recover(args: Sequence[str]) -> dict[str, Any]:
    coords = _coordinates(args)
    step = "LEASE"
    try:
        with cleanup.protected_boca_job_lease(INCIDENT) as lease:

            def guard() -> None:
                cleanup.verify_protected_boca_job_lease(lease, INCIDENT)
                _disarmed()

            step = "PREFLIGHT"
            guard()
            before = _preflight()
            _require(before == _preflight())
            guard()
            if before.role != "OLD_ACTIVE":
                step = "RESTORE"
                _restore(before, guard)
            step = "ORIGINAL_HEALTH"
            _healthy()
            step = "WORKER_IPC"
            guard()
            _clean_worker(before)
            _only_legacy()
            step = "IMAGES"
            guard()
            images = _clean_images()
            step = "STAGE"
            guard()
            _healthy()
            _only_legacy()
            _terminal(before.plan)
            _stage_gate(True)
            stage.discard_recovered(INCIDENT, PINS["legacy_compose_sha"])
            step = "POSTFLIGHT"
            _stage_gate(False)
            _only_legacy()
            _healthy()
            _terminal(before.plan)
            guard()
        return {**coords, "state": "ORIGINAL_RESTORED", "legacy": LEGACY, **images}
    except Exception:
        # A transport/manager/parser failure must never publish its arguments.
        return {**coords, "state": "NO_GO", "step": step}


def verify(raw: bytes, args: Sequence[str]) -> dict[str, Any]:
    coords = _coordinates(args)
    _require(0 < len(raw) <= LIMIT)
    result = json.loads(raw, object_pairs_hook=stage._unique)
    _require(
        isinstance(result, dict)
        and all(result.get(k) == v for k, v in coords.items())
        and _wire(result) == raw
    )
    if result.get("state") == "NO_GO":
        _require(set(result) == {*coords, "state", "step"} and result["step"] in _STEPS)
    else:
        _require(
            set(result) == {*coords, "state", "legacy", "controller_image", "worker_image"}
            and result.get("state") == "ORIGINAL_RESTORED"
            and result["legacy"] == LEGACY
            and all(result[k] in _IMAGE_OUTCOMES for k in ("controller_image", "worker_image"))
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        _require(len(args) == 6 and args[0] in ("host", "verify"))
        if args[0] == "host":
            record = recover(args[1:])
            output = _wire(record)
            verify(output, args[1:])
            sys.stdout.buffer.write(output)
        else:
            record = verify(sys.stdin.buffer.read(LIMIT + 1), args[1:])
            summary = "BOCA_904_RECOVERY state=" + record["state"]
            if record["state"] == "NO_GO":
                summary += " step=" + record["step"]
            else:
                summary += (
                    " controller_image="
                    + record["controller_image"]
                    + " worker_image="
                    + record["worker_image"]
                )
            print(summary + " cutover=NO_GO")
        return 0 if record["state"] == "ORIGINAL_RESTORED" else 3
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print("BOCA_904_RECOVERY state=NO_GO step=INPUT", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
