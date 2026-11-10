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


class ImageEngine916:
    """The Docker CLI wire boundary. No image records or environment are returned."""

    def __init__(self, ref):
        self.ref = ref
        self.ident = "sha256:" + "9" * 64
        self.tags = []
        self.digests = [ref]
        self.source = rescue.cleanup.BOCA_SOURCE
        self.revision = rescue.SOURCE
        self.present = True
        self.users = []
        self.calls = []
        self.raw_id = False
        self.fault = None
        self.list_digest = None

    def __call__(self, *argv):
        import json
        from subprocess import CompletedProcess

        self.calls.append(argv)
        if argv[:2] == ("image", "inspect"):
            fmt, target = argv[-2:]
            if not self.present:
                return CompletedProcess(
                    argv, 1, b"\n", f"Error: No such image: {target}\n".encode()
                )
            if fmt in ("{{json .Id}}", "{{json .ID}}"):
                value = self.ident.removeprefix("sha256:") if self.raw_id else self.ident
            elif fmt == "{{json .RepoDigests}}":
                value = self.digests
            elif fmt == "{{json .RepoTags}}":
                value = self.tags
            elif "org.opencontainers.image.source" in fmt:
                value = self.source
            elif "org.opencontainers.image.revision" in fmt:
                value = self.revision
            else:
                pytest.fail(f"Unreviewed Docker field {fmt}")
            return CompletedProcess(argv, 0, json.dumps(value).encode() + b"\n", b"")
        if argv[0] == "ps":
            return CompletedProcess(argv, 0, "\n".join(self.users).encode(), b"")
        if argv[:2] == ("image", "ls"):
            if self.fault:
                return CompletedProcess(argv, 1, b"", b"private-sentinel")
            return CompletedProcess(argv, 0, (self.list_digest or "").encode(), b"")
        pytest.fail(f"Unexpected operation {argv[:2]}")


@pytest.mark.parametrize(
    ("case", "status", "step", "reason"),
    [
        ("plain", "REMOVABLE", "USERS", "UNUSED"),
        ("raw-id", "REMOVABLE", "USERS", "UNUSED"),
        ("dangling", "REMOVABLE", "USERS", "UNUSED"),
        ("containerd", "REMOVABLE", "USERS", "UNUSED"),
        ("absent", "ABSENT", "LIST_REF", "ABSENCE_PROVED"),
        ("ambiguous", "UNKNOWN", "LIST_REF", "CLI_REJECTED"),
        ("wrong-source", "UNKNOWN", "SOURCE_LABEL", "MISMATCH"),
        ("missing-revision", "UNKNOWN", "REVISION_LABEL", "MISSING"),
        ("binding", "UNKNOWN", "REPO_DIGESTS", "MISMATCH"),
        ("tag", "RETAINED_ALIAS", "ALIASES", "SHARED"),
        ("used", "RETAINED_REFERENCED", "USERS", "IN_USE"),
    ],
)
def test_916_observer_uses_only_exact_fields_and_reports_distinct_steps(case, status, step, reason):
    ref = rescue.PINS["target_image_ref"]
    engine = ImageEngine916(ref)
    if case == "raw-id":
        engine.raw_id = True
    if case == "containerd":
        engine.tags = [ref]
        engine.ident = ref.split("@")[1]
    if case == "dangling":
        engine.tags = ["<none>:<none>"]
    if case in ("absent", "ambiguous"):
        engine.present = False
        engine.fault = case == "ambiguous"
    if case == "wrong-source":
        engine.source = "private-sentinel"
    if case == "missing-revision":
        engine.revision = ""
    if case == "binding":
        engine.digests = []
    if case == "tag":
        engine.tags = ["some-project:private-sentinel"]
    if case == "used":
        engine.users = [rescue.LEGACY]
    record = rescue.observe_image916(ref, docker=engine)
    assert (record["status"], record["step"], record["reason"]) == (status, step, reason)
    assert b"private-sentinel" not in rescue._wire(record)
    assert all(call[:2] != ("image", "rm") and "{{json .}}" not in call for call in engine.calls)
    if case == "absent":
        assert sum(call[:2] == ("image", "ls") for call in engine.calls) == 2


def test_916_exact_absence_contradicted_by_positive_listing_is_quarantined():
    ref = rescue.PINS["browser_image_ref"]
    engine = ImageEngine916(ref)
    engine.present = False
    repo, digest = ref.split("@")
    engine.list_digest = f"{repo} {digest} {engine.ident}\n"
    record = rescue.observe_image916(ref, docker=engine)
    assert (record["status"], record["step"], record["reason"]) == (
        "UNKNOWN",
        "LIST_REF",
        "MISMATCH",
    )


