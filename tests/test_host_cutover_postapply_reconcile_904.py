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
    candid, worker = "8" * 64, "9" * 64
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
    monkeypatch.setattr(r, "_stage_preflight", lambda intent: dict(raw_stage))
    monkeypatch.setattr(
        r,
        "_staged_attempt",
        lambda attempt: dict.fromkeys(("stage", "promotion_intent", "promotion_result"), "ABSENT"),
    )
    original_files = r._files904
    monkeypatch.setattr(
        r, "_files904", lambda *args: original_files(tmp_path / "absent-stage", home, 10001)
    )
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
    monkeypatch.setattr(r, "_docker_snapshot", lambda: items)

    def inspect(*argv):
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
                "no",
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

    def changed(*args):
        if args[-1] == result["worker_id"]:
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
