"""Exact-ID rollback after #904, isolated from Docker and the droplet."""

import importlib
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
rescue = importlib.import_module("scripts.host_cutover_904_recovery")

RUN = "42749999999"
SHA = "a" * 40
COORDS = (rescue.INCIDENT, rescue.SOURCE, rescue.EVIDENCE, RUN, SHA)


@pytest.fixture
def world(monkeypatch):
    events = []
    plan = rescue._plan("synthetic-owner")
    before = rescue.Preflight(plan, "OLD_PARKED", True, True, True, "1" * 64, b"seccomp", "2" * 64)
    scenario = SimpleNamespace(first=before, second=before, fail_health=False, events=events)
    samples = iter(("first", "second"))
    monkeypatch.setattr(
        rescue.cleanup, "protected_boca_job_lease", lambda incident: nullcontext("lease")
    )
    monkeypatch.setattr(rescue.cleanup, "verify_protected_boca_job_lease", lambda lease, run: None)
    monkeypatch.setattr(rescue, "_preflight", lambda: getattr(scenario, next(samples)))
    monkeypatch.setattr(rescue, "_disarmed", lambda: events.append("disarmed"))
    monkeypatch.setattr(
        rescue, "_restore", lambda observed, guard: events.append(("restore", observed.candidate))
    )

    def healthy():
        events.append("healthy")
        if scenario.fail_health:
            raise ValueError("private-sentinel")

    monkeypatch.setattr(rescue, "_healthy", healthy)
    monkeypatch.setattr(
        rescue, "_clean_worker", lambda observed: events.append(("worker", observed.worker))
    )
    monkeypatch.setattr(
        rescue, "_clean_images", lambda: {"controller_image": "ABSENT", "worker_image": "REMOVED"}
    )
    monkeypatch.setattr(rescue, "_stage_gate", lambda present: events.append(("stage", present)))
    monkeypatch.setattr(rescue.stage, "discard_recovered", lambda *args: events.append("discard"))
    monkeypatch.setattr(rescue, "_only_legacy", lambda: events.append("singleton"))
    monkeypatch.setattr(rescue, "_terminal", lambda plan: None)
    return scenario


@pytest.mark.parametrize(
    "role,candidate,worker",
    [
        ("OLD_ACTIVE", False, False),
        ("OLD_PARKED", False, True),
        ("OLD_PARKED", True, True),
        ("OLD_RENAMED", False, True),
        ("OLD_STARTED", False, False),
    ],
)
def test_restore_by_positive_role_and_only_clean_after_health(world, role, candidate, worker):
    world.first = world.second = replace(world.first, role=role, candidate=candidate, worker=worker)
    result = rescue.recover(COORDS)
    assert result["state"] == "ORIGINAL_RESTORED"
    assert (("restore", candidate) in world.events) == (role != "OLD_ACTIVE")
    assert (
        world.events.index("healthy")
        < world.events.index(("worker", worker))
        < world.events.index("discard")
    )
    assert world.events.index("singleton") < world.events.index("discard")
    assert rescue.verify(rescue._wire(result), COORDS) == result


def test_physical_drift_prevents_every_mutation(world):
    world.second = replace(world.first, fingerprint="f" * 64)
    result = rescue.recover(COORDS)
    assert (result["state"], result["step"]) == ("NO_GO", "PREFLIGHT")
    assert "discard" not in world.events and not any(
        isinstance(e, tuple) and e[0] == "restore" for e in world.events
    )


def test_original_without_positive_http_preserves_worker_images_and_stage(world):
    world.fail_health = True
    result = rescue.recover(COORDS)
    assert result["state"] == "NO_GO" and result["step"] == "ORIGINAL_HEALTH"
    assert not any(
        e == "discard" or isinstance(e, tuple) and e[0] == "worker" for e in world.events
    )
    assert b"private-sentinel" not in rescue._wire(result)


@pytest.mark.parametrize(
    "index,value", [(0, "123"), (1, "b" * 40), (2, "123"), (3, rescue.INCIDENT), (4, "oops")]
)
def test_unverified_inputs_never_open_lease(monkeypatch, index, value):
    monkeypatch.setattr(
        rescue.cleanup, "protected_boca_job_lease", lambda *_: pytest.fail("lease opened")
    )
    args = list(COORDS)
    args[index] = value
    with pytest.raises(ValueError):
        rescue.recover(args)