@pytest.fixture
def completion916(monkeypatch):
    coords = ("42750940352", "3c7dd8ae08bc5372a01a25701b6c5524ec9b3386", "42751222045", RUN, SHA)
    scenario = SimpleNamespace(pid=410, started="2026-11-10T00:00:00Z", changes=[], ended=False)
    engines = {}
    for side, ref in rescue._IMAGE_REFS916.items():
        engine = ImageEngine916(ref)
        engine.ident = rescue._CONFIG_IDS916[side]
        engines[ref] = engine
    scenario.engines = engines
    monkeypatch.setattr(rescue.host, "_validate_docker_boundary", lambda: None)
    monkeypatch.setattr(rescue, "_only_legacy", lambda: None)
    monkeypatch.setattr(rescue, "_disarmed", lambda: None)
    monkeypatch.setattr(rescue, "_healthy", lambda: (scenario.pid, scenario.started))
    monkeypatch.setattr(
        rescue,
        "_legacy",
        lambda _: {
            "Config": {"Env": ["BOCA_OWNER_SUBJECT=private-owner"]},
            "Image": "sha256:" + "d" * 64,
            "State": {"Pid": scenario.pid, "StartedAt": scenario.started},
        },
    )
    monkeypatch.setattr(rescue, "_terminal", lambda _: None)
    monkeypatch.setattr(rescue, "_stage_identity", lambda *_: None)
    monkeypatch.setattr(
        rescue, "_stage_gate", lambda present: rescue._require(present != scenario.ended)
    )

    def discard(*args):
        assert args == (rescue.INCIDENT, rescue.PINS["legacy_compose_sha"])
        scenario.ended = True
        scenario.changes.append("discard")

    monkeypatch.setattr(rescue.stage, "discard_recovered", discard)

    def lease(incident):
        assert incident == rescue.INCIDENT
        scenario.changes.append("lease")
        return nullcontext("lock")

    monkeypatch.setattr(rescue.cleanup, "protected_boca_job_lease", lease)
    monkeypatch.setattr(
        rescue.cleanup,
        "verify_protected_boca_job_lease",
        lambda token, incident: rescue._require(token == "lock" and incident == rescue.INCIDENT),
    )

    def docker(*argv):
        from subprocess import CompletedProcess

        if argv[:2] == ("image", "rm"):
            assert argv[2] == "--no-prune" and len(argv) == 4
            engine = next(item for item in engines.values() if item.ident == argv[-1])
            assert engine.present
            engine.present = False
            scenario.changes.append(("remove", engine.ident))
            if getattr(scenario, "break_post", False):
                engine.fault = True
            return CompletedProcess(argv, 0, b"Deleted", b"")
        if argv[:2] == ("image", "ls") and "--quiet" in argv:
            return CompletedProcess(
                argv, 0, "\n".join(x.ident for x in engines.values() if x.present).encode(), b""
            )
        key = argv[-1].removeprefix("ancestor=")
        engine = next(
            item
            for item in engines.values()
            if key in (item.ref, item.ident, item.ref.split("@")[0])
        )
        return engine(*argv)

    monkeypatch.setattr(rescue, "_image_docker916", docker)
    scenario.observe = lambda: rescue.completion_916(coords, observation=True)

    def finish(first):
        finish_args = (*coords[:3], "42751999999", SHA, RUN, first["plan_sha256"])
        result = rescue.completion_916(finish_args, observation=False)
        assert rescue.verify_916(rescue._wire(result), finish_args, observation=False) == result
        return result

    scenario.finish = finish
    scenario.coords = coords
    return scenario


def test_916_plan_and_finish_bind_to_same_process_and_two_images(completion916):
    lab = completion916
    first = lab.observe()
    assert first["state"] == "READY" and lab.changes == []
    assert rescue.verify_916(rescue._wire(first), lab.coords, observation=True) == first
    assert b"private-owner" not in rescue._wire(first)
    final = lab.finish(first)
    assert (final["state"], final["plan_sha256"]) == ("COMPLETED", first["plan_sha256"])
    assert list(lab.changes) == [
        "lease",
        *(("remove", engine.ident) for engine in lab.engines.values()),
        "discard",
    ]
    assert {value["status"] for value in final["images"].values()} == {"REMOVED"}


@pytest.mark.parametrize("changed", ["PID", "STARTED_AT", "ALIAS", "LABEL"])
def test_916_stale_plan_stops_before_any_removal(completion916, changed):
    lab = completion916
    first = lab.observe()
    worker = lab.engines[rescue.PINS["browser_image_ref"]]
    if changed == "PID":
        lab.pid += 1
    elif changed == "STARTED_AT":
        lab.started = "2026-11-10T01:01:01Z"
    elif changed == "ALIAS":
        worker.tags = ["other:tag"]
    else:
        worker.source = "private-sentinel"
    result = lab.finish(first)
    assert result["state"] == "NO_GO" and result["plan_sha256"] is None and lab.changes == ["lease"]
    assert b"private-sentinel" not in rescue._wire(result)


