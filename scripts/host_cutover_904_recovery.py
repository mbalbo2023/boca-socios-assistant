"""Recover the three immutable Boca CIDs from the precommit #904 terminal."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import nullcontext
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


def _owner_plan(original: dict) -> CutoverPlan:
    owner = [
        v.removeprefix("BOCA_OWNER_SUBJECT=")
        for v in original["Config"]["Env"]
        if isinstance(v, str) and v.startswith("BOCA_OWNER_SUBJECT=")
    ]
    _require(len(owner) == 1)
    return _plan(owner[0])


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
    plan = _owner_plan(original)
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


R916 = "42750940352"
R916_SHA = "3c7dd8ae08bc5372a01a25701b6c5524ec9b3386"
R917 = "42751222045"
LIMIT_916 = 4096
_IMAGE_REFS916 = {"controller": PINS["target_image_ref"], "worker": PINS["browser_image_ref"]}
_DOCKER_ID916 = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")
_REPOSITORY916 = r"[a-z0-9][a-z0-9.-]*(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-]+[a-z0-9]+)*)+"
_REF916 = re.compile(_REPOSITORY916 + r"@sha256:[0-9a-f]{64}\Z")
_LIST916 = "{{.Repository}} {{.Digest}} {{.ID}}"
# Image build and registry push in Release #788, job 129583391462. Depending
# on the local store the Docker ID can be the config digest or the pushed manifest.
_CONFIG_IDS916 = {
    "controller": "sha256:a191fe19d4837225f066aaeeb68ed459f668b55c20e3cb29e86a48c74ab86fb6",
    "worker": "sha256:81753c847715010eadfb410747753c95745cf3080cc55b7bbc7f0c8562e57c34",
}
_RELEASE_IDS916 = {
    role: frozenset((_CONFIG_IDS916[role], ref.split("@")[1]))
    for role, ref in _IMAGE_REFS916.items()
}
_LABEL_FMT916 = {
    key: '{{if .Config.Labels}}{{json (index .Config.Labels "org.opencontainers.image.'
    + key
    + '")}}{{else}}null{{end}}'
    for key in ("source", "revision")
}


def _commands916() -> frozenset[tuple[str, ...]]:
    commands = {("image", "ls", "--all", "--quiet", "--no-trunc")}
    for role, ref in _IMAGE_REFS916.items():
        repo = ref.split("@")[0]
        commands.add(
            ("image", "ls", "--all", "--digests", "--no-trunc", "--format", _LIST916, repo)
        )
        for key in (ref, *_RELEASE_IDS916[role]):
            for fmt in ("{{json .Id}}", "{{json .ID}}"):
                commands.add(("image", "inspect", "--format", fmt, key))
        for ident in _RELEASE_IDS916[role]:
            for fmt in ("{{json .RepoTags}}", "{{json .RepoDigests}}", *_LABEL_FMT916.values()):
                commands.add(("image", "inspect", "--format", fmt, ident))
            commands.add(("ps", "-a", "-q", "--no-trunc", "--filter", "ancestor=" + ident))
            commands.add(("image", "rm", "--no-prune", ident))
    return frozenset(commands)


_COMMANDS916 = _commands916()
_PLAN_STATUS916 = {
    "ABSENT": ("LIST_REF", "ABSENCE_PROVED"),
    "REMOVABLE": ("USERS", "UNUSED"),
    "RETAINED_ALIAS": ("ALIASES", "SHARED"),
    "RETAINED_REFERENCED": ("USERS", "IN_USE"),
    "REMOVED": ("POST_DELETE", "ABSENCE_PROVED"),
}
_IMAGE_STEPS916 = {
    "LOOKUP_REF",
    "LOOKUP_ID",
    "LIST_REF",
    "REPO_DIGESTS",
    "REPO_TAGS",
    "SOURCE_LABEL",
    "REVISION_LABEL",
    "ALIASES",
    "USERS",
    "COMPARE_IMAGE",
    "REMOVE",
    "POST_DELETE",
    "NOT_REACHED",
    "RELEASE_IDS",
}
_REASONS916 = {
    "UNVERIFIED",
    "CLI_REJECTED",
    "TIMEOUT",
    "UNAVAILABLE",
    "MALFORMED",
    "MISSING",
    "MISMATCH",
    "DRIFT",
    "ACTIVE_IMAGE",
    "UNEXPECTED_ID",
    "PLAN_MISMATCH",
    "ALREADY_ABSENT",
    "ORPHAN_ID",
    "SHARED",
    "IN_USE",
}
_GUARD_STEPS916 = {
    "LEASE",
    "BOUNDARY",
    "ONLY_LEGACY",
    "DISARMED",
    "ORIGINAL_HEALTH",
    "TERMINAL",
    "STAGE_IDENTITY",
    "PLAN_DIGEST",
    "STAGE_DISCARD",
    "POST_STAGE",
    "STAGE_ABSENT",
    "COMPLETE",
}


class _Fault916(Exception):
    def __init__(self, step: str, reason: str):
        super().__init__(step, reason)
        self.step = step
        self.reason = reason


def _check916(ok: bool, step: str, reason: str) -> None:
    if not ok:
        raise _Fault916(step, reason)


def _sha916(value: object) -> str:
    return hashlib.sha256(observer._canonical(value)).hexdigest()


def _image_result916(
    status: str, step: str, reason: str, ident: str | None = None, evidence: str | None = None
) -> dict:
    return {"status": status, "step": step, "reason": reason, "id": ident, "evidence": evidence}


def _image_docker916(*args: str) -> subprocess.CompletedProcess[bytes]:
    _check916(args in _COMMANDS916, "BOUNDARY", "UNVERIFIED")
    host._require_dedicated_identity()
    return subprocess.run(  # noqa: S603 - exact arguments on Boca's pinned rootless socket
        ["/usr/bin/docker", "--host", cleanup.DOCKER_SOCKET, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=20,
        env={
            "DOCKER_HOST": cleanup.DOCKER_SOCKET,
            "XDG_RUNTIME_DIR": f"/run/user/{cleanup.EXPECTED_UID}",
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
        },
    )


Docker916 = Callable[..., subprocess.CompletedProcess[bytes]]


def _call916(docker: Docker916, step: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        result = docker(*args)
    except subprocess.TimeoutExpired as exc:
        raise _Fault916(step, "TIMEOUT") from exc
    except OSError as exc:
        raise _Fault916(step, "UNAVAILABLE") from exc
    _check916(
        type(result.returncode) is int
        and isinstance(result.stdout, bytes)
        and isinstance(result.stderr, bytes)
        and len(result.stdout) <= 32_768
        and len(result.stderr) <= 1024,
        step,
        "MALFORMED",
    )
    return result


def _success916(result: subprocess.CompletedProcess[bytes], step: str) -> bytes:
    _check916(result.returncode == 0 and not result.stderr, step, "CLI_REJECTED")
    return result.stdout


def _json916(result: subprocess.CompletedProcess[bytes], step: str) -> object:
    try:
        return json.loads(_success916(result, step))
    except (UnicodeError, ValueError) as exc:
        raise _Fault916(step, "MALFORMED") from exc


def _id916(value: object, step: str) -> str:
    match = _DOCKER_ID916.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise _Fault916(step, "MALFORMED")
    return "sha256:" + match[1]


def _lookup916(
    docker: Docker916, key: str, step: str, *, allow_missing: bool = False
) -> str | None:
    for fmt in ("{{json .Id}}", "{{json .ID}}"):
        result = _call916(docker, step, "image", "inspect", "--format", fmt, key)
        if result.returncode == 0:
            return _id916(_json916(result, step), step)
        if (
            allow_missing
            and fmt == "{{json .Id}}"
            and host._browser_missing_image_result(
                result.returncode, result.stdout, result.stderr, key
            )
        ):
            return None
    raise _Fault916(step, "CLI_REJECTED")


def _repo_absent916(docker: Docker916, ref: str) -> None:
    repo, digest = ref.split("@")
    for _ in range(2):
        out = _success916(
            _call916(
                docker,
                "LIST_REF",
                "image",
                "ls",
                "--all",
                "--digests",
                "--no-trunc",
                "--format",
                _LIST916,
                repo,
            ),
            "LIST_REF",
        )
        for row in out.splitlines():
            try:
                fields = row.decode("ascii").split()
            except UnicodeError as exc:
                raise _Fault916("LIST_REF", "MALFORMED") from exc
            _check916(
                len(fields) == 3
                and fields[0] == repo
                and (
                    fields[1] == "<none>"
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", fields[1]) is not None
                ),
                "LIST_REF",
                "MALFORMED",
            )
            _id916(fields[2], "LIST_REF")
            _check916(fields[1] != digest, "LIST_REF", "MISMATCH")


def _image_names916(value: object, step: str) -> list[str]:
    if value is None:
        return []
    _check916(isinstance(value, list) and len(value) <= cleanup.MAX_OBJECTS, step, "MALFORMED")
    assert isinstance(value, list)
    for name in value:
        _check916(
            isinstance(name, str) and bool(re.fullmatch(r"[A-Za-z0-9._:/@<>-]{1,512}", name)),
            step,
            "MALFORMED",
        )
    _check916(len(value) == len(set(value)), step, "MALFORMED")
    return sorted(value)


def observe_image916(
    reference: str,
    *,
    docker: Docker916 = _image_docker916,
    revision: str = SOURCE,
    source: str = cleanup.BOCA_SOURCE,
    expected_ids: frozenset[str] | None = None,
) -> dict:
    """Return bounded facts for a single immutable reference, including an exact failure phase."""
    ident = None
    try:
        _check916(_REF916.fullmatch(reference) is not None, "LOOKUP_REF", "MALFORMED")
        ident = _lookup916(docker, reference, "LOOKUP_REF", allow_missing=True)
        if ident is None:
            _repo_absent916(docker, reference)
            return _image_result916(
                "ABSENT", "LIST_REF", "ABSENCE_PROVED", evidence=_sha916(reference)
            )
        _check916(expected_ids is None or ident in expected_ids, "RELEASE_IDS", "UNEXPECTED_ID")
        _check916(_lookup916(docker, ident, "LOOKUP_ID") == ident, "LOOKUP_ID", "MISMATCH")

        def field(step: str, fmt: str) -> object:
            return _json916(
                _call916(docker, step, "image", "inspect", "--format", fmt, ident), step
            )

        digests = _image_names916(field("REPO_DIGESTS", "{{json .RepoDigests}}"), "REPO_DIGESTS")
        _check916(reference in digests, "REPO_DIGESTS", "MISMATCH")
        _check916(
            all(_REF916.fullmatch(item) or item == "<none>@<none>" for item in digests),
            "REPO_DIGESTS",
            "MALFORMED",
        )
        tags = _image_names916(field("REPO_TAGS", "{{json .RepoTags}}"), "REPO_TAGS")
        for key, expected in (("source", source), ("revision", revision)):
            step = key.upper() + "_LABEL"
            value = field(step, _LABEL_FMT916[key])
            _check916(value is not None and value != "", step, "MISSING")
            _check916(value == expected, step, "MISMATCH")
        users = _success916(
            _call916(
                docker, "USERS", "ps", "-a", "-q", "--no-trunc", "--filter", "ancestor=" + ident
            ),
            "USERS",
        ).splitlines()
        _check916(all(re.fullmatch(rb"[0-9a-f]{64}", cid) for cid in users), "USERS", "MALFORMED")
        _check916(len(users) == len(set(users)) <= cleanup.MAX_OBJECTS, "USERS", "MALFORMED")
        evidence = _sha916(
            [
                reference,
                ident,
                digests,
                tags,
                source,
                revision,
                sorted(x.decode("ascii") for x in users),
            ]
        )
        if set(tags) - {reference, "<none>:<none>"} or set(digests) - {reference, "<none>@<none>"}:
            status = "RETAINED_ALIAS"
        elif users:
            status = "RETAINED_REFERENCED"
        else:
            status = "REMOVABLE"
        return _image_result916(status, *_PLAN_STATUS916[status], ident, evidence)
    except _Fault916 as exc:
        return _image_result916("UNKNOWN", exc.step, exc.reason, ident)


def _host_image916(role: str, active_image: str) -> dict:
    ref = _IMAGE_REFS916[role]
    permitted = _RELEASE_IDS916[role]
    result = observe_image916(ref, docker=_image_docker916, expected_ids=permitted)
    ident = result["id"]
    try:
        if result["status"] == "UNKNOWN":
            return {**result, "id": ident if ident in permitted else None}
        if ident is None:
            # A lost repository name does not establish that its known content is gone.
            for _ in range(2):
                out = _success916(
                    _call916(
                        _image_docker916,
                        "RELEASE_IDS",
                        "image",
                        "ls",
                        "--all",
                        "--quiet",
                        "--no-trunc",
                    ),
                    "RELEASE_IDS",
                )
                try:
                    ids = {_id916(row.decode("ascii"), "RELEASE_IDS") for row in out.splitlines()}
                except UnicodeError as exc:
                    raise _Fault916("RELEASE_IDS", "MALFORMED") from exc
                remaining = sorted(ids & permitted)
                if remaining:
                    ident = remaining[0]
                    raise _Fault916("RELEASE_IDS", "ORPHAN_ID")
        else:
            _check916(ident != active_image, "RELEASE_IDS", "ACTIVE_IMAGE")
        return result
    except _Fault916 as exc:
        return _image_result916(
            "UNKNOWN", exc.step, exc.reason, ident if ident in permitted else None
        )


def _coords916(args: Sequence[str], observation: bool) -> dict:
    historical = {INCIDENT, EVIDENCE, "42750716605", R916, R917}
    _require(
        len(args) == (5 if observation else 7)
        and tuple(args[:3]) == (R916, R916_SHA, R917)
        and observer.RUN.fullmatch(args[3]) is not None
        and args[3] not in historical
        and observer.SOURCE.fullmatch(args[4]) is not None
        and args[4] not in (SOURCE, EVIDENCE_SHA, R916_SHA)
    )
    coords = {
        "version": "boca-release-residue-916-v1",
        "mode": "observe" if observation else "finish",
        "recovery_run_id": R916,
        "recovery_source_sha": R916_SHA,
        "evidence_run_id": R917,
        "current_run_id": args[3],
        "current_source_sha": args[4],
    }
    if not observation:
        _require(
            observer.RUN.fullmatch(args[5]) is not None
            and args[5] not in historical | {args[3]}
            and observer.IDENT.fullmatch(args[6]) is not None
        )
        coords.update(observation_run_id=args[5], observation_plan_sha256=args[6])
    return coords


def _checked916(step: str, fn: Callable, *args):
    try:
        return fn(*args)
    except _Fault916:
        raise
    except Exception as exc:
        # Host paths, owner data, process output and exception text stay private.
        raise _Fault916(step, "UNVERIFIED") from exc


def _ground916(lease, *, stage_present: bool, allow_absent: bool = False) -> tuple[str, str, bool]:
    if lease is not None:
        _checked916("LEASE", cleanup.verify_protected_boca_job_lease, lease, INCIDENT)
    _checked916("DISARMED", _disarmed)
    _checked916("ONLY_LEGACY", _only_legacy)
    original = _checked916("ORIGINAL_HEALTH", _legacy, "OLD_ACTIVE")
    active_image = _id916(original.get("Image"), "ORIGINAL_HEALTH")
    process = _checked916("ORIGINAL_HEALTH", _healthy)
    _check916(
        (original["State"]["Pid"], original["State"]["StartedAt"]) == process,
        "ORIGINAL_HEALTH",
        "DRIFT",
    )
    plan = _checked916("TERMINAL", _owner_plan, original)
    _checked916("TERMINAL", _terminal, plan)
    try:
        _checked916("STAGE_IDENTITY" if stage_present else "POST_STAGE", _stage_gate, stage_present)
    except _Fault916:
        if not (allow_absent and stage_present):
            raise
        _checked916("STAGE_IDENTITY", _stage_gate, False)
        stage_present = False
    if stage_present:
        _checked916(
            "STAGE_IDENTITY", _stage_identity, INCIDENT, json.loads(terminal._intent_bytes(plan))
        )
    return _sha916([LEGACY, *process]), active_image, stage_present


def _plan_sha916(images: dict, epoch: str, source_sha: str) -> str:
    return _sha916([R916, R916_SHA, R917, INCIDENT, PINS, source_sha, epoch, images])


def _same_image916(expected: dict, current: dict) -> None:
    if current["status"] == "UNKNOWN":
        raise _Fault916(current["step"], current["reason"])
    _check916(current == expected, "COMPARE_IMAGE", "DRIFT")


def completion_916(args: Sequence[str], *, observation: bool) -> dict:
    coords = _coords916(args, observation)
    images = {
        key: _image_result916("UNKNOWN", "NOT_REACHED", "UNVERIFIED") for key in _IMAGE_REFS916
    }
    epoch = None
    try:
        _checked916("BOUNDARY", host._validate_docker_boundary)
        context = nullcontext() if observation else cleanup.protected_boca_job_lease(INCIDENT)
        with context as lease:
            _check916(observation or lease is not None, "LEASE", "UNVERIFIED")
            physical = _ground916(lease, stage_present=True, allow_absent=observation)
            epoch, active_image, present = physical

            def unchanged(*, stage_present: bool) -> None:
                now = _ground916(lease, stage_present=stage_present)
                _check916(now == (epoch, active_image, stage_present), "ORIGINAL_HEALTH", "DRIFT")

            def read(role: str) -> dict:
                return _checked916("LOOKUP_REF", _host_image916, role, active_image)

            for role in images:
                images[role] = read(role)
            unchanged(stage_present=present)
            for role in images:
                first = images[role]
                second = read(role)
                if second != first:
                    images[role] = (
                        second
                        if second["status"] == "UNKNOWN"
                        else _image_result916(
                            "UNKNOWN",
                            "COMPARE_IMAGE",
                            "DRIFT",
                            second["id"],
                        )
                    )
            for value in images.values():
                if value["status"] not in ("ABSENT", "REMOVABLE"):
                    raise _Fault916(value["step"], value["reason"])
            _check916(present, "STAGE_ABSENT", "ALREADY_ABSENT")
            plan_sha = _plan_sha916(images, epoch, coords["current_source_sha"])
            if not observation:
                _check916(
                    plan_sha == coords["observation_plan_sha256"], "PLAN_DIGEST", "PLAN_MISMATCH"
                )
                for role, expected in images.items():
                    unchanged(stage_present=True)
                    current = read(role)
                    try:
                        _same_image916(expected, current)
                        if expected["status"] == "REMOVABLE":
                            _success916(
                                _call916(
                                    _image_docker916,
                                    "REMOVE",
                                    "image",
                                    "rm",
                                    "--no-prune",
                                    expected["id"],
                                ),
                                "REMOVE",
                            )
                            after = read(role)
                            if after["status"] == "UNKNOWN":
                                images[role] = after
                                raise _Fault916("POST_DELETE", after["reason"])
                            _check916(after["status"] == "ABSENT", "POST_DELETE", "MISMATCH")
                            images[role] = _image_result916(
                                "REMOVED",
                                *_PLAN_STATUS916["REMOVED"],
                                expected["id"],
                                after["evidence"],
                            )
                    except _Fault916 as exc:
                        if images[role]["status"] != "UNKNOWN":
                            images[role] = _image_result916(
                                "UNKNOWN", exc.step, exc.reason, expected["id"]
                            )
                        raise
                unchanged(stage_present=True)
                for role, final in images.items():
                    actual = read(role)
                    if final["status"] == "REMOVED" and actual["status"] == "ABSENT":
                        continue
                    try:
                        _same_image916(final, actual)
                    except _Fault916 as exc:
                        images[role] = _image_result916(
                            "UNKNOWN", exc.step, exc.reason, actual["id"]
                        )
                        raise
                # A final locked proof of the same panel epoch and sealed stage precedes its only unlink.
                unchanged(stage_present=True)
                _checked916(
                    "STAGE_DISCARD", stage.discard_recovered, INCIDENT, PINS["legacy_compose_sha"]
                )
                unchanged(stage_present=False)
            else:
                unchanged(stage_present=True)
        return {
            **coords,
            "state": "READY" if observation else "COMPLETED",
            "step": "COMPLETE",
            "reason": "VERIFIED",
            "process_sha256": epoch,
            "plan_sha256": plan_sha,
            "images": images,
        }
    except Exception as exc:
        step, reason = (
            (exc.step, exc.reason) if isinstance(exc, _Fault916) else ("LEASE", "UNVERIFIED")
        )
        return {
            **coords,
            "state": "NO_GO",
            "step": step,
            "reason": reason,
            "process_sha256": epoch,
            "plan_sha256": None,
            "images": images,
        }


def verify_916(raw: bytes, args: Sequence[str], *, observation: bool) -> dict:
    coords = _coords916(args, observation)
    _require(0 < len(raw) <= LIMIT_916)
    result = json.loads(raw, object_pairs_hook=stage._unique)
    _require(
        isinstance(result, dict)
        and set(result)
        == {*coords, "state", "step", "reason", "process_sha256", "plan_sha256", "images"}
        and all(result.get(k) == v for k, v in coords.items())
        and _wire(result) == raw
    )
    state, epoch, digest, images = (
        result[k] for k in ("state", "process_sha256", "plan_sha256", "images")
    )
    _require(
        isinstance(images, dict)
        and set(images) == set(_IMAGE_REFS916)
        and (
            epoch is None or isinstance(epoch, str) and observer.IDENT.fullmatch(epoch) is not None
        )
    )
    for role, image in images.items():
        _require(
            isinstance(image, dict) and set(image) == {"status", "step", "reason", "id", "evidence"}
        )
        status, step, reason, ident, evidence = (
            image[k] for k in ("status", "step", "reason", "id", "evidence")
        )
        _require(ident is None or isinstance(ident, str) and ident in _RELEASE_IDS916[role])
        if status == "UNKNOWN":
            _require(
                state == "NO_GO"
                and step in _IMAGE_STEPS916
                and reason in _REASONS916
                and evidence is None
            )
        else:
            _require(
                status in _PLAN_STATUS916
                and _PLAN_STATUS916[status] == (step, reason)
                and isinstance(evidence, str)
                and observer.IDENT.fullmatch(evidence) is not None
                and ((ident is None) == (status == "ABSENT"))
            )
            if state in ("READY", "COMPLETED"):
                _require(
                    status in ({"ABSENT", "REMOVABLE"} if observation else {"ABSENT", "REMOVED"})
                )
            if status in ("ABSENT", "REMOVED"):
                _require(evidence == _sha916(_IMAGE_REFS916[role]))
            _require(
                (not observation or status != "REMOVED")
                and (state != "COMPLETED" or status != "REMOVABLE")
            )
    if state == "NO_GO":
        _require(
            digest is None
            and result["step"] in _GUARD_STEPS916 | _IMAGE_STEPS916
            and result["reason"] in _REASONS916
        )
    else:
        _require(
            state == ("READY" if observation else "COMPLETED")
            and result["step"] == "COMPLETE"
            and result["reason"] == "VERIFIED"
            and epoch is not None
            and digest
            == (
                _plan_sha916(images, epoch, coords["current_source_sha"])
                if observation
                else coords["observation_plan_sha256"]
            )
        )
    return result


def verify_916_finish_against_plan(finish: dict, plan: dict) -> None:
    """Bind the authenticated host completion to its separately downloaded READY artifact."""
    fixed = (R916, R916_SHA, R917)
    plan_run, source, digest = (
        plan["current_run_id"],
        plan["current_source_sha"],
        plan["plan_sha256"],
    )
    verify_916(_wire(plan), (*fixed, plan_run, source), observation=True)
    verify_916(
        _wire(finish),
        (*fixed, finish["current_run_id"], source, plan_run, digest),
        observation=False,
    )
    _require(
        plan["state"] == "READY"
        and finish["state"] == "COMPLETED"
        and finish["process_sha256"] == plan["process_sha256"]
        and finish["plan_sha256"] == digest
    )
    for role, before in plan["images"].items():
        after = finish["images"][role]
        if before["status"] == "ABSENT":
            _require(after == before)
        else:
            _require(
                before["status"] == "REMOVABLE"
                and after["status"] == "REMOVED"
                and after["id"] == before["id"]
                and after["evidence"] == _sha916(_IMAGE_REFS916[role])
            )


def _main916(args: Sequence[str]) -> int:
    observation = args[0] in ("observe-916", "verify-observe-916")
    try:
        if args[0].startswith("verify-"):
            record = verify_916(
                sys.stdin.buffer.read(LIMIT_916 + 1), args[1:], observation=observation
            )
            summary = [
                "BOCA_916_PLAN" if observation else "BOCA_916_FINISH",
                "state=" + record["state"],
                "step=" + record["step"],
                "reason=" + record["reason"],
            ]
            if record["plan_sha256"]:
                summary.append("plan_sha256=" + record["plan_sha256"])
            for role in _IMAGE_REFS916:
                item = record["images"][role]
                summary.append(f"{role}={item['status']}/{item['step']}/{item['reason']}")
            print(" ".join(summary))
        else:
            record = completion_916(args[1:], observation=observation)
            wire = _wire(record)
            verify_916(wire, args[1:], observation=observation)
            sys.stdout.buffer.write(wire)
        return 3 if record["state"] == "NO_GO" else 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print("BOCA_916 state=NO_GO step=INPUT", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("observe-916", "verify-observe-916", "finish-916", "verify-finish-916"):
        return _main916(args)
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