def test_worker_running_during_last_check_never_stops_or_removes(monkeypatch):
    host = rescue.host
    monkeypatch.setattr(host, "_cutover_worker_name_id", lambda: rescue.WORKER)
    monkeypatch.setattr(host, "_browser_inspect_record", lambda cid: {"State": {"Running": True}})
    monkeypatch.setattr(host, "_run", lambda *a, **kwargs: pytest.fail("Docker mutation"))
    with pytest.raises(host.PreflightError):
        host._cutover_compensate_worker(
            rescue.PINS["browser_image_ref"],
            rescue.SOURCE,
            rescue.INCIDENT,
            rescue.PINS["seccomp_sha"],
            b"unused",
            rescue.WORKER,
            idle_config_hash="1" * 64,
        )


@pytest.mark.parametrize("outcome", ["RETAINED_ALIAS", "RETAINED_REFERENCED", "ABSENT"])
def test_image_tied_to_multiple_tags_or_references_is_preserved(monkeypatch, outcome):
    monkeypatch.setattr(rescue, "_only_legacy", lambda: None)
    monkeypatch.setattr(rescue, "_image", lambda ref: (outcome, "sha256:" + "1" * 64))
    monkeypatch.setattr(
        rescue.cleanup, "_docker", lambda *a: pytest.fail("unexpected image removal")
    )
    assert rescue._clean_images() == {"controller_image": outcome, "worker_image": outcome}


def test_exact_images_only_after_two_identical_proofs_and_absence_of_id(monkeypatch):
    refs = (rescue.PINS["target_image_ref"], rescue.PINS["browser_image_ref"])
    known = {ref: "sha256:" + ch * 64 for ref, ch in zip(refs, ("a", "b"), strict=True)}
    available = set(known.values())
    removals = []
    monkeypatch.setattr(rescue, "_only_legacy", lambda: None)

    def field(kind, key, prop):
        if kind == "container":
            assert (key, prop) == (rescue.LEGACY, "Image")
            return "sha256:" + "c" * 64
        ident = known.get(key, key)
        if ident not in available:
            raise rescue.cleanup.CleanupError("absent")
        return {
            "Id": ident,
            "RepoTags": [],
            "RepoDigests": [next(ref for ref, dig in known.items() if dig == ident)],
        }[prop]

    monkeypatch.setattr(rescue.cleanup, "_inspect_field", field)
    monkeypatch.setattr(
        rescue.cleanup,
        "_inspect_image_public_oci_label",
        lambda ident, key: (
            rescue.SOURCE if key.endswith("revision") else rescue.cleanup.BOCA_SOURCE
        ),
    )
    monkeypatch.setattr(
        rescue.host, "_browser_image_absent", lambda ref, source: known[ref] not in available
    )
    monkeypatch.setattr(
        rescue.cleanup, "_ids", lambda *args, **kw: list(available) if args[0] == "image" else []
    )

    def remove(*argv):
        assert argv[:3] == ("image", "rm", "--no-prune") and argv[3] in available
        removals.append(argv[3])
        available.remove(argv[3])

    monkeypatch.setattr(rescue.cleanup, "_docker", remove)
    assert rescue._clean_images() == {"controller_image": "REMOVED", "worker_image": "REMOVED"}
    assert removals == list(known.values()) and not available


