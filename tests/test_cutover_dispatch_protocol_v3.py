"""V3 producer/consumer contract: no PREPARE, no weakened cleanup path."""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover_cli as cli
from boca_socios import host_first_deploy as host
from boca_socios.host_boca_cutover import CutoverReceipt
from test_boca_deploy_dispatch_v3 import evidence, gate
from test_cutover_a_go import _actions_fixture, _file, go


def _v3(tmp_path: Path) -> tuple[go.GoRequest, dict[str, str], str]:
    assert hasattr(cli, "VERSION_DISPATCH"), "V3 needs its own non-legacy host protocol"
    request, env = _actions_fixture(tmp_path)
    token = cli.encode_invocation(
        request.plan,
        bundle_sha256=go.hash_reviewed_file(request.bundle_path),
        go_binding_sha256="b" * 64,
        dispatch_v3=True,
    )
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_INVOCATION_NAME, (token + "\n").encode())
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_APPROVAL_NAME, ("b" * 64 + "\n").encode())
    env.update(BOCA_CUTOVER_A_GO_PREFLIGHT="success", BOCA_CUTOVER_A_HOST_APPLY="success")
    return request, env, token


@pytest.mark.parametrize("idle_install", [False, True])
@pytest.mark.parametrize("cleanup_present", [False, True])
def test_v3_requires_cleanup_without_prepare_and_consumes_real_observe_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_present: bool,
    idle_install: bool,
) -> None:
    request, env, token = _v3(tmp_path)
    plan = request.plan
    assert cli.CutoverInvocation.decode(token).prepare_run_id is None
    disk = cleanup.DiskInodes(1000, 100, 3000, 300, 8, 10, 16, 18)
    detail = cleanup.CleanupReceipt("SUCCESS", plan.attempt_id, "ACCEPT", disk, disk, (), (), ())
    # Keep the actual observer's validation and output producer; replace only
    # its physical Docker/filesystem boundaries with synthetic observations.
    monkeypatch.setattr(host, "_browser_engine_version", lambda: "28.0.0")
    monkeypatch.setattr(
        host,
        "_beta_acceptance_status",
        lambda *_a: (SimpleNamespace(container_id=plan.legacy_id, health="healthy"), object()),
    )
    monkeypatch.setattr(
        host, "_names", lambda *_a: {host.OWNER_VOLUME, host.KEY_VOLUME, host.DATA_VOLUME}
    )
    monkeypatch.setattr(host, "_browser_inventory", lambda **_kw: None)
    monkeypatch.setattr(host, "_browser_root_entries", lambda *_a: None)

    def execute(_plan: object) -> CutoverReceipt:
        host._cutover_observe(
            plan.legacy_image,
            plan.legacy_sha,
            plan.legacy_compose_sha,
            plan.origin,
            plan.owner_subject,
            plan.target_image,
            plan.target_sha,
            plan.browser_image,
            plan.legacy_id,
        )
        return CutoverReceipt(
            plan.attempt_id,
            "ACCEPTED",
            "ACCEPT",
            False,
            True,
            "2" * 64,
            "3" * 64,
            cleanup_receipt=detail if cleanup_present else None,
            idle_installed=idle_install,
        )

    fd = os.memfd_create("boca-v3-test", flags=0)
    try:
        os.write(fd, request.bundle_path.read_bytes())
        monkeypatch.setattr(sys, "argv", [f"/proc/self/fd/{fd}"])
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.run_cli(
                token,
                approved_go_binding_sha256="b" * 64,
                dispatch_v3=True,
                execute=execute,
                reconcile=lambda *_a: None,
            )
    finally:
        os.close(fd)
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, out.getvalue().encode())
    if idle_install:
        env["BOCA_REQUIRE_IDLE_INSTALL"] = "1"
    if not cleanup_present:
        assert rc == 3 and "state=ACCEPTED" not in out.getvalue()
        with pytest.raises(go.CutoverGoError):
            go.assert_actions_host_receipt(env)
    else:
        assert rc == 0
        assert go.assert_actions_host_receipt(env) is not None
        if idle_install:
            missing = out.getvalue().replace(cli.IDLE_RECEIPT + "\n", "")
            _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, missing.encode())
            with pytest.raises(go.CutoverGoError):
                go.assert_actions_host_receipt(env)
        else:
            with pytest.raises(go.CutoverGoError):
                go.assert_actions_host_receipt({**env, "BOCA_REQUIRE_IDLE_INSTALL": "1"})
        original = out.getvalue()
        for bad in (
            original.replace("BOCA_CUTOVER_A_POSTFLIGHT ", "WRONG "),
            original.replace(plan.legacy_id, "9" * 64, 1),
            original + original,
            "\n".join(original.splitlines()[1:]) + "\n",
        ):
            _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, bad.encode())
            with pytest.raises(go.CutoverGoError):
                go.assert_actions_host_receipt(env)


def test_v3_cannot_enter_legacy_cli_and_legacy_cannot_enter_v3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _, token = _v3(tmp_path)
    monkeypatch.setattr(cli, "_bundle_digest", lambda: go.hash_reviewed_file(request.bundle_path))
    effects: list[str] = []

    def execute(_plan: object) -> CutoverReceipt:
        effects.append("effect")
        raise AssertionError("must not execute")

    assert cli.run_cli(token, approved_go_binding_sha256="b" * 64, execute=execute) == 3
    old = cli.encode_invocation(
        request.plan,
        bundle_sha256=go.hash_reviewed_file(request.bundle_path),
        go_binding_sha256="b" * 64,
    )
    assert (
        cli.run_cli(old, approved_go_binding_sha256="b" * 64, dispatch_v3=True, execute=execute)
        == 3
    )
    assert effects == []


def test_dispatch_writes_run_bound_v3_without_manual_go_and_refuses_replay(tmp_path: Path) -> None:
    assert hasattr(cli, "VERSION_DISPATCH"), "V3 protocol required"
    request, env = _actions_fixture(tmp_path)
    dispatch_env, proof = evidence()
    # Align the independent Actions fixture to the reviewed source/run fixture.
    for key in ("GITHUB_SHA", "GITHUB_RUN_ID"):
        dispatch_env[key] = env[key]
    proof["run"].update(id=int(env["GITHUB_RUN_ID"]), head_sha=env["GITHUB_SHA"])
    proof["history"][0]["workflow_runs"] = [dict(proof["run"])]
    proof["main"]["object"]["sha"] = env["GITHUB_SHA"]
    proof["ci"][0]["workflow_runs"][0]["head_sha"] = env["GITHUB_SHA"]
    for check in proof["checks"][0]["check_runs"]:
        check["head_sha"] = env["GITHUB_SHA"]
    env.update(dispatch_env)
    gate().write_invocation(env, proof)
    token = (Path(env["RUNNER_TEMP"]) / go.HOST_INVOCATION_NAME).read_text().strip()
    invocation = cli.CutoverInvocation.decode(token)
    assert invocation.dispatch_v3 and invocation.plan == request.plan
    assert invocation.prepare_run_id is None
    with pytest.raises(ValueError):
        gate().write_invocation(env, proof)
