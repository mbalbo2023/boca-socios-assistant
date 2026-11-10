"""Rootless Cutover idle admission, with Docker and the host service replaced by doubles."""

from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios import worker_start_capture
from test_cutover_prearmed import capture_identity
from test_host_cutover_adapter import (
    ATTEMPT,
    CONFIG_HASH,
    LEGACY_IMAGE,
    LEGACY_SHA,
    ORIGINAL_ID,
    OWNER,
    SECCOMP,
    SECCOMP_SHA,
    TARGET_IMAGE,
    TARGET_SHA,
    WORKER_ID,
    WORKER_IMAGE,
    _worker_preparation_fake,
)


def test_idle_install_create_never_attaches_or_starts(monkeypatch):
    calls, legacy, worker = _worker_preparation_fake(monkeypatch)
    monkeypatch.setattr(worker_start_capture, "attach_output", lambda *a: pytest.fail("attach"))
    checks = []

    def preflight(cid, image, revision, attempt, config_hash, *, on_demand):
        assert (cid, image, revision, attempt, config_hash) == (
            WORKER_ID,
            WORKER_IMAGE,
            TARGET_SHA,
            ATTEMPT,
            CONFIG_HASH,
        )
        checks.append(on_demand)

    monkeypatch.setattr(host, "_cutover_capture_preflight", preflight)
    result = host._cutover_prepare_worker(
        ORIGINAL_ID,
        LEGACY_IMAGE,
        LEGACY_SHA,
        WORKER_IMAGE,
        TARGET_SHA,
        ATTEMPT,
        CONFIG_HASH,
        SECCOMP_SHA,
        SECCOMP,
        lambda *_: pytest.fail("capture"),
        on_demand=True,
    )
    assert checks == [True] and result == WORKER_ID
    assert worker == {"exists": True, "running": False, "volume": True}
    assert legacy["State"]["Running"] is True
    assert not any(cmd[:2] in (("docker", "start"), ("docker", "exec")) for cmd in calls)
    create = next(cmd for cmd in calls if cmd[:2] == ("docker", "create"))
    assert create[create.index("--health-cmd") + 1] == (
        "python -m boca_socios.browser.worker_health >/dev/null 2>&1"
    )


@pytest.mark.parametrize(
    "wrong",
    [
        {"pid": 1},
        {"pid": False},
        {"status": "exited"},
        {"running": True},
        {"paused": True},
        {"dead": True},
    ],
)
def test_cold_identity_rejects_running_or_previously_started_workers(monkeypatch, wrong):
    record, _ = capture_identity(monkeypatch)
    record.update(pid=0, running=False, paused=False, dead=False, restarting=False)
    host._cutover_capture_preflight(
        WORKER_ID, WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH, on_demand=True
    )
    record.update(wrong)
    with pytest.raises(host.PreflightError):
        host._cutover_capture_preflight(
            WORKER_ID, WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH, on_demand=True
        )


def test_subsequent_start_requires_positively_matched_exited_worker(monkeypatch):
    record, _ = capture_identity(monkeypatch)
    record.update(pid=0, running=False, paused=False, dead=False, restarting=False, status="exited")
    host._cutover_capture_preflight(
        WORKER_ID,
        WORKER_IMAGE,
        TARGET_SHA,
        ATTEMPT,
        CONFIG_HASH,
        on_demand=True,
        expected_state="exited",
    )
    with pytest.raises(host.PreflightError):
        host._cutover_capture_preflight(
            WORKER_ID, WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH, expected_state="exited"
        )


def test_control_mount_and_profile_are_controller_only():
    directory = Path("/home/boca-deploy/.boca-on-demand/socket")
    create = host._cutover_candidate_create_argv(
        TARGET_IMAGE,
        TARGET_SHA,
        ATTEMPT,
        "http://localhost:8443",
        OWNER,
        CONFIG_HASH,
        control_directory=directory,
    )
    assert "BOCA_BOT_CONTROL=on-demand" in create
    assert create[create.index("--restart") + 1] == "unless-stopped"
    assert f"type=bind,source={directory},target=/run/boca-bot-control,readonly" in create
    worker = host._cutover_worker_create_argv(
        WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH, on_demand=True
    )
    assert all(
        "boca-bot-control" not in value and "BOCA_BOT_CONTROL" not in value for value in worker
    )


@pytest.mark.parametrize("mutation", ["valid", "legacy", "worker-bind", "controller-rw", "foreign"])
def test_on_demand_exact_bind_is_admitted_only_in_a_reviewed_cutover(monkeypatch, mutation):
    import json

    from test_beta_browser_deploy_contract import ATTEMPT, BROWSER_IMAGE, on_demand_model
    from test_beta_deploy_contract import ORIGIN, OWNER
    from test_deploy_contract import IMAGE

    model = on_demand_model()
    controller, worker = (model["services"][s] for s in ("controller", "browser-worker"))
    directory = Path("/home/boca-deploy/.boca-on-demand/socket")
    bind = controller["volumes"][-1]
    if mutation == "worker-bind":
        worker["volumes"].append(bind)
    elif mutation == "controller-rw":
        bind["read_only"] = False
    elif mutation == "foreign":
        bind["source"] = "/run/docker"
    stage = host.ROOT / f"cutover-a-{ATTEMPT}"
    worker["security_opt"][1] = "seccomp=" + str(stage / host.BROWSER_SECCOMP.name)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: json.dumps(model))
    args = dict(
        base_file=stage / host.BETA_COMPOSE.name,
        overlay_file=stage / host.BROWSER_COMPOSE.name,
        seccomp_file=stage / host.BROWSER_SECCOMP.name,
    )
    if mutation != "legacy":
        args["control_directory"] = directory
    if mutation == "valid":
        assert host._browser_compose_model(IMAGE, ORIGIN, OWNER, BROWSER_IMAGE, ATTEMPT, **args)
    else:
        with pytest.raises(host.PreflightError):
            host._browser_compose_model(IMAGE, ORIGIN, OWNER, BROWSER_IMAGE, ATTEMPT, **args)


def test_controller_mount_cli_refuses_host_paths_outside_its_control_directory():
    with pytest.raises(host.PreflightError):
        host._cutover_candidate_create_argv(
            TARGET_IMAGE,
            TARGET_SHA,
            ATTEMPT,
            "http://localhost:8443",
            OWNER,
            CONFIG_HASH,
            control_directory=Path("/"),
        )