@pytest.mark.parametrize(
    "drift",
    [
        "alias",
        "multiple-digests",
        "referenced",
        "wrong-revision",
        "wrong-source",
        "not-found-unknown",
    ],
)
def test_release_only_image_disposition(monkeypatch, drift):
    ref = rescue.PINS["target_image_ref"]
    ident = "sha256:" + "7" * 64

    def inspect(kind, key, prop):
        if drift == "not-found-unknown":
            raise rescue.cleanup.CleanupError("transport unknown")
        return {
            "Id": ident,
            "RepoTags": ["extra"] if drift == "alias" else None,
            "RepoDigests": [ref, "alias"] if drift == "multiple-digests" else [ref],
        }[prop]

    monkeypatch.setattr(rescue.cleanup, "_inspect_field", inspect)
    monkeypatch.setattr(
        rescue.cleanup,
        "_inspect_image_public_oci_label",
        lambda _, k: (
            "wrong"
            if drift == "wrong-" + k.rpartition(".")[2]
            else rescue.SOURCE
            if k.endswith(".revision")
            else rescue.cleanup.BOCA_SOURCE
        ),
    )
    monkeypatch.setattr(
        rescue.cleanup, "_ids", lambda *a: [rescue.LEGACY] if drift == "referenced" else []
    )
    monkeypatch.setattr(rescue.host, "_browser_image_absent", lambda *_: False)
    if drift.startswith("wrong") or drift == "not-found-unknown":
        with pytest.raises(ValueError):
            rescue._image(ref)
    else:
        assert rescue._image(ref) == (
            "RETAINED_REFERENCED" if drift == "referenced" else "RETAINED_ALIAS",
            ident,
        )


@pytest.mark.parametrize(
    "bad", ["global-extra", "project-missing", "pinned-undisclosed", "pinned-error"]
)
def test_docker_inventory_independently_compares_global_and_pinned_cids(monkeypatch, bad):
    def ids(*args):
        if "--filter" not in args:
            return [rescue.LEGACY] + (["a" * 64] if bad == "global-extra" else [])
        expr = args[-1]
        if expr.startswith("label="):
            return [] if bad == "project-missing" else [rescue.LEGACY]
        if expr == "id=" + rescue.LEGACY:
            return [rescue.LEGACY]
        if expr == "id=" + rescue.CANDIDATE and bad == "pinned-undisclosed":
            return [rescue.CANDIDATE]
        if bad == "pinned-error":
            raise rescue.cleanup.CleanupError("timeout")
        return []

    monkeypatch.setattr(rescue.cleanup, "_ids", ids)
    with pytest.raises(ValueError):
        rescue._ids()


def test_terminal_requires_exact_original_uncommitted_receipt_and_uses_hashed_owner(monkeypatch):
    p = rescue._plan("private-test-owner")
    import hashlib

    raw = rescue.terminal._intent_bytes(p)
    assert b"private-test-owner" not in raw
    stored = rescue.terminal.TerminalRecord(
        rescue.INCIDENT,
        p.legacy_sha,
        rescue.SOURCE,
        rescue.LEGACY,
        hashlib.sha256(raw).hexdigest(),
        "NO_GO",
        "NO_GO",
        False,
        False,
        rescue.CANDIDATE,
        rescue.WORKER,
    )
    monkeypatch.setattr(rescue.terminal, "read_persisted_record", lambda _: stored)
    rescue._terminal(p)
    for changed in (
        replace(stored, original_restored=True),
        replace(stored, cleanup="ACCEPT"),
        replace(stored, worker_id=None),
        replace(stored, intent_sha256="e" * 64),
    ):
        monkeypatch.setattr(
            rescue.terminal, "read_persisted_record", lambda _, record=changed: record
        )
        with pytest.raises(ValueError):
            rescue._terminal(p)


@pytest.mark.parametrize(
    "state",
    [
        "running 1 true false false false 0",
        "exited 0 false false false false 0",
        "created 0 false false false false 1",
    ],
)
def test_worker_history_is_closed_without_actions(monkeypatch, state):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        assert args[:3] == ("docker", "inspect", "--format") and args[-1] == rescue.WORKER
        return state + " 0001-01-01T00:00:00Z 0001-01-01T00:00:00Z"

    monkeypatch.setattr(rescue.host, "_run", docker)
    with pytest.raises(rescue.host.PreflightError):
        rescue.host._cutover_worker_never_started(rescue.WORKER)
    assert len(calls) == 1


