"""Selective compensation against Docker inspect-shaped controller records."""

from pathlib import Path
from typing import Any, cast

import pytest

from boca_socios import host_first_deploy as host
from test_host_browser_ipc_install import (
    ATTEMPT,
    CONTROLLER_ID,
    IMAGE,
    ORIGIN,
    OWNER,
    SOURCE,
    controller_record,
)
from test_host_cutover_adapter import CONFIG_HASH, LEGACY_IMAGE, LEGACY_SHA, ORIGINAL_ID

CONTROL_DIRECTORY = Path("/home/boca-deploy/.boca-on-demand/socket")
COORDINATES = (IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER, CONFIG_HASH)


@pytest.fixture
def candidate(monkeypatch):
    record = cast(dict[str, Any], controller_record())
    record["Config"]["Labels"]["com.docker.compose.config-hash"] = CONFIG_HASH
    record["Config"]["Env"].append("BOCA_BOT_CONTROL=on-demand")
    record["HostConfig"]["RestartPolicy"]["Name"] = "unless-stopped"
    record["Mounts"].append(
        {
            "Type": "bind",
            "Source": str(CONTROL_DIRECTORY),
            "Destination": "/run/boca-bot-control",
            "RW": False,
            "Propagation": "rprivate",
        }
    )
    record["State"].update(Status="running", Pid=27, Paused=False, Dead=False)
    record["RestartCount"] = 1
    census = [CONTROLLER_ID]
    effects = []

    def docker(*argv, **_kwargs):
        if argv[:2] == ("docker", "ps"):
            assert argv[:-1] == (
                "docker",
                "ps",
                "-a",
                "-q",
                "--no-trunc",
                "--filter",
            )
            if argv[-1] == f"id={CONTROLLER_ID}":
                return CONTROLLER_ID if CONTROLLER_ID in census else ""
            assert argv[-1] == "name=^/boca-socios-controller-1$"
            return "\n".join(census)
        effects.append(argv)
        if argv == ("docker", "stop", "--time", "8", CONTROLLER_ID):
            return "Flag --time has been deprecated, use --timeout instead\n" + CONTROLLER_ID
        if argv == ("docker", "stop", "-t", "8", CONTROLLER_ID):
            record["State"].update(Status="exited", Running=False, Pid=0)
            record["NetworkSettings"]["Ports"] = {}
        elif argv == ("docker", "rm", CONTROLLER_ID):
            census.clear()
        else:
            pytest.fail(f"unexpected mutation {argv}")
        return CONTROLLER_ID

    def inspect(cid):
        assert cid == CONTROLLER_ID
        return record

    monkeypatch.setattr(host, "_run", docker)
    monkeypatch.setattr(host, "_browser_inspect_record", inspect)
    monkeypatch.setattr(host, "_validate_boca_network", lambda *args: None)
    monkeypatch.setattr(
        host, "_browser_port_free", lambda **kwargs: effects.append(("port-free", kwargs))
    )
    monkeypatch.setattr(host, "_cutover_restore_original", lambda *args: effects.append(args))
    return record, census, effects


def compensate(pinned):
    host._cutover_compensate_candidate(
        ORIGINAL_ID,
        LEGACY_IMAGE,
        LEGACY_SHA,
        *COORDINATES,
        control_directory=CONTROL_DIRECTORY,
        expected_candidate=pinned,
    )


@pytest.mark.parametrize("running", [True, False])
def test_compensate_restarted_pinned_candidate_after_stable_inspect(candidate, running):
    record, _census, effects = candidate
    if not running:
        record["State"].update(Status="exited", Running=False, Pid=0)
        record["NetworkSettings"]["Ports"] = {}
    for verify_runtime in (False, True):
        with pytest.raises(host.PreflightError):
            host._cutover_candidate_postflight(
                CONTROLLER_ID,
                *COORDINATES,
                control_directory=CONTROL_DIRECTORY,
                verify_runtime=verify_runtime,
            )
    compensate(CONTROLLER_ID)
    assert effects == [
        *([("docker", "stop", "-t", "8", CONTROLLER_ID)] if running else []),
        ("docker", "rm", CONTROLLER_ID),
        ("port-free", {"after_candidate_removal": True}),
        (ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT),
    ]


@pytest.mark.parametrize(
    "pinned,observed",
    [
        (None, [CONTROLLER_ID]),
        (CONTROLLER_ID, []),
        (CONTROLLER_ID, ["b" * 64]),
        (CONTROLLER_ID[:12], [CONTROLLER_ID[:12]]),
        (CONTROLLER_ID, [CONTROLLER_ID, "b" * 64]),
        (ORIGINAL_ID, [ORIGINAL_ID]),
    ],
)
def test_missing_or_ambiguous_candidate_identity_has_no_effect(candidate, pinned, observed):
    record, census, effects = candidate
    record["RestartCount"] = 0
    census[:] = observed
    with pytest.raises(host.PreflightError):
        compensate(pinned)
    assert effects == []


def test_empty_inventory_before_create_can_revive_original_without_removing_any_cid(candidate):
    _record, census, effects = candidate
    census.clear()
    compensate(None)
    assert effects == [("port-free", {}), (ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)]


@pytest.mark.parametrize("ack", [CONTROLLER_ID[:12], ORIGINAL_ID, "warning\n" + CONTROLLER_ID, ""])
def test_ambiguous_stop_ack_after_physical_stop_keeps_candidate_and_parked_original(
    candidate, monkeypatch, ack
):
    record, census, effects = candidate
    run = host._run

    def docker(*args, **kwargs):
        value = run(*args, **kwargs)
        return ack if args[:2] == ("docker", "stop") else value

    monkeypatch.setattr(host, "_run", docker)
    with pytest.raises(host.PreflightError, match="stop receipt uncertain"):
        compensate(CONTROLLER_ID)
    assert record["State"]["Pid"] == 0 and census == [CONTROLLER_ID]
    assert effects == [("docker", "stop", "-t", "8", CONTROLLER_ID)]


def test_uncertain_post_stop_does_not_remove_candidate_or_unpark_original(candidate, monkeypatch):
    record, _census, effects = candidate
    run = host._run

    def docker(*args, **kwargs):
        result = run(*args, **kwargs)
        if args == ("docker", "stop", "-t", "8", CONTROLLER_ID):
            record["State"].update(Status="restarting", Restarting=True)
        return result

    monkeypatch.setattr(host, "_run", docker)
    with pytest.raises(host.PreflightError):
        compensate(CONTROLLER_ID)
    assert effects == [("docker", "stop", "-t", "8", CONTROLLER_ID)]


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("State", "Restarting", True),
        ("State", "Status", "restarting"),
        ("State", "Paused", True),
        ("State", "Dead", True),
        ("State", "Pid", 0),
        ("Config", "User", "0:0"),
        ("Labels", "com.docker.compose.config-hash", "0" * 64),
        ("HostConfig", "RestartPolicy", {"Name": "always", "MaximumRetryCount": 0}),
        ("record", "RestartCount", -1),
        ("record", "RestartCount", True),
    ],
)
def test_pinned_candidate_with_state_or_boundary_drift_has_no_effect(
    candidate, section, key, value
):
    record, _census, effects = candidate
    target = {"Labels": record["Config"]["Labels"], "record": record}.get(
        section, record.get(section)
    )
    target[key] = value
    with pytest.raises(host.PreflightError):
        compensate(CONTROLLER_ID)
    assert effects == []
