"""Protected sidecar provisioning and redacted current-binding evidence, offline."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from boca_socios import host_boca_pair_observe as pair
from boca_socios.host_on_demand_lifecycle import PanelStatus
from test_r294_current_retained import APPLY, RUN, SOURCE, current_pair, installation

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
WORKFLOW = "f" * 40
OPERATION = "a3b563c5-0a43-4d31-85d3-364467d684f7"


def module():
    name = "boca_socios.host_boca_installed_admin"
    assert importlib.util.find_spec(name) is not None, "missing protected installed admin helper"
    return importlib.import_module(name)


def document(*, source=SOURCE):
    item = installation()
    return {
        "version": 1,
        "source_sha": source,
        "observation_run_id": RUN,
        "installation_run_id": APPLY,
        "controller_id": item.controller_id,
        "worker_id": item.worker_id,
        "sender_id": None,
        "observed_at": NOW.isoformat(),
        "configured": "ABSENT",
        "paired": "NOT_PAIRED",
        "sender": "ABSENT",
        "human_receipt": "UNVERIFIED",
    }


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


@pytest.fixture
def host(monkeypatch):
    admin = module()
    events = []
    state = {"installed": installation(), "pair": current_pair(), "operation": None}

    @contextmanager
    def lease(run):
        assert run == RUN
        events.append("lease")
        yield object()

    monkeypatch.setattr(admin.cleanup, "protected_boca_job_lease", lease)
    monkeypatch.setattr(admin.service, "read_installed_binding", lambda _lease: state["installed"])
    monkeypatch.setattr(admin.pair, "observe", lambda _run: state["pair"])
    monkeypatch.setattr(admin, "read_panel_status", lambda _item: state["operation"])
    monkeypatch.setattr(admin, "_controller_boundary", lambda _item: events.append("boundary"))

    def execute(item, raw):
        assert item == state["installed"]
        events.append(("exec", json.loads(raw)))
        return admin._controller_receipt(raw)

    monkeypatch.setattr(admin, "_execute", execute)
    return admin, state, events


def test_current_admin_derives_installed_source_and_cids_separately_from_workflow(host):
    admin, _, events = host
    raw = admin.provision(WORKFLOW, RUN, "current", now=NOW)
    value = admin.verify(raw, WORKFLOW, RUN, "current")
    assert value["workflow_source_sha"] == WORKFLOW
    assert value["telegram"]["source_sha"] == SOURCE
    assert value["telegram"] == document()
    assert value["sector_schema"] == 2 and value["legacy_writes"] == 0
    assert events[0] == "lease" and sum(isinstance(x, tuple) for x in events) == 1


def test_automatic_post_apply_requires_this_exact_installation_before_exec(host):
    admin, _, events = host
    with pytest.raises(admin.AdminNoGo):
        admin.provision(WORKFLOW, RUN, RUN, now=NOW)
    assert not any(isinstance(x, tuple) for x in events)


@pytest.mark.parametrize("fault", ("cid", "binding", "worker_exit", "stop_absent", "stop_start"))
def test_wrong_binding_or_unproven_stopped_worker_cannot_write(host, fault):
    admin, state, events = host
    if fault in ("cid", "binding"):
        field = "controller_id" if fault == "cid" else "source_sha"
        state["installed"] = replace(
            state["installed"], **{field: "e" * (64 if fault == "cid" else 40)}
        )
    else:
        value = json.loads(current_pair(stopped=True).removeprefix(pair._PREFIX))
        if fault == "worker_exit":
            value["services"][1]["exit_code"] = 137
        if fault == "stop_start":
            state["operation"] = PanelStatus(
                OPERATION, "start", "APPLIED", "NONE", None, None, None
            )
        state["pair"] = pair._canonical(value)
    with pytest.raises((admin.AdminNoGo, ValueError)):
        admin.provision(WORKFLOW, RUN, "current", now=NOW)
    assert not any(isinstance(x, tuple) for x in events)


def test_actual_terminal_stop_is_accepted_without_relaxing_other_worker_states(host):
    admin, state, _ = host
    state["pair"] = current_pair(stopped=True)
    state["operation"] = PanelStatus(OPERATION, "stop", "APPLIED", "NONE", None, None, None)
    assert admin.verify(
        admin.provision(WORKFLOW, RUN, "current", now=NOW), WORKFLOW, RUN, "current"
    )


def test_volume_presence_is_not_an_invented_configuration_or_pairing_proof(host):
    admin, state, _ = host
    value = json.loads(state["pair"].removeprefix(pair._PREFIX))
    value["volumes"] = sorted([*value["volumes"], "boca-socios_boca_telegram"])
    state["pair"] = pair._canonical(value)
    value = admin.verify(
        admin.provision(WORKFLOW, RUN, "current", now=NOW), WORKFLOW, RUN, "current"
    )
    assert value["telegram"]["configured"] == value["telegram"]["paired"] == "UNVERIFIED"
    assert value["telegram"]["sender"] == "ABSENT"


def local_database(tmp_path):
    path = tmp_path / "boca.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE members(member_id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO members VALUES ('synthetic-member')")
        db.execute("PRAGMA user_version=7")
    path.chmod(0o600)
    return path


def test_explicit_local_provision_is_idempotent_and_never_changes_legacy(tmp_path):
    admin = module()
    path = local_database(tmp_path)
    before = path.read_bytes()
    raw = canonical(document())
    for _ in range(2):
        assert admin.provision_local(
            path, raw, expected_source_sha=SOURCE, now=NOW
        ) == admin._controller_receipt(raw)
        assert path.read_bytes() == before
    sidecar = path.with_name("boca_sector_preferences.sqlite3")
    with sqlite3.connect(f"file:{sidecar}?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM event_sector_preferences").fetchone() == (0,)
    receipt = path.with_name("boca_telegram_admin_status_v1.json")
    assert receipt.read_bytes() == raw and receipt.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("fault", ("symlink", "hardlink", "public", "extra", "source", "future"))
def test_unsafe_receipt_or_file_prevents_sector_migration(tmp_path, fault):
    admin = module()
    path = local_database(tmp_path)
    receipt = path.with_name("boca_telegram_admin_status_v1.json")
    value = document()
    if fault in ("symlink", "hardlink", "public"):
        target = tmp_path / "protected-target"
        target.write_bytes(b"do-not-replace")
        target.chmod(0o600)
        if fault == "symlink":
            receipt.symlink_to(target)
        elif fault == "hardlink":
            os.link(target, receipt)
        else:
            receipt.write_bytes(b"unsafe")
            receipt.chmod(0o644)
    elif fault == "extra":
        value["token"] = "PRIVATE_SENTINEL"
    elif fault == "source":
        value["source_sha"] = WORKFLOW
    else:
        value["observed_at"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises((admin.AdminNoGo, ValueError)):
        admin.provision_local(path, canonical(value), expected_source_sha=SOURCE, now=NOW)
    assert not path.with_name("boca_sector_preferences.sqlite3").exists()


def test_controller_cli_refuses_wrong_uid_or_source_without_raw_output(monkeypatch, capsys):
    admin = module()
    monkeypatch.setattr(admin.os, "getuid", lambda: 0)
    monkeypatch.setenv("BOCA_SOURCE_SHA", SOURCE)
    assert admin.main(["controller", canonical(document()).decode()]) == 3
    assert capsys.readouterr().out == admin.NO_GO.decode()