def test_904_cannot_use_old_stage_only_api(monkeypatch):
    from scripts import host_cutover_stage_recovery as old

    monkeypatch.setattr(old, "_recover", lambda *a: pytest.fail("historic mutation reached"))
    with pytest.raises(old.StageRecoveryError):
        old.recover_v3(rescue.INCIDENT, rescue.SOURCE)
    with pytest.raises(old.StageRecoveryError):
        old.verify_runner_v3(b"", rescue.INCIDENT, rescue.SOURCE)


def test_unlinked_systemd_instance_still_active_prohibits_any_recovery(monkeypatch, tmp_path):
    ctl = rescue.control
    monkeypatch.setattr(ctl, "_home", lambda: tmp_path)
    monkeypatch.setattr(ctl, "_unit_dir", lambda home: home)
    monkeypatch.setattr(ctl, "_present", lambda path: False)
    monkeypatch.setattr(
        ctl,
        "_known",
        lambda *args: {"LoadState": "not-found", "ActiveState": "inactive", "SubState": "dead"},
    )

    def manager(home, *args):
        assert args[0] == "list-units" and args[-1] == "boca-bot-control@*.service"
        return "boca-bot-control@0-residual.service loaded active running"

    monkeypatch.setattr(ctl, "_systemctl", manager)
    with pytest.raises(ValueError):
        rescue._disarmed()


def test_inactive_unlinked_units_with_queued_job_prohibit_recovery(monkeypatch, tmp_path):
    ctl = rescue.control
    monkeypatch.setattr(ctl, "_home", lambda: tmp_path)
    monkeypatch.setattr(ctl, "_unit_dir", lambda home: home)
    monkeypatch.setattr(ctl, "_present", lambda path: False)
    monkeypatch.setattr(
        ctl,
        "_known",
        lambda *args: {"LoadState": "not-found", "ActiveState": "inactive", "SubState": "dead"},
    )

    def manager(home, *args):
        if args[0] == "list-units":
            return ""
        assert args == (
            "list-jobs",
            "--no-legend",
            "--plain",
            "--no-pager",
            "boca-bot-control.socket",
            "boca-bot-control@*.service",
        )
        return "22 boca-bot-control@8-pending.service start waiting"

    monkeypatch.setattr(ctl, "_systemctl", manager)
    with pytest.raises(ValueError):
        rescue._disarmed()


def test_subprocess_timeout_yields_bounded_coordinates_and_failing_step(world, monkeypatch):
    import subprocess

    def timeout():
        raise subprocess.TimeoutExpired("private-sentinel", 15)

    monkeypatch.setattr(rescue, "_disarmed", timeout)
    result = rescue.recover(COORDS)
    assert (result["state"], result["step"]) == ("NO_GO", "PREFLIGHT")
    assert b"private-sentinel" not in rescue._wire(result)


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "root-inode",
        "stage-inode",
        "marker-inode",
        "compose-mode",
        "promotion",
        "actuator",
        "extra",
        "seccomp",
    ],
)
def test_only_908_staging_anchors_and_missing_actuator_admit_effects(monkeypatch, tmp_path, change):
    obs = rescue.observer
    nodes = dict.fromkeys(obs._FILES904.keys() | obs._ACT904.keys(), "ABSENT")
    for key, kind, ino, mode in (
        ("root", "dir", 3362, 0o700),
        ("stage", "dir", 3145755, 0o700),
        ("compose", "file", 3220, 0o644),
        ("stage_marker", "file", 3145756, 0o600),
    ):
        nodes[key] = [kind, 64769, ino, mode, 1, True]
    for inode, key in enumerate(("stage_base", "stage_overlay", "stage_seccomp"), 3145757):
        nodes[key] = ["file", 64769, inode, 0o600, 1, True]
    checks = {
        "root": 0,
        "stage": 0,
        "compose": True,
        "stage_marker": [64769, 3220],
        "stage_base": True,
        "stage_overlay": True,
        "stage_seccomp": True,
    }
    if change == "root-inode":
        nodes["root"][2] += 1
    if change == "stage-inode":
        nodes["stage"][2] += 1
    if change == "marker-inode":
        nodes["stage_marker"][2] += 1
    if change == "compose-mode":
        nodes["compose"][3] = 0o600
    if change == "promotion":
        nodes["promote_intent"] = "UNREADABLE"
    if change == "actuator":
        nodes["installed_service"] = "UNSAFE"
    if change == "extra":
        checks["stage"] = 1
    if change == "seccomp":
        checks["stage_seccomp"] = False
    monkeypatch.setattr(rescue.control, "_home", lambda: tmp_path)
    monkeypatch.setattr(obs, "_files904", lambda *args: {"inodes": nodes, "checks": checks})
    if change == "none":
        rescue._stage_gate(True)
    else:
        with pytest.raises(ValueError):
            rescue._stage_gate(True)