def test_916_partial_image_removal_retains_stage_with_exact_postcheck_cause(completion916):
    lab = completion916
    first = lab.observe()
    lab.break_post = True
    result = lab.finish(first)
    image = result["images"]["controller"]
    assert (result["state"], result["step"], image["status"], image["step"], image["reason"]) == (
        "NO_GO",
        "POST_DELETE",
        "UNKNOWN",
        "LIST_REF",
        "CLI_REJECTED",
    )
    assert len(lab.changes) == 2 and lab.changes[-1][0] == "remove" and not lab.ended


@pytest.mark.parametrize("blocked", ["RETAINED_ALIAS", "RETAINED_REFERENCED"])
def test_916_shared_image_blocks_both_mutations_and_staging(completion916, blocked):
    lab = completion916
    first = lab.observe()
    _, worker = lab.engines.values()
    if blocked == "RETAINED_ALIAS":
        worker.tags = ["known-local:tag"]
    else:
        worker.users = [rescue.LEGACY]
    report = lab.observe()
    assert report["state"] == "NO_GO" and report["plan_sha256"] is None
    assert report["images"]["controller"]["status"] == "REMOVABLE"
    assert report["images"]["worker"]["status"] == blocked and lab.changes == []
    assert rescue.verify_916(rescue._wire(report), lab.coords, observation=True) == report
    result = lab.finish(first)
    assert result["state"] == "NO_GO"
    assert lab.changes == ["lease"] and not lab.ended


@pytest.mark.parametrize(
    "fault",
    [
        "epoch",
        "release",
        "previous_run",
        "absent_to_removed",
        "wrong_evidence",
        "wrong_id",
        "shared_before",
    ],
)
def test_916_finish_ack_is_bound_to_authenticated_plan_and_only_its_transitions(
    completion916, fault
):
    from copy import deepcopy

    lab = completion916
    lab.engines[rescue._IMAGE_REFS916["worker"]].present = False
    plan = lab.observe()
    final = lab.finish(plan)
    rescue.verify_916_finish_against_plan(final, plan)
    final = deepcopy(final)
    if fault == "epoch":
        final["process_sha256"] = "c" * 64
    elif fault == "release":
        final["current_source_sha"] = "e" * 40
    elif fault == "previous_run":
        final["observation_run_id"] = "2222222"
    elif fault == "absent_to_removed":
        final["images"]["worker"] = {
            **final["images"]["controller"],
            "id": rescue._CONFIG_IDS916["worker"],
        }
    elif fault == "wrong_evidence":
        final["images"]["controller"]["evidence"] = "c" * 64
    elif fault == "wrong_id":
        final["images"]["controller"]["id"] = rescue._IMAGE_REFS916["controller"].split("@")[1]
    else:
        plan["images"]["controller"].update(
            status="RETAINED_ALIAS", step="ALIASES", reason="SHARED"
        )
    with pytest.raises(ValueError):
        rescue.verify_916_finish_against_plan(final, plan)


def test_916_no_go_observation_sanitizes_both_images_even_when_first_fails(completion916):
    lab = completion916
    for engine in lab.engines.values():
        engine.source = None
    record = lab.observe()
    assert record["state"] == "NO_GO" and record["plan_sha256"] is None and lab.changes == []
    assert all(
        item["step"] == "SOURCE_LABEL" and item["reason"] == "MISSING"
        for item in record["images"].values()
    )
    assert rescue.verify_916(rescue._wire(record), lab.coords, observation=True) == record


def test_916_verifier_rejects_forged_plan_and_noncanonical_input(completion916):
    lab = completion916
    plan = lab.observe()
    with pytest.raises(ValueError):
        rescue.verify_916(
            rescue._wire({**plan, "plan_sha256": "f" * 64}), lab.coords, observation=True
        )
    with pytest.raises(ValueError):
        rescue.verify_916(rescue._wire({**plan, "untrusted": "echo"}), lab.coords, observation=True)
    with pytest.raises(ValueError):
        rescue.verify_916(b" " + rescue._wire(plan), lab.coords, observation=True)


