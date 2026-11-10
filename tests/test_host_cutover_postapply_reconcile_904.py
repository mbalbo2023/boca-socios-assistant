"""Exact historical V3 readback, with independent stage and actuator inode evidence."""

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from test_host_cutover_postapply_reconcile import _container, _intent, _result, reconcile


def test_files_survive_extra_stage_entries_and_reject_symlink_targets(tmp_path):
    r = reconcile
    root, home = tmp_path / "stage", tmp_path / "home"
    root.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    root.joinpath("compose.beta.yaml").write_bytes(
        (Path(__file__).parents[1] / "compose.beta.yaml").read_bytes()
    )
    base = root.joinpath("compose.beta.yaml").stat()
    stage = root / r._STAGE904
    stage.mkdir(mode=0o700)
    (stage / "cutover-a-marker.json").write_bytes(
        r._canonical(
            {
                "version": "cutover-a-stage-v1",
                "attempt_id": r.R904,
                "legacy_controller_id": r.LEGACY904,
                "legacy_source_sha": r._PINS904["legacy_source_sha"],
                "target_source_sha": r.R904_SHA,
                "legacy_compose_sha": r._BASE,
                "target_compose_sha": r._BASE,
                "overlay_compose_sha": r._OVERLAY,
                "seccomp_sha": r._SECCOMP,
                "target_image": r._PINS904["target_image_ref"],
                "browser_image": r._PINS904["browser_image_ref"],
                "legacy_compose_dev": base.st_dev,
                "legacy_compose_ino": base.st_ino,
            }
        )
    )
    (root / "unreportable-private-sentinel").touch()
    actuator = home / r._ACT
    actuator.mkdir(mode=0o700)
    (actuator / "attempt").write_text(r.R904 + "\n")
    (actuator / "attempt").chmod(0o600)
    (actuator / "socket").symlink_to(root, target_is_directory=True)
    (actuator / r._UNIT).touch(mode=0o600)
    units = home / r._USER
    units.mkdir(parents=True, mode=0o700)
    os.link(actuator / r._UNIT, units / r._UNIT)
    (units / "default.target.wants").mkdir()
    (units / "default.target.wants" / r._UNIT).symlink_to("../" + r._UNIT)
    observed = r._files904(root, home, os.geteuid())
    facts, checks = observed["inodes"], observed["checks"]
    assert checks["compose"] is True and checks["root"] == 1
    assert checks["stage_marker"] == [base.st_dev, base.st_ino] == facts["compose"][1:3]
    assert checks["attempt"] is True and checks["enabled_socket"] is True
    assert facts["installed_socket"] == facts["socket_unit"] and facts["socket_unit"][4] == 2
    assert facts["socket_dir"][0] == "link" and facts["endpoint"] == "UNSAFE"
    assert not (root / "control.sock").exists() and "unreportable-private-sentinel" not in str(
        observed
    )
    (actuator / "attempt").write_text("some-other-attempt")
    (root / "compose.beta.yaml").write_bytes(b"unreportable-private-sentinel")
    current = r._files904(root, home, os.geteuid())
    assert current["checks"]["compose"] is False and current["checks"]["attempt"] is False
    assert "unreportable-private-sentinel" not in str(current)