@pytest.mark.parametrize("role", ["OLD_RENAMED", "OLD_STARTED"])
@pytest.mark.parametrize("drift", ["none", "name", "candidate", "health", "pid"])
def test_canonical_recovery_only_starts_stopped_and_checks_same_process_on_rearming(
    monkeypatch, role, drift
):
    plan = rescue._plan("test-owner")
    epoch = (199, "2026-11-10T00:00:01.000Z") if role == "OLD_STARTED" else None
    before = rescue.Preflight(plan, role, False, False, False, "", b"", "0" * 64, epoch)
    original = rescue.LEGACY
    state = {
        "running": role == "OLD_STARTED",
        "pid": 199 if role == "OLD_STARTED" else 0,
        "policy": "no",
    }
    calls = []

    def inspect(cid, image, sha, *, name, running, restart_policy="unless-stopped"):
        assert cid == original and image == plan.legacy_image and sha == plan.legacy_sha
        assert (
            name == rescue.host.CUTOVER_LEGACY_NAME
            and running is state["running"]
            and restart_policy == state["policy"]
        )
        return {
            "Image": "sha256:" + "a" * 64,
            "State": {
                "Status": "running" if running else "exited",
                "Pid": state["pid"],
                "Paused": False,
                "Dead": False,
                "Health": {"Status": "healthy"},
                "StartedAt": "2026-11-10T00:00:01.000Z",
            },
        }

    def docker(*argv, **kw):
        calls.append(argv)
        assert argv[-1] == original
        if argv[:2] == ("docker", "start"):
            assert not state["running"]
            state.update(running=True, pid=199)
        elif argv[:3] == ("docker", "update", "--restart=unless-stopped"):
            state["policy"] = "unless-stopped"
            if drift == "pid":
                state["pid"] += 1
        else:
            pytest.fail("unexpected Docker action")
        return original

    def http(*args):
        assert state["running"]
        if drift == "health":
            raise rescue.host.PreflightError("health failed")
        calls.append(("http", state["policy"]))

    monkeypatch.setattr(
        rescue,
        "_ids",
        lambda: frozenset({original, rescue.CANDIDATE} if drift == "candidate" else {original}),
    )
    monkeypatch.setattr(
        rescue.host, "_cutover_candidate_name_id", lambda: None if drift == "name" else original
    )
    monkeypatch.setattr(rescue.host, "_cutover_legacy_record", inspect)
    monkeypatch.setattr(rescue.cleanup, "attest_historical_legacy_image", lambda *_: None)
    monkeypatch.setattr(rescue.host, "_run", docker)
    monkeypatch.setattr(rescue.host, "_beta_loopback_health", http)
    monkeypatch.setattr(rescue.host, "_browser_port_free", lambda **kw: calls.append(("port", kw)))
    monkeypatch.setattr(rescue.host, "_browser_wait_healthy", lambda cid: None)
    if drift == "none":
        rescue._restore(before, lambda: None)
    else:
        with pytest.raises(ValueError):
            rescue._restore(before, lambda: None)
    effects = [c for c in calls if c[0] == "docker"]
    start = ("docker", "start", original)
    update = ("docker", "update", "--restart=unless-stopped", original)
    if drift in ("name", "candidate"):
        assert effects == []
    else:
        assert (start in effects) is (role == "OLD_RENAMED")
        assert (update in effects) is (drift != "health")
        if drift == "none":
            assert (
                calls.index(("http", "no"))
                < calls.index(update)
                < calls.index(("http", "unless-stopped"))
            )
        assert any(c[0] == "port" for c in calls) is (role == "OLD_RENAMED")