@pytest.mark.parametrize("side", ["controller", "worker"])
@pytest.mark.parametrize("digest_kind", ["config", "manifest"])
def test_916_lost_repository_name_with_release_id_still_listed_is_quarantined(
    completion916, monkeypatch, side, digest_kind
):
    lab = completion916
    ref = rescue._IMAGE_REFS916[side]
    lab.engines[ref].present = False
    remaining = rescue._CONFIG_IDS916[side] if digest_kind == "config" else ref.split("@")[1]
    docker = rescue._image_docker916

    def orphan(*args):
        from subprocess import CompletedProcess

        if args[:2] == ("image", "ls") and "--quiet" in args:
            return CompletedProcess(args, 0, (remaining + "\n").encode(), b"")
        return docker(*args)

    monkeypatch.setattr(rescue, "_image_docker916", orphan)
    record = lab.observe()
    assert record["state"] == "NO_GO" and lab.changes == []
    assert record["images"][side] == {
        "status": "UNKNOWN",
        "step": "RELEASE_IDS",
        "reason": "ORPHAN_ID",
        "id": remaining,
        "evidence": None,
    }
    assert rescue.verify_916(rescue._wire(record), lab.coords, observation=True) == record


def test_916_lost_finish_ack_confirms_absence_and_refuses_another_plan(completion916):
    lab = completion916
    assert lab.finish(lab.observe())["state"] == "COMPLETED"
    previous = list(lab.changes)
    after = lab.observe()
    assert (after["state"], after["step"], after["reason"]) == (
        "NO_GO",
        "STAGE_ABSENT",
        "ALREADY_ABSENT",
    )
    assert [v["status"] for v in after["images"].values()] == ["ABSENT", "ABSENT"]
    assert after["plan_sha256"] is None and after["process_sha256"] and lab.changes == previous
    assert rescue.verify_916(rescue._wire(after), lab.coords, observation=True) == after


def test_916_unpublished_or_unknown_config_id_never_leaves_the_host_receipt(completion916):
    lab = completion916
    fake = "sha256:" + "a" * 64
    next(iter(lab.engines.values())).ident = fake
    receipt = lab.observe()
    assert (receipt["state"], receipt["step"], receipt["reason"]) == (
        "NO_GO",
        "RELEASE_IDS",
        "UNEXPECTED_ID",
    )
    assert fake.encode() not in rescue._wire(receipt) and lab.changes == []


def test_916_dual_lookup_falls_back_only_for_a_present_typed_id():
    from subprocess import CompletedProcess

    ref = rescue.PINS["target_image_ref"]
    engine = ImageEngine916(ref)

    def docker(*args):
        if args[-2] == "{{json .Id}}":
            return CompletedProcess(args, 1, b"\n", b"template error")
        return engine(*args)

    assert rescue.observe_image916(ref, docker=docker)["status"] == "REMOVABLE"
    engine.present = False
    negative = rescue.observe_image916(ref, docker=docker)
    assert (negative["status"], negative["step"], negative["reason"]) == (
        "UNKNOWN",
        "LOOKUP_REF",
        "CLI_REJECTED",
    )


def test_916_host_no_go_guards_do_not_start_a_container_or_drop_a_volume(
    completion916, monkeypatch
):
    lab = completion916
    first = lab.observe()

    def unsafe():
        raise RuntimeError("secret-guard")

    monkeypatch.setattr(rescue, "_only_legacy", unsafe)
    result = lab.finish(first)
    assert (result["state"], result["step"]) == ("NO_GO", "ONLY_LEGACY")
    assert lab.changes == ["lease"] and b"secret-guard" not in rescue._wire(result)


def test_916_lease_must_yield_a_real_token_even_when_context_entry_succeeds(
    completion916, monkeypatch
):
    lab = completion916
    first = lab.observe()
    monkeypatch.setattr(rescue.cleanup, "protected_boca_job_lease", lambda _: nullcontext(None))
    result = lab.finish(first)
    assert (result["state"], result["step"]) == ("NO_GO", "LEASE")
    assert not lab.changes


@pytest.mark.parametrize(
    "args",
    [
        ("container", "stop", rescue.LEGACY),
        ("volume", "rm", "boca_data"),
        ("image", "prune"),
        ("image", "rm", "--force", rescue._CONFIG_IDS916["controller"]),
        ("image", "rm", "--no-prune", "sha256:" + "f" * 64),
        ("image", "inspect", "--format", "{{json .}}", rescue._CONFIG_IDS916["worker"]),
    ],
)
def test_916_production_transport_rejects_outside_exact_readers_and_two_release_images(
    monkeypatch, args
):
    monkeypatch.setattr(rescue.host, "_require_dedicated_identity", lambda: None)
    monkeypatch.setattr(
        rescue.subprocess, "run", lambda *a, **kw: pytest.fail("outside pinned commands")
    )
    with pytest.raises(rescue._Fault916):
        rescue._image_docker916(*args)


def test_916_rejects_foreign_id_before_inspecting_any_fields_or_labels(completion916):
    lab = completion916
    engine = next(iter(lab.engines.values()))
    engine.ident = "sha256:" + "6" * 64
    assert lab.observe()["images"]["controller"]["reason"] == "UNEXPECTED_ID"
    assert all(call[-1] == engine.ref for call in engine.calls)