@pytest.fixture
def readback(tmp_path, monkeypatch):
    r = reconcile
    candid = "a0db3bf1f723bc6abdaa7f1b4ccb79b35c3bf298266c7f6fc01543c1afef9acd"
    worker = "0b6c1b863d0925918ab68965d4bf397dda1999b5b185182454518cf0b6d91598"
    intent = {**json.loads(_intent()), **r._PINS904, "attempt_id": r.R904}
    raw = r._canonical(intent)
    result = {
        **json.loads(_result()),
        "attempt_id": r.R904,
        "legacy_id": r.LEGACY904,
        "legacy_source_sha": r._PINS904["legacy_source_sha"],
        "target_source_sha": r.R904_SHA,
        "intent_sha256": hashlib.sha256(raw).hexdigest(),
        "candidate_id": candid,
        "cleanup": "NO_GO",
        "worker_id": worker,
    }
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / r.RECEIPT_DIR).mkdir(mode=0o700)
    (home / r.RECEIPT_DIR / f"boca-cutover-a-intent-{r.R904}.json").write_bytes(raw)
    (home / r.RECEIPT_DIR / f"boca-cutover-a-result-{r.R904}.json").write_bytes(
        r._canonical(result)
    )
    monkeypatch.setattr(r, "_private_home", lambda: home)
    monkeypatch.setattr(r.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(r.os, "getegid", lambda: 10001)
    monkeypatch.setattr(
        r,
        "_read_private",
        lambda name, *, directory: (
            (directory / name).read_bytes() if (directory / name).is_file() else None
        ),
    )
    raw_stage = r._stage_preflight(None)
    raw_stage.update(
        reason="STAGE_ROOT_ENTRIES",
        root_entries_count=2,
        plan_hashes_unique=True,
        legacy_target_compose_equal=True,
    )
    monkeypatch.setattr(r, "_stage_preflight", lambda intent: dict(raw_stage))
    monkeypatch.setattr(
        r,
        "_staged_attempt",
        lambda attempt: {
            "stage": "PRESENT",
            "promotion_intent": "ABSENT",
            "promotion_result": "ABSENT",
        },
    )
    historical_files = r._files904(tmp_path / "absent-stage", home, 10001)
    nodes, checks = historical_files["inodes"], historical_files["checks"]
    nodes.update(dict.fromkeys(r._ACT904, "ABSENT"))
    for key, kind, ino, mode in (
        ("root", "dir", 3362, 0o700),
        ("compose", "file", 3220, 0o644),
        ("stage", "dir", 3145755, 0o700),
        ("stage_marker", "file", 3145756, 0o600),
        ("stage_base", "file", 3145757, 0o600),
        ("stage_overlay", "file", 3145758, 0o600),
        ("stage_seccomp", "file", 3145759, 0o600),
    ):
        nodes[key] = [kind, 64769, ino, mode, 2 if kind == "dir" else 1, True]
    checks.update(
        root=0,
        stage=0,
        stage_marker=[64769, 3220],
        compose=True,
        stage_base=True,
        stage_overlay=True,
        stage_seccomp=True,
    )
    monkeypatch.setattr(r, "_files904", lambda *args: copy.deepcopy(historical_files))
    items = [
        _container(ident, service=service, revision=revision, name=name, running=running)
        for ident, service, revision, name, running in (
            (
                r.LEGACY904,
                "controller",
                r._PINS904["legacy_source_sha"],
                "/boca-socios-controller-legacy-" + r.R904,
                False,
            ),
            (candid, "controller", r.R904_SHA, "/boca-socios-controller-1", True),
            (worker, "browser-worker", r.R904_SHA, "/boca-socios-browser-worker-1", False),
        )
    ]
    items[0]["attempt"] = None
    items[1]["health"] = "private-sentinel"
    items[2]["port_binding"] = {"private-sentinel": []}
    monkeypatch.setattr(r, "_docker_snapshot", lambda: sorted(items, key=lambda row: row["id"]))

    def inspect(*argv, **kwargs):
        cid = argv[-1]
        if argv[:6] == (
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "id=" + cid.removeprefix("id="),
        ):
            return cid.removeprefix("id=")
        if argv[2] in (r.PINNED_RUNTIME_FORMAT, r.PINNED_CONFIG_FORMAT):
            is_old, is_candidate = cid == r.LEGACY904, cid == candid
            if argv[2] == r.PINNED_RUNTIME_FORMAT:
                return json.dumps(
                    [
                        cid,
                        r.PROJECT,
                        "exited" if is_old else "running" if is_candidate else "created",
                        42 if is_candidate else 0,
                        "healthy" if is_candidate else None,
                        2 if is_candidate else 0,
                        {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
                        if is_candidate
                        else {},
                    ]
                )
            row = next(item for item in items if item["id"] == cid)
            return json.dumps(
                [
                    cid,
                    r.PROJECT,
                    row["name"],
                    r._PINS904[
                        "legacy_image_ref"
                        if is_old
                        else "target_image_ref"
                        if is_candidate
                        else "browser_image_ref"
                    ],
                    row["image_id"],
                    row["service"],
                    row["revision"],
                    None if is_old else r.R904,
                    "unless-stopped" if is_candidate else "no",
                    {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
                    if cid != worker
                    else {},
                ]
            )
        assert argv[:2] == ("inspect", "--format") and argv[-1] in {x["id"] for x in items}
        return json.dumps(
            [
                argv[-1],
                "created"
                if argv[-1] == worker
                else "exited"
                if argv[-1] == r.LEGACY904
                else "running",
                42 if argv[-1] == candid else 0,
                r._PINS904[
                    "legacy_image_ref"
                    if argv[-1] == r.LEGACY904
                    else "browser_image_ref"
                    if argv[-1] == worker
                    else "target_image_ref"
                ],
                "unless-stopped" if argv[-1] == candid else "no",
                2 if argv[-1] == candid else 0,
            ]
        )

    monkeypatch.setattr(r, "_docker", inspect)

    def observed():
        return r._host(r.R904, None, source_sha=r.R904_SHA)

    return observed, home, result


def test_exact_incident_accepts_a_restored_or_parked_original_and_no_prepare(readback):
    r = reconcile
    observe, home, result = readback
    case = observe()
    raw = r._canonical(case) + b"\n"
    assert r.verify_runner(raw, r.R904, None, source_sha=r.R904_SHA) == case
    assert case["terminal_state"] == "NO_GO" and case["original"]["running"] is False
    assert (
        case["terminal_ids"]["candidate_id"] == result["candidate_id"]
        and len(case["boca_inventory"]) == 3
    )
    assert (
        case["processes"][result["worker_id"]][:2] == ["created", 0]
        and case["processes"][result["candidate_id"]][-1] == 2
        and b"private-sentinel" not in raw
    )
    with pytest.raises(r.ReconcileError):
        r.verify_runner(raw, r.R904, "123")
    with pytest.raises(r.ReconcileError):
        r.verify_runner(raw, r.R904, None, source_sha="a" * 40)
    with pytest.raises(r.ReconcileError):
        r.verified_cleanup_legacy_id(raw, r.R904, r.R904_SHA, v3=True)
    p = home / r.RECEIPT_DIR / f"boca-cutover-a-result-{r.R904}.json"
    p.write_bytes(
        r._canonical(
            {**result, "state": "RECOVERED", "cleanup": "ACCEPT", "original_restored": True}
        )
    )
    assert observe()["terminal_state"] == "RECOVERED"
    p.unlink()
    incomplete = observe()
    assert incomplete["result"] == "ABSENT" and incomplete["terminal_ids"] == {
        "candidate_id": None,
        "worker_id": None,
    }
    assert incomplete["original"]["id"] == r.LEGACY904
    assert (
        r.verify_runner(r._canonical(incomplete) + b"\n", r.R904, None, source_sha=r.R904_SHA)
        == incomplete
    )


@pytest.mark.parametrize(
    "change",
    [
        "freeform-nested",
        "foreign-name",
        "pid-type",
        "restart-count-type",
        "terminal-alias",
        "stage",
        "downgrade",
    ],
)
def test_reader_fails_closed_without_echoing_host_bytes(readback, change):
    r = reconcile
    observe, _, _ = readback
    obj = copy.deepcopy(observe())
    if change == "freeform-nested":
        obj["incident_files"]["checks"]["stage_marker"] = "private-sentinel"
    if change == "foreign-name":
        obj["boca_inventory"][0]["name"] = "/boca-socios-private-sentinel"
    if change == "pid-type":
        obj["processes"][r.LEGACY904][1] = True
    if change == "restart-count-type":
        obj["processes"][r.LEGACY904][-1] = True
    if change == "terminal-alias":
        obj["terminal_ids"]["candidate_id"] = r.LEGACY904
    if change == "stage":
        obj["stage_preflight"]["reason"] = "private-sentinel"
    if change == "downgrade":
        obj["version"] = "boca-postapply-reconcile-v3"
    with pytest.raises(r.ReconcileError) as caught:
        r.verify_runner(r._canonical(obj) + b"\n", r.R904, None, source_sha=r.R904_SHA)
    assert "private-sentinel" not in str(caught.value)


def test_unstable_file_keeps_other_files_docker_and_terminal(readback, monkeypatch):
    r = reconcile
    observe, _, result = readback
    case = observe()
    original = case["incident_files"]
    changed = copy.deepcopy(original)
    changed["inodes"]["compose"] = "UNSAFE"
    values = iter((original, changed))
    monkeypatch.setattr(r, "_files904", lambda *args: next(values))
    partial = observe()
    assert partial["incident_files"]["inodes"]["compose"] == "UNSTABLE"
    assert partial["incident_files"]["checks"]["compose"] is None
    assert partial["incident_files"]["inodes"]["stage"] == changed["inodes"]["stage"]
    assert partial["processes"][result["worker_id"]][:2] == ["created", 0]
    assert partial["terminal_state"] == "NO_GO"
    assert (
        r.verify_runner(r._canonical(partial) + b"\n", r.R904, None, source_sha=r.R904_SHA)
        == partial
    )


def test_failed_boca_listing_keeps_terminal_and_file_evidence_without_reporting_zero(
    readback, monkeypatch
):
    r = reconcile
    observe, _, _ = readback
    before = observe()

    def unavailable():
        raise r.ReconcileError("private-sentinel")

    monkeypatch.setattr(r, "_docker_snapshot", unavailable)
    obj = observe()
    assert obj["inventory_state"] == "INDETERMINATE" and obj["boca_containers"] is None
    assert obj["port_8443"] == "UNVERIFIED" and obj["incident_files"] == before["incident_files"]
    assert obj["terminal_ids"] == before["terminal_ids"] and obj["result"] == "PRESENT"
    raw = r._canonical(obj) + b"\n"
    assert (
        b"private-sentinel" not in raw
        and r.verify_runner(raw, r.R904, None, source_sha=r.R904_SHA) == obj
    )
    obj["boca_containers"] = 0
    with pytest.raises(r.ReconcileError):
        r.verify_runner(r._canonical(obj) + b"\n", r.R904, None, source_sha=r.R904_SHA)


def test_unknown_process_retains_other_containers_files_and_terminal(readback, monkeypatch):
    r = reconcile
    observe, _, result = readback
    before = observe()
    inspect = r._docker

    def changed(*args, **kwargs):
        if (
            args[:2] == ("inspect", "--format")
            and args[2] not in (r.PINNED_RUNTIME_FORMAT, r.PINNED_CONFIG_FORMAT)
            and args[-1] == result["worker_id"]
        ):
            return json.dumps([args[-1], "private-sentinel", 0, "", "no", 0])
        return inspect(*args)

    monkeypatch.setattr(r, "_docker", changed)
    obj = observe()
    assert obj["processes"][result["worker_id"]] == "INDETERMINATE"
    assert obj["processes"][result["candidate_id"]] == before["processes"][result["candidate_id"]]
    assert obj["processes"][r.LEGACY904] == before["processes"][r.LEGACY904]
    assert (
        obj["incident_files"] == before["incident_files"]
        and obj["terminal_ids"] == before["terminal_ids"]
    )
    raw = r._canonical(obj) + b"\n"
    assert (
        b"private-sentinel" not in raw
        and r.verify_runner(raw, r.R904, None, source_sha=r.R904_SHA) == obj
    )


def test_908_repeat_exact_cid_observations_survive_an_unavailable_project_listing(
    readback, monkeypatch
):
    r = reconcile
    observe, _, result = readback

    def unavailable():
        raise r.ReconcileError("DOCKER_PROJECT_LIST")

    monkeypatch.setattr(r, "_docker_snapshot", unavailable)
    case = observe()
    assert case["inventory_reason"] == "PROJECT_LIST_FAILED"
    pins = case["pinned_containers"]
    assert set(pins) == {r.LEGACY904, result["candidate_id"], result["worker_id"]}
    assert pins[r.LEGACY904]["attributes"]["state"] == "exited"
    assert pins[r.LEGACY904]["attributes"]["port_binding"] == "LOOPBACK_8443"
    assert pins[result["candidate_id"]]["attributes"]["restart_count"] == 2
    assert pins[result["worker_id"]]["attributes"]["state"] == "created"
    assert pins[result["worker_id"]]["attributes"]["health"] == "NONE"
    assert all(x["presence"] == "PRESENT" for x in pins.values())
    assert r.verify_runner(r._canonical(case) + b"\n", r.R904, None, source_sha=r.R904_SHA) == case
    with pytest.raises(r.ReconcileError):
        r.recovery_profile904(case)


def test_908_eligibility_requires_matching_stable_listed_and_pinned_parked_case(
    readback, monkeypatch
):
    r = reconcile
    observe, _, result = readback
    items = copy.deepcopy(r._docker_snapshot())
    for item in items:
        if item["id"] == result["candidate_id"]:
            item["health"] = "healthy"
        if item["id"] == result["worker_id"]:
            item["port_binding"] = {}
        item["attempt"] = None if item["id"] == r.LEGACY904 else r.R904
    monkeypatch.setattr(r, "_docker_snapshot", lambda: items)
    case = observe()
    assert r.recovery_profile904(case) == "OLD_PARKED"
    pin = case["pinned_containers"][result["worker_id"]]
    pin["attributes"]["state"] = "running"
    with pytest.raises(r.ReconcileError):
        r.recovery_profile904(case)


@pytest.mark.parametrize(
    ("first", "last", "presence", "reason"),
    [
        ("", "", "ABSENT", "EXACT_ID"),
        ("ERROR", "ERROR", "INDETERMINATE", "ID_QUERY_FAILED"),
        ("SHORT", "SHORT", "INDETERMINATE", "ID_QUERY_INVALID"),
        ("", "PRESENT", "INDETERMINATE", "ID_DRIFT"),
        ("PRESENT", "", "INDETERMINATE", "ID_DRIFT"),
    ],
)
def test_exact_absence_requires_two_successful_identical_id_filters(
    readback, monkeypatch, first, last, presence, reason
):
    r = reconcile
    observe, _, _ = readback
    original = r._docker
    answers = iter((first, last))

    def docker(*argv, **kwargs):
        if argv == ("ps", "-a", "-q", "--no-trunc", "--filter", "id=" + r.WORKER904):
            answer = next(answers)
            if answer == "ERROR":
                raise r.ReconcileError("private-sentinel")
            return {"PRESENT": r.WORKER904, "SHORT": r.WORKER904[:12]}.get(answer, answer)
        return original(*argv, **kwargs)

    monkeypatch.setattr(r, "_docker", docker)
    raw = r._canonical(observe()) + b"\n"
    record = r.verify_runner(raw, r.R904, None, source_sha=r.R904_SHA)
    assert record["pinned_containers"][r.WORKER904] == {
        "presence": presence,
        "reason": reason,
        "groups": {},
        "attributes": {},
    }
    assert b"private-sentinel" not in raw
    assert record["pinned_containers"][r.LEGACY904]["attributes"]["state"] == "exited"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("error", "QUERY_FAILED"),
        ("format", "BAD_FORMAT"),
        ("project", "IDENTITY"),
        ("id", "IDENTITY"),
    ],
)
def test_inspect_failure_never_claims_absence_or_erases_other_fields(
    readback, monkeypatch, error, reason
):
    r = reconcile
    observe, _, _ = readback
    original = r._docker

    def docker(*args, **kwargs):
        if args == ("inspect", "--format", r.PINNED_RUNTIME_FORMAT, r.WORKER904):
            if error == "error":
                raise r.ReconcileError("private-sentinel")
            if error == "format":
                return "private-sentinel"
            data = json.loads(original(*args, **kwargs))
            data[1 if error == "project" else 0] = "private-sentinel"
            return json.dumps(data)
        return original(*args, **kwargs)

    monkeypatch.setattr(r, "_docker", docker)
    raw = r._canonical(observe()) + b"\n"
    assert b"private-sentinel" not in raw
    case = r.verify_runner(raw, r.R904, None, source_sha=r.R904_SHA)
    pin = case["pinned_containers"][r.WORKER904]
    assert pin["presence"] == "PRESENT" and pin["groups"] == {"config": "OK", "runtime": reason}
    assert (
        pin["attributes"]["pid"] == "UNKNOWN"
        and pin["attributes"]["image"] == r._PINS904["browser_image_ref"]
    )
    assert case["pinned_containers"][r.LEGACY904]["attributes"]["state"] == "exited"
    with pytest.raises(r.ReconcileError):
        r.recovery_profile904(case)


def test_pid_change_preserves_stable_fields_and_runner_rejects_forged_unknown_reason(
    readback, monkeypatch
):
    r = reconcile
    observe, _, _ = readback
    original = r._docker
    pids = iter((72, 75))

    def docker(*args, **kwargs):
        line = original(*args, **kwargs)
        if args == ("inspect", "--format", r.PINNED_RUNTIME_FORMAT, r.CANDIDATE904):
            data = json.loads(line)
            data[3] = next(pids)
            return json.dumps(data)
        return line

    monkeypatch.setattr(r, "_docker", docker)
    case = observe()
    pin = case["pinned_containers"][r.CANDIDATE904]
    assert pin["groups"]["runtime"] == "DRIFT"
    assert pin["attributes"]["pid"] == "UNKNOWN" and pin["attributes"]["state"] == "running"
    raw = r._canonical(case) + b"\n"
    assert r.verify_runner(raw, r.R904, None, source_sha=r.R904_SHA) == case
    pin["groups"]["runtime"] = "private-sentinel"
    with pytest.raises(r.ReconcileError):
        r.verify_runner(r._canonical(case) + b"\n", r.R904, None, source_sha=r.R904_SHA)


def test_old_positive_readback_remains_readable_but_cannot_qualify_for_repair(readback):
    r = reconcile
    observe, _, _ = readback
    old = observe()
    old["version"] = "boca-postapply-reconcile-904-v1"
    old.pop("pinned_containers")
    old.pop("inventory_reason")
    assert r.verify_runner(r._canonical(old) + b"\n", r.R904, None, source_sha=r.R904_SHA) == old
    with pytest.raises(r.ReconcileError):
        r.recovery_profile904(old)


@pytest.mark.parametrize(
    ("state", "pid", "health", "policy", "published", "candidate", "extra", "expected"),
    [
        ("running", 95, "healthy", "unless-stopped", "loopback", False, False, "OLD_ACTIVE"),
        ("exited", 0, None, "no", "none", False, False, "OLD_RENAMED"),
        ("exited", 0, None, "no", "unbound", False, False, "OLD_RENAMED"),
        ("running", 95, "healthy", "no", "loopback", False, False, "OLD_STARTED"),
        ("exited", 0, None, "no", "none", True, False, None),
        ("running", 95, "healthy", "no", "loopback", True, False, None),
        ("exited", 0, None, "no", "none", False, True, None),
        ("running", 95, "healthy", "no", "loopback", False, True, None),
        ("exited", 0, None, "unless-stopped", "none", False, False, None),
        ("running", 95, "starting", "no", "loopback", False, False, None),
        ("running", 0, "healthy", "no", "loopback", False, False, None),
        ("exited", 29, None, "no", "none", False, False, None),
        ("exited", 0, None, "no", "loopback", False, False, None),
        ("running", 95, "healthy", "no", "none", False, False, None),
    ],
)
def test_canonical_original_requires_exact_profile_and_absent_candidate(
    readback, monkeypatch, state, pid, health, policy, published, candidate, extra, expected
):
    r = reconcile
    observe, _, _ = readback
    initial = r._docker
    items = {x["id"]: copy.deepcopy(x) for x in r._docker_snapshot()}
    original = items[r.LEGACY904]
    original.update(
        {
            "running": state == "running",
            "name": "/boca-socios-controller-1",
            "health": health,
            "attempt": None,
        }
    )
    inventory = [original]
    if candidate:
        c = items[r.CANDIDATE904]
        c.update(attempt=r.R904, health="healthy")
        inventory.append(c)
    if extra:
        inventory.append({**original, "id": "f" * 64})
    monkeypatch.setattr(r, "_docker_snapshot", lambda: sorted(inventory, key=lambda x: x["id"]))
    ports = {"none": {}, "unbound": {"8443/tcp": None}, "loopback": original["port_binding"]}[
        published
    ]

    def docker(*args, **kwargs):
        if args[:2] == ("ps", "-a") and args[-1] in (
            ("id=" + r.WORKER904,) if candidate else ("id=" + r.WORKER904, "id=" + r.CANDIDATE904)
        ):
            return ""
        if extra and args[:2] == ("inspect", "--format") and args[-1] == "f" * 64:
            return json.dumps([args[-1], "running", 32, r._PINS904["legacy_image_ref"], policy, 0])
        value = initial(*args, **kwargs)
        if args[:2] == ("inspect", "--format") and args[-1] == r.LEGACY904:
            row = json.loads(value)
            if args[2] == r.PINNED_RUNTIME_FORMAT:
                row[2:7] = [state, pid, health, 4, ports]
            elif args[2] == r.PINNED_CONFIG_FORMAT:
                row[2] = original["name"]
                row[-2] = policy
            else:
                row[1:] = [state, pid, r._PINS904["legacy_image_ref"], policy, 4]
            return json.dumps(row)
        return value

    monkeypatch.setattr(r, "_docker", docker)
    case = observe()
    if expected is None:
        with pytest.raises(r.ReconcileError):
            r.recovery_profile904(case)
    else:
        assert r.recovery_profile904(case) == expected
        assert case["pinned_containers"][r.CANDIDATE904]["presence"] == "ABSENT"
        for part, key, value in (
            ("checks", "stage", 1),
            ("checks", "root", 1),
            ("checks", "stage_marker", [64769, 3219]),
            ("checks", "stage_seccomp", False),
            ("inodes", "enabled_socket", ["link", 64769, 91, 511, 1, True]),
            ("inodes", "binding", ["file", 64769, 92, 384, 1, True]),
        ):
            tainted = copy.deepcopy(case)
            tainted["incident_files"][part][key] = value
            with pytest.raises(r.ReconcileError):
                r.recovery_profile904(tainted)


def test_908_directory_does_not_supply_a_different_cid_for_docker(readback, monkeypatch):
    r = reconcile
    observe, home, result = readback
    path = home / r.RECEIPT_DIR / f"boca-cutover-a-result-{r.R904}.json"
    path.write_bytes(r._canonical({**result, "worker_id": "5" * 64}))

    def forbidden(*args, **kwargs):
        pytest.fail("Docker was queried with an unauthenticated terminal")

    monkeypatch.setattr(r, "_docker_snapshot", forbidden)
    monkeypatch.setattr(r, "_docker", forbidden)
    with pytest.raises(r.ReconcileError, match="R904_TERMINAL"):
        observe()


def test_908_stage_gate_requires_clean_exact_slots_before_and_after_removal(readback):
    r = reconcile
    observe, _, _ = readback
    facts = observe()["incident_files"]
    assert r.stage_files_match_908(facts)
    assert not r.stage_files_match_908(facts, present=False)
    nodes, checks = facts["inodes"], facts["checks"]
    for key in ("stage", "stage_marker", "stage_base", "stage_overlay", "stage_seccomp"):
        nodes[key] = "ABSENT"
        checks[key] = None
    assert r.stage_files_match_908(facts, present=False)
    assert not r.stage_files_match_908(facts)
    changed = copy.deepcopy(facts)
    changed["inodes"]["compose"][2] += 1
    assert not r.stage_files_match_908(changed, present=False)
    nodes["promote_intent"] = "UNREADABLE"
    assert not r.stage_files_match_908(facts, present=False)
