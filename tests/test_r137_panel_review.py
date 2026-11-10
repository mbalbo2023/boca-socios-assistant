"""Recovery must recognize two intermediate states produced by the real legacy restore."""

import json
from copy import deepcopy

import pytest

from boca_socios import host_first_deploy as host
from test_host_cutover_postapply_reconcile_904 import readback as readback
from test_host_cutover_postapply_reconcile_904 import reconcile


@pytest.mark.parametrize("started", [False, True], ids=["after-rename", "after-start"])
def test_known_original_survives_interrupted_restore(readback, monkeypatch, started):
    r = reconcile
    state = {"name": "/boca-socios-controller-legacy-" + r.R904, "running": False}
    with monkeypatch.context() as fault:
        fault.setattr(host, "_browser_inspect_record", lambda _cid: {"Name": state["name"]})

        def attest(cid, _image, _sha, *, name, running, restart_policy):
            assert cid == r.LEGACY904 and state == {"name": "/" + name, "running": running}
            assert restart_policy == "no"
            return {}

        def interrupted_at_port(**_kwargs):
            if not started:
                raise host.PreflightError("interrupted after rename")

        def run(*args, **_kwargs):
            if args == ("docker", "rename", r.LEGACY904, host.CUTOVER_LEGACY_NAME):
                state["name"] = "/" + host.CUTOVER_LEGACY_NAME
                return ""
            if args == ("docker", "start", r.LEGACY904):
                state["running"] = True
                return r.LEGACY904
            assert args == ("docker", "update", "--restart=unless-stopped", r.LEGACY904)
            raise host.PreflightError("interrupted after healthy start")

        fault.setattr(host, "_cutover_legacy_record", attest)
        fault.setattr(host, "_browser_port_free", interrupted_at_port)
        fault.setattr(host, "_browser_wait_healthy", lambda _cid: None)
        fault.setattr(host, "_run", run)
        with pytest.raises(host.PreflightError, match="interrupted"):
            host._cutover_restore_original(
                r.LEGACY904, r._PINS904["legacy_image_ref"], r._PINS904["legacy_source_sha"], r.R904
            )

    observe, _, _ = readback
    row = deepcopy(next(row for row in r._docker_snapshot() if row["id"] == r.LEGACY904))
    row.update(state, health="healthy" if started else None, attempt=None)
    monkeypatch.setattr(r, "_docker_snapshot", lambda: [row])
    prior = r._docker
    phase, pid = ("running", 77) if started else ("exited", 0)

    def inspect(*args, **kwargs):
        if args[:2] == ("ps", "-a") and args[-1] in ("id=" + r.CANDIDATE904, "id=" + r.WORKER904):
            return ""
        raw = prior(*args, **kwargs)
        if args[:2] != ("inspect", "--format") or args[-1] != r.LEGACY904:
            return raw
        fields = json.loads(raw)
        if args[2] == r.PINNED_RUNTIME_FORMAT:
            fields[2:] = [phase, pid, row["health"], 0, row["port_binding"] if started else {}]
        elif args[2] == r.PINNED_CONFIG_FORMAT:
            fields[2] = state["name"]
            fields[-2] = "no"
        else:
            fields[1:] = [phase, pid, r._PINS904["legacy_image_ref"], "no", 0]
        return json.dumps(fields)

    monkeypatch.setattr(r, "_docker", inspect)
    record = observe()
    assert (
        r.verify_runner(r._canonical(record) + b"\n", r.R904, None, source_sha=r.R904_SHA) == record
    )
    assert r.recovery_profile904(record) == ("OLD_STARTED" if started else "OLD_RENAMED")
