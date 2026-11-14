"""Real temporary binding bytes and fake user manager; no Docker or providers."""

from dataclasses import replace

import pytest

from boca_socios import host_on_demand_service as service
from test_on_demand_service import ATTEMPT, SOCKET, UNIT, installation
from test_on_demand_service import host as _host_fixture

base_host = _host_fixture


@pytest.fixture
def host(base_host, monkeypatch):
    manager = service._systemctl
    monkeypatch.setattr(
        service,
        "_systemctl",
        lambda home, *args: "" if args[0] == "list-units" else manager(home, *args),
    )
    return base_host


def prepared(host):
    home, unit, manager, lease = host
    old = installation(home)
    service.prepare_control_directory(ATTEMPT, lease)
    service.install_control(old, lease)
    new = replace(
        old,
        pair=replace(
            old.pair,
            sender_id="1" * 64,
            sender_config_hash="2" * 64,
            sender_attempt_id=ATTEMPT,
            sender_running=True,
        ),
    )
    return old, new


def test_sender_binding_preserves_archive_and_pair_and_unit_links(host):
    old, new = prepared(host)
    home, unit, manager, lease = host
    root = home / service._ROOT
    archive = (root / service._ARCHIVE).stat()
    assert hasattr(service, "adopt_sender_binding")
    digest = service.adopt_sender_binding(old, new, lease, stopped=lambda: None)
    assert digest == service._sha((root / service._BINDING).read_bytes())
    assert service.read_installed_binding(lease) == new
    assert (root / service._ARCHIVE).stat() == archive
    assert (unit / UNIT).samefile(root / UNIT)
    assert (unit / SOCKET).samefile(root / SOCKET)
    assert manager.active


@pytest.mark.parametrize("field", ["source_sha", "controller_id", "worker_id"])
def test_sender_binding_rejects_non_sender_drift_before_effect(host, field):
    old, new = prepared(host)
    manager, lease = host[2:]
    before = list(manager.effects)
    new = replace(new, **{field: "3" * len(getattr(new, field))})
    assert hasattr(service, "adopt_sender_binding")
    with pytest.raises(service.ControlRefused):
        service.adopt_sender_binding(old, new, lease, stopped=lambda: None)
    assert manager.effects == before
    assert service.read_installed_binding(lease) == old


@pytest.mark.parametrize("stage", range(1, 8))
def test_each_publication_failure_compensates_exact_prestate(host, monkeypatch, stage):
    from boca_socios import host_on_demand_sender_update as update

    old, new = prepared(host)
    home, _, manager, lease = host
    original = update.os.replace
    calls = 0

    def fail_once(source, target):
        nonlocal calls
        calls += 1
        if calls == stage:
            raise OSError("injected publication failure")
        return original(source, target)

    monkeypatch.setattr(update.os, "replace", fail_once)
    if stage <= 5:
        with pytest.raises(service.ControlRefused, match="NO_GO"):
            service.adopt_sender_binding(old, new, lease, stopped=lambda: None)
        assert service.read_installed_binding(lease) == old
    else:
        service.adopt_sender_binding(old, new, lease, stopped=lambda: None)
        assert service.read_installed_binding(lease) == new
    assert manager.active
    assert not (home / service._ROOT / service._UPDATING).exists()


def test_interruption_fences_requests_and_recovery_never_resends(host, monkeypatch):
    from boca_socios import host_on_demand_sender_update as update

    old, new = prepared(host)
    lease = host[3]
    original = update.os.replace
    calls = 0

    def interrupt(source, target):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt()
        return original(source, target)

    monkeypatch.setattr(update.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        service.adopt_sender_binding(old, new, lease, stopped=lambda: None)
    with pytest.raises(service.ControlRefused):
        service.read_installed_binding(lease)
    assert update.pending(lease) == (old, new, ATTEMPT)
    monkeypatch.setattr(update.os, "replace", original)
    update.recover(lease, stopped=lambda: None, commit=True)
    assert service.read_installed_binding(lease) == new


def test_unknown_replacement_blocks_compensation_and_preserves_journal(host, monkeypatch):
    from boca_socios import host_on_demand_sender_update as update

    old, new = prepared(host)
    home, unit, _, lease = host
    original = update.os.replace

    def foreign(source, target):
        (unit / UNIT).unlink()
        service._new(unit / UNIT, b"foreign bytes")
        raise OSError("interference")

    monkeypatch.setattr(update.os, "replace", foreign)
    with pytest.raises(service.ControlRefused, match="INDETERMINATE"):
        service.adopt_sender_binding(old, new, lease, stopped=lambda: None)
    assert (unit / UNIT).read_bytes() == b"foreign bytes"
    assert (home / service._ROOT / service._UPDATING).exists()
    monkeypatch.setattr(update.os, "replace", original)
    with pytest.raises(service.ControlRefused):
        update.recover(lease, stopped=lambda: None, commit=False)


def test_v2_fixed_sender_and_acceptance_commands_have_no_private_identity():
    import inspect

    from boca_socios import host_first_deploy as deploy

    assert "v2_attempt" in inspect.signature(deploy._telegram_test_container).parameters
    args = deploy._telegram_test_container("image", "a" * 40, "", "", v2_attempt="622")
    assert args[args.index("--network") + 1] == "boca-socios_boca_telegram_egress"
    assert args[-6:] == (
        "python",
        "-m",
        "boca_socios.telegram_one_shot",
        "test-v2",
        "a" * 40,
        "622",
    )
    worker = deploy._telegram_worker_container("image", "a" * 40, "", "", "111", "622", v2=True)
    assert worker[worker.index("--network") + 1] == "boca-socios_boca_telegram_egress"
    assert worker[-6:] == (
        "python",
        "-m",
        "boca_socios.notify.telegram_worker",
        "serve-v2",
        "a" * 40,
        "622",
    )
    assert (
        "com.docker.compose.config-hash=" + deploy._telegram_sender_hash("a" * 40, "622") in worker
    )


def test_sender_callback_is_available_and_redacted():
    import importlib.util

    assert importlib.util.find_spec("boca_socios.host_telegram_sender") is not None
    from boca_socios.host_telegram_sender import SenderActivationReceipt

    receipt = SenderActivationReceipt("VERIFIED", "a" * 40, "b" * 64)
    assert set(receipt.__dataclass_fields__) == {"state", "source_sha", "sender_id"}


def sender_host(
    host,
    monkeypatch,
    *,
    acceptance="API_ACCEPTED",
    original_attempt=ATTEMPT,
    evidence_state="NOT_ATTEMPTED",
):
    from types import SimpleNamespace

    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios import host_first_deploy as deploy
    from boca_socios.host_telegram_installed_context import InstalledTelegramContext

    old, _ = prepared(host)
    lease = host[3]
    events = []
    evidence = {"state": evidence_state}
    states = {old.controller_id: False, old.worker_id: False}
    commands = {}
    test_id, sender_id = "4" * 64, "5" * 64

    class Reader:
        uid = gid = 10001

        def field(self, kind, ident, field):
            assert kind == "container"
            return False if field == "State.Restarting" else states[ident]

        def inventory(self):
            return SimpleNamespace(containers=[SimpleNamespace(ident=ident) for ident in states])

    reader = Reader()
    context = InstalledTelegramContext(ATTEMPT, lease, reader, old, "0" * 64, (), old.source_sha)
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda proof, attempt: None)

    def docker(*args):
        events.append(args)
        if args[0] == "create":
            ident = test_id if "boca_socios.telegram_one_shot" in args else sender_id
            assert ident not in states
            states[ident] = False
            commands[ident] = args
            return ident
        ident = args[-1]
        assert ident in states
        if args[:2] == ("start", "--attach"):
            evidence["state"] = acceptance if acceptance == "API_ACCEPTED" else "INDETERMINATE"
            return f"BOCA_TELEGRAM_TEST state={acceptance} source_sha={old.source_sha} synthetic=1 human_receipt=unverified"
        if args[0] == "start":
            states[ident] = True
        elif args[0] == "stop":
            states[ident] = False
        elif args[0] == "rm":
            assert states[ident] is False
            del states[ident]
        else:
            pytest.fail(str(args))
        return ident

    monkeypatch.setattr(cleanup, "_docker", docker)

    def test_attest(*args, **kwargs):
        assert commands[test_id][-3:] == ("test-v2", old.source_sha, original_attempt)
        assert states[test_id] is kwargs["running"]
        return test_id

    monkeypatch.setattr(deploy, "_telegram_test_finished", test_attest)

    def sender_attest(ident, *args, **kwargs):
        assert ident == sender_id
        assert commands[ident][-3:] == ("serve-v2", old.source_sha, original_attempt)
        assert states[ident] is kwargs["running"]
        return ATTEMPT

    monkeypatch.setattr(deploy, "_telegram_worker_inspect", sender_attest)
    monkeypatch.setattr(deploy, "_telegram_egress", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy, "_telegram_worker_ready", lambda *args: events.append(("READY",)))
    maintenance = SimpleNamespace(
        verify=lambda *args, **kwargs: SimpleNamespace(
            source_sha=old.source_sha, state="CUSTODY_COMMITTED_NO_SEND"
        )
    )
    from boca_socios import host_telegram_sender as sender

    monkeypatch.setattr(
        sender,
        "_sender_evidence",
        lambda *_args: sender.SenderAcceptanceEvidence(
            old.source_sha, original_attempt, evidence["state"]
        ),
    )
    return context, maintenance, events, states, sender_id


def test_complete_sender_adopts_real_binding_and_clears_stale_context(host, monkeypatch):
    from boca_socios.host_telegram_sender import activate_installed_sender

    context, maintenance, events, states, sender_id = sender_host(host, monkeypatch)
    receipt = activate_installed_sender(
        context,
        lease=host[3],
        maintenance=maintenance,
        expected_source_sha=context.installation.source_sha,
        attempt_id=ATTEMPT,
    )
    assert receipt.state == "VERIFIED" and receipt.sender_id == sender_id
    assert service.read_installed_binding(host[3]) == context.installation
    assert context.installation.pair.sender_id == sender_id
    assert context.installation.pair.sender_running
    assert context.pins is None and context.coordinates is None
    assert states == {
        context.installation.controller_id: False,
        context.installation.worker_id: False,
        sender_id: True,
    }
    assert events.index(("READY",)) < len(events)
    assert sum(event[:2] == ("start", "--attach") for event in events) == 1


def test_ambiguous_acceptance_never_starts_sender_or_retries(host, monkeypatch):
    from boca_socios.host_telegram_sender import SenderActivationError, activate_installed_sender

    context, maintenance, events, states, sender_id = sender_host(
        host, monkeypatch, acceptance="AMBIGUOUS"
    )
    old = context.installation
    with pytest.raises(SenderActivationError, match="INDETERMINATE"):
        activate_installed_sender(
            context,
            lease=host[3],
            maintenance=maintenance,
            expected_source_sha=old.source_sha,
            attempt_id=ATTEMPT,
        )
    assert sender_id not in states
    assert len(states) == 2
    assert sum(event[:2] == ("start", "--attach") for event in events) == 1
    assert service.read_installed_binding(host[3]) == old


@pytest.mark.parametrize("drift", ["source", "foreign", "prior_sender"])
def test_sender_preflight_drift_prevents_container_creation(host, monkeypatch, drift):
    from boca_socios.host_telegram_sender import SenderActivationError, activate_installed_sender

    context, maintenance, events, states, _ = sender_host(host, monkeypatch)
    source = context.installation.source_sha
    if drift == "source":
        source = "0" * 40
    elif drift == "foreign":
        states["6" * 64] = False
    else:
        context.installation = replace(
            context.installation,
            pair=replace(
                context.installation.pair,
                sender_id="6" * 64,
                sender_config_hash="7" * 64,
                sender_attempt_id="777",
                sender_running=False,
            ),
        )
    with pytest.raises(SenderActivationError):
        activate_installed_sender(
            context,
            lease=host[3],
            maintenance=maintenance,
            expected_source_sha=source,
            attempt_id=ATTEMPT,
        )
    assert events == []


def recovery_context(tmp_path, monkeypatch, *, bound_sender=False):
    from pathlib import Path

    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios import host_first_deploy as deploy
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
    from boca_socios.host_telegram_installed_context import InstalledTelegramContext
    from test_host_lifecycle_rootless_adapter import _binding
    from test_host_telegram_postcutover import _lease, _on_demand_fake, _pins

    monkeypatch.setattr(deploy, "_telegram_volume", lambda: None)
    pins, lease = _pins(stopped_sender=bound_sender), _lease()
    reader = _on_demand_fake(tmp_path, stopped_sender=bound_sender)
    for volume in reader.inventory_value.volumes:
        reader.fields[("volume", volume.name, "Mountpoint")] = (
            "/home/boca-deploy/.local/share/docker/volumes/" + volume.name + "/_data"
        )
    item = OnDemandInstallation(
        pins.browser_attempt,
        pins.source_sha,
        pins.controller_id,
        pins.controller_image,
        pins.worker_id,
        pins.worker_image,
        Path(
            "/home/boca-deploy/.local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3"
        ),
        _binding(sender_running=True) if bound_sender else _binding(),
    )
    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", lambda proof, attempt: None)
    return InstalledTelegramContext(
        pins.attempt_id, lease, reader, item, "d" * 64, (), pins.source_sha
    )


def test_recovery_boundary_before_pairing_uses_actual_stopped_profiles(tmp_path, monkeypatch):
    from boca_socios.host_telegram_sender import _recovery_boundary

    context = recovery_context(tmp_path, monkeypatch)
    _recovery_boundary(context)
    assert len(context.volumes) == 6


@pytest.mark.parametrize("drift", ["helper", "foreign_peer", "mount", "image", "running"])
def test_recovery_boundary_refuses_unknown_or_changed_objects(tmp_path, monkeypatch, drift):
    from boca_socios.host_telegram_sender import _recovery_boundary

    context = recovery_context(tmp_path, monkeypatch)
    reader, item = context.reader, context.installation
    if drift == "helper":
        reader.inventory_value = replace(
            reader.inventory_value,
            containers=reader.inventory_value.containers + (reader.inventory_value.containers[0],),
        )
    elif drift == "foreign_peer":
        nets = reader.inventory_value.networks
        reader.inventory_value = replace(
            reader.inventory_value, networks=(replace(nets[0], attached_ids=("0" * 64,)), *nets[1:])
        )
    elif drift == "mount":
        reader.fields[("container", item.controller_id, "Mounts")] = []
    elif drift == "image":
        reader.fields[("container", item.worker_id, "Config.Image")] = "foreign"
    else:
        reader.fields[("container", item.worker_id, "State.Running")] = True
    with pytest.raises((ValueError, RuntimeError)):
        _recovery_boundary(context)


def test_recovery_before_journal_restores_exact_controller_without_sender(tmp_path, monkeypatch):
    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios import host_telegram_production_reader as production
    from boca_socios import host_telegram_sender as sender

    context = recovery_context(tmp_path, monkeypatch)
    reader, item = context.reader, context.installation
    root = tmp_path / service._ROOT
    root.mkdir(mode=0o700)
    service._new(root / service._BINDING, b"fixture authenticated binding")
    monkeypatch.setattr(service, "_home", lambda: tmp_path)
    monkeypatch.setattr(service, "read_installed_binding", lambda lease: item)
    monkeypatch.setattr(production, "TelegramProductionDockerIO", lambda: reader)
    effects = []

    def docker(*args):
        effects.append(args)
        assert args == ("start", item.controller_id)
        reader.set_state(item.controller_id, True)
        reader.fields[("container", item.controller_id, "NetworkSettings.Ports")] = {
            "8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]
        }
        reader.inventory_value = replace(
            reader.inventory_value,
            networks=tuple(
                replace(n, attached_ids=(item.controller_id,))
                if n.name == "boca-socios_boca_private"
                else n
                for n in reader.inventory_value.networks
            ),
        )
        return item.controller_id

    monkeypatch.setattr(cleanup, "_docker", docker)
    from boca_socios import host_telegram_status

    monkeypatch.setattr(host_telegram_status, "publish_installed_status", lambda *_args: None)
    receipt = sender.recover_installed_sender(
        lease=context.lease,
        expected_source_sha=item.source_sha,
        workflow_sha=context.workflow_sha,
        attempt_id=context.attempt_id,
    )
    assert receipt.state == "RECOVERED"
    assert receipt.sender_state == "OFF"
    assert receipt.restoration == "CONTROLLER_HEALTHY_ENGINE_OFF"
    assert effects == [("start", item.controller_id)]


@pytest.mark.parametrize("field", ["command", "config_hash", "runtime_attempt"])
def test_v2_sender_attestor_rejects_binding_drift(monkeypatch, field):
    from boca_socios import host_first_deploy as deploy
    from test_host_browser_runtime_lifecycle import ATTEMPT as INSTALLED
    from test_host_browser_runtime_lifecycle import (
        IMAGE,
        RUNTIME_ATTEMPT,
        SENDER_ID,
        SOURCE,
        sender_image,
        sender_record,
    )

    record = sender_record()
    record["HostConfig"]["NetworkMode"] = deploy.TELEGRAM_V2_NETWORK
    record["NetworkSettings"]["Networks"] = {deploy.TELEGRAM_V2_NETWORK: {}}
    record["Config"]["Cmd"] = [
        "python",
        "-m",
        "boca_socios.notify.telegram_worker",
        "serve-v2",
        SOURCE,
        RUNTIME_ATTEMPT,
    ]
    record["Config"]["Labels"]["com.docker.compose.config-hash"] = deploy._telegram_sender_hash(
        SOURCE, RUNTIME_ATTEMPT
    )
    monkeypatch.setattr(deploy, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(deploy, "_run", lambda *args, **kwargs: sender_image())
    assert (
        deploy._telegram_worker_inspect(
            SENDER_ID,
            IMAGE,
            SOURCE,
            "",
            "",
            INSTALLED,
            running=True,
            runtime_attempt=RUNTIME_ATTEMPT,
            v2=True,
        )
        == RUNTIME_ATTEMPT
    )
    if field == "command":
        record["Config"]["Cmd"][-1] = "999"
    elif field == "config_hash":
        record["Config"]["Labels"]["com.docker.compose.config-hash"] = "0" * 64
    else:
        record["Config"]["Labels"][deploy.TELEGRAM_ATTEMPT_LABEL] = "999"
    with pytest.raises(deploy.PreflightError):
        deploy._telegram_worker_inspect(
            SENDER_ID,
            IMAGE,
            SOURCE,
            "",
            "",
            INSTALLED,
            running=True,
            runtime_attempt=RUNTIME_ATTEMPT,
            v2=True,
        )


def test_busy_control_service_blocks_before_publication(host, monkeypatch):
    old, new = prepared(host)
    manager, lease = host[2:]
    original = service._systemctl

    def busy(home, *args):
        if args[0] == "list-units":
            return "boca-bot-control@busy.service loaded active running\n"
        return original(home, *args)

    monkeypatch.setattr(service, "_systemctl", busy)
    before = list(manager.effects)
    with pytest.raises(service.ControlRefused):
        service.adopt_sender_binding(old, new, lease, stopped=lambda: None)
    assert manager.effects == before
    assert service.read_installed_binding(lease) == old


@pytest.mark.parametrize("failure", ["stop", "daemon-reload", "start"])
def test_manager_transition_failures_restore_old_binding(host, monkeypatch, failure):
    old, new = prepared(host)
    original = service._systemctl
    fired = False

    def fail_once(home, *args):
        nonlocal fired
        if args[0] == failure and not fired:
            fired = True
            raise OSError("injected manager failure")
        return original(home, *args)

    monkeypatch.setattr(service, "_systemctl", fail_once)
    with pytest.raises(service.ControlRefused, match="NO_GO"):
        service.adopt_sender_binding(old, new, host[3], stopped=lambda: None)
    assert fired
    assert service.read_installed_binding(host[3]) == old


def test_remove_control_cannot_discard_sender_recovery_journal(host):
    from boca_socios import host_on_demand_sender_update as update

    old, new = prepared(host)
    home, _, manager, lease = host
    root = home / service._ROOT
    archive = service._sha((root / service._ARCHIVE).read_bytes())
    service._new(
        root / service._UPDATING,
        update._journal(
            service._plan(home, old, archive), service._plan(home, new, archive), ATTEMPT
        ),
    )
    before = list(manager.effects)
    with pytest.raises(service.ControlRefused):
        service.remove_control(ATTEMPT, lease)
    assert manager.effects == before
    assert update.pending(lease) == (old, new, ATTEMPT)


def test_adoption_requires_sender_from_current_lease(host):
    old, new = prepared(host)
    new = replace(new, pair=replace(new.pair, sender_attempt_id="999"))
    before = list(host[2].effects)
    with pytest.raises(service.ControlRefused):
        service.adopt_sender_binding(old, new, host[3], stopped=lambda: None)
    assert host[2].effects == before


def test_completion_api_is_explicit_and_available():
    from boca_socios import host_telegram_sender as sender

    assert hasattr(sender, "complete_installed_telegram_sender")


def test_explicit_adoption_can_retain_original_acceptance_attempt(host):
    old, new = prepared(host)
    new = replace(new, pair=replace(new.pair, sender_attempt_id="111"))
    service.adopt_sender_binding(
        old, new, host[3], stopped=lambda: None, original_sender_attempt="111"
    )
    assert service.read_installed_binding(host[3]) == new


@pytest.mark.parametrize("acceptance_state,send_count", [("NOT_ATTEMPTED", 1), ("API_ACCEPTED", 0)])
def test_complete_retains_original_attempt_and_never_replays_accepted_send(
    host, monkeypatch, acceptance_state, send_count
):
    from boca_socios import host_telegram_maintenance as maintenance_module
    from boca_socios import host_telegram_sender as sender
    from boca_socios import host_telegram_status as status

    context, maintenance, events, states, sender_id = sender_host(
        host, monkeypatch, original_attempt="111", evidence_state=acceptance_state
    )
    monkeypatch.setattr(sender, "_completion_context", lambda *_args: context)
    monkeypatch.setattr(sender, "_recovery_boundary", lambda context: sender._stopped(context))
    monkeypatch.setattr(maintenance_module, "InstalledMaintenance", lambda _: maintenance)

    def restore():
        states[context.installation.controller_id] = True
        events.append(("RESTORE",))

    context.restore = restore
    monkeypatch.setattr(
        status, "publish_installed_status", lambda *_args: events.append(("PUBLISH",))
    )
    receipt = sender.complete_installed_telegram_sender(
        lease=host[3],
        expected_source_sha=context.installation.source_sha,
        workflow_sha=context.workflow_sha,
        attempt_id=ATTEMPT,
    )
    assert receipt.state == "READY" and receipt.sender_state == "VERIFIED"
    assert context.installation.pair.sender_attempt_id == "111"
    assert context.installation.pair.sender_id == sender_id
    assert service.read_installed_binding(host[3]) == context.installation
    assert sum(event[:2] == ("start", "--attach") for event in events) == send_count
    assert events[-2:] == [("RESTORE",), ("PUBLISH",)]


def test_complete_refuses_ambiguous_acceptance_without_retry(host, monkeypatch):
    from boca_socios import host_telegram_maintenance as maintenance_module
    from boca_socios import host_telegram_sender as sender

    context, maintenance, events, states, sender_id = sender_host(
        host, monkeypatch, original_attempt="111", evidence_state="INDETERMINATE"
    )
    monkeypatch.setattr(sender, "_completion_context", lambda *_args: context)
    monkeypatch.setattr(maintenance_module, "InstalledMaintenance", lambda _: maintenance)
    context.restore = lambda: events.append(("RESTORE",))
    with pytest.raises(sender.SenderActivationError, match="INDETERMINATE"):
        sender.complete_installed_telegram_sender(
            lease=host[3],
            expected_source_sha=context.installation.source_sha,
            workflow_sha=context.workflow_sha,
            attempt_id=ATTEMPT,
        )
    assert events == [("RESTORE",)]
    assert sender_id not in states


def test_initial_callback_cannot_create_new_acceptance_identity_for_old_custody(host, monkeypatch):
    from boca_socios import host_telegram_sender as sender

    context, maintenance, events, _, _ = sender_host(host, monkeypatch, original_attempt="111")
    with pytest.raises(sender.SenderActivationError, match="completion_required"):
        sender.activate_installed_sender(
            context,
            lease=host[3],
            maintenance=maintenance,
            expected_source_sha=context.installation.source_sha,
            attempt_id=ATTEMPT,
        )
    assert events == []


def test_host_evidence_adapter_reads_real_committed_stage_and_original_nonce(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from boca_socios import host_telegram_sender as sender
    from boca_socios import telegram_maintenance
    from test_r296_telegram_sender_evidence import _committed

    context, api, _, _, _ = _committed(tmp_path, monkeypatch)
    maintenance = SimpleNamespace(call=telegram_maintenance.execute)
    evidence = sender._sender_evidence(context, maintenance)
    assert evidence == sender.SenderAcceptanceEvidence(
        context.installation.source_sha, context.attempt_id, "NOT_ATTEMPTED"
    )
    assert len(api.calls) == 4


@pytest.mark.parametrize("damage", ["source", "attempt", "state", "extra"])
def test_host_evidence_adapter_refuses_noncanonical_receipt(host, monkeypatch, damage):
    from types import SimpleNamespace

    from boca_socios import host_telegram_owner_stage
    from boca_socios import host_telegram_sender as sender
    from boca_socios.telegram_pairing_cutover import CutoverCoordinates

    real_evidence = sender._sender_evidence
    context, _, events, _, _ = sender_host(host, monkeypatch)
    context.coordinates = CutoverCoordinates(
        context.attempt_id,
        context.installation.source_sha,
        context.installation.controller_image,
        "1" * 64,
        "2" * 64,
        context.installation.controller_id,
        "3" * 64,
    )
    monkeypatch.setattr(
        host_telegram_owner_stage, "_controller_owner_subject", lambda *_args: "owner"
    )
    value = {
        "source_sha": context.installation.source_sha,
        "original_attempt_id": "111",
        "acceptance_state": "NOT_ATTEMPTED",
    }
    if damage == "source":
        value["source_sha"] = "0" * 40
    elif damage == "attempt":
        value["original_attempt_id"] = "new-run"
    elif damage == "state":
        value["acceptance_state"] = "READY"
    else:
        value["private"] = "forbidden"
    with pytest.raises(sender.SenderActivationError, match="evidence_unverified"):
        real_evidence(context, SimpleNamespace(call=lambda *_args: value))
    assert events == []


def test_completion_publication_failure_never_claims_ready(host, monkeypatch):
    from boca_socios import host_telegram_maintenance as maintenance_module
    from boca_socios import host_telegram_sender as sender
    from boca_socios import host_telegram_status as status

    context, maintenance, events, _, _ = sender_host(
        host, monkeypatch, original_attempt="111", evidence_state="API_ACCEPTED"
    )
    monkeypatch.setattr(sender, "_completion_context", lambda *_args: context)
    monkeypatch.setattr(sender, "_recovery_boundary", lambda context: sender._stopped(context))
    monkeypatch.setattr(maintenance_module, "InstalledMaintenance", lambda _: maintenance)
    context.restore = lambda: events.append(("RESTORE",))

    def fail(*_args):
        raise ValueError("fixed publication failure")

    monkeypatch.setattr(status, "publish_installed_status", fail)
    with pytest.raises(sender.SenderActivationError, match="publish_INDETERMINATE"):
        sender.complete_installed_telegram_sender(
            lease=host[3],
            expected_source_sha=context.installation.source_sha,
            workflow_sha=context.workflow_sha,
            attempt_id=ATTEMPT,
        )
    assert not any(event[:2] == ("start", "--attach") for event in events)
    assert ("RESTORE",) in events


def test_lost_create_ack_requires_phase_rca_without_foreign_deletion(host, monkeypatch):
    from boca_socios import host_telegram_production_reader as production
    from boca_socios import host_telegram_sender as sender

    context, _, events, states, _ = sender_host(host, monkeypatch)
    states["8" * 64] = False
    monkeypatch.setattr(production, "TelegramProductionDockerIO", lambda: context.reader)
    with pytest.raises(sender.SenderActivationError, match="unbound_container_RCA_REQUIRED"):
        sender._completion_context(
            context.lease, context.installation.source_sha, context.workflow_sha, context.attempt_id
        )
    assert events == [] and "8" * 64 in states


def test_interrupted_completion_journal_retains_original_acceptance_attempt(host, monkeypatch):
    from boca_socios import host_on_demand_sender_update as update

    old, new = prepared(host)
    new = replace(new, pair=replace(new.pair, sender_attempt_id="111"))
    original = update.os.replace
    count = 0

    def interrupt(source, target):
        nonlocal count
        count += 1
        if count == 3:
            raise KeyboardInterrupt()
        return original(source, target)

    monkeypatch.setattr(update.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        service.adopt_sender_binding(
            old, new, host[3], stopped=lambda: None, original_sender_attempt="111"
        )
    assert update.pending(host[3]) == (old, new, "111")
    monkeypatch.setattr(update.os, "replace", original)
    update.recover(host[3], stopped=lambda: None, commit=True)
    assert service.read_installed_binding(host[3]) == new


def test_healthy_completion_context_attests_real_maintenance_mount_sources(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios import host_telegram_maintenance as maintenance
    from boca_socios import host_telegram_production_reader as production
    from boca_socios import host_telegram_sender as sender
    from boca_socios.telegram_maintenance_contract import MOUNTS

    previous = recovery_context(tmp_path, monkeypatch)
    reader, item = previous.reader, previous.installation
    reader.set_state(item.controller_id, True)
    reader.fields[("container", item.controller_id, "NetworkSettings.Ports")] = {
        "8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]
    }
    reader.inventory_value = replace(
        reader.inventory_value,
        networks=tuple(
            replace(network, attached_ids=(item.controller_id,))
            if network.name == "boca-socios_boca_private"
            else network
            for network in reader.inventory_value.networks
        ),
    )
    root = tmp_path / service._ROOT
    root.mkdir(mode=0o700)
    service._new(root / service._BINDING, b"fixture authenticated binding")
    monkeypatch.setattr(service, "_home", lambda: tmp_path)
    monkeypatch.setattr(service, "read_installed_binding", lambda _: item)
    monkeypatch.setattr(production, "TelegramProductionDockerIO", lambda: reader)
    context = sender._completion_context(
        previous.lease, item.source_sha, previous.workflow_sha, previous.attempt_id
    )
    # Exercise the actual maintenance call and attestor, not a stub of either.
    cid = "7" * 64
    calls = []
    record = {}

    def docker(*args):
        calls.append(args[0])
        if args[0] == "create":
            name = args[args.index("--name") + 1]
            record.update(
                {
                    "Id": cid,
                    "Name": "/" + name,
                    "Config": {
                        "Image": item.controller_image,
                        "User": "10001:10001",
                        "Cmd": [
                            "python",
                            "-m",
                            "boca_socios.telegram_maintenance",
                            "sender-evidence",
                        ],
                        "Labels": {"com.docker.compose.project": "boca-socios"},
                    },
                    "HostConfig": {
                        "NetworkMode": "none",
                        "ReadonlyRootfs": True,
                        "Privileged": False,
                        "LogConfig": {"Type": "none"},
                        "CapDrop": ["ALL"],
                        "CapAdd": None,
                        "PidsLimit": 16,
                        "Memory": 67108864,
                        "NanoCpus": 250000000,
                        "PublishAllPorts": False,
                        "PortBindings": {},
                        "RestartPolicy": {"Name": "no"},
                        "SecurityOpt": ["no-new-privileges"],
                    },
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Name": "boca-socios_" + name,
                            "Source": reader.field("volume", "boca-socios_" + name, "Mountpoint"),
                            "Destination": target,
                            "RW": rw,
                            "Driver": "local",
                        }
                        for name, target, rw in MOUNTS["sender-evidence"]
                    ],
                    "NetworkSettings": {"Networks": {"none": {}}},
                    "State": {"Restarting": False, "Running": False, "ExitCode": 0},
                }
            )
            return cid
        if args[0] == "inspect":
            return json.dumps(record)
        assert args == ("rm", cid)
        return cid

    monkeypatch.setattr(cleanup, "_docker", docker)

    def child(argv, **kwargs):
        calls.append("private-child")
        assert argv[-1] == cid
        return SimpleNamespace(returncode=0, stderr=b"", stdout=b'{"checked":true}')

    monkeypatch.setattr(maintenance.subprocess, "run", child)
    assert maintenance.InstalledMaintenance(context).call("sender-evidence", {}) == {
        "checked": True
    }
    assert set(dict(context.volumes)) == {
        "boca-socios_boca_data",
        "boca-socios_boca_owner",
        "boca-socios_boca_telegram",
    }
    assert calls.count("private-child") == 1 and calls[-1] == "rm"


@pytest.mark.parametrize("mode", ["publish", "pending", "custody_changed"])
def test_already_healthy_bound_recovery_republishes_without_controller_action(
    tmp_path, monkeypatch, mode
):
    import hashlib
    import json

    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios import host_first_deploy as deploy
    from boca_socios import host_telegram_production_reader as production
    from boca_socios import host_telegram_sender as sender
    from boca_socios.host_telegram_maintenance import InstalledMaintenance
    from boca_socios.telegram_bootstrap import _canonical
    from boca_socios.telegram_pairing_install import PairingCustodyReceipt
    from test_host_browser_runtime_lifecycle import sender_record

    network_name = "boca-socios_boca_telegram_egress"
    previous = recovery_context(tmp_path, monkeypatch, bound_sender=True)
    reader, item = previous.reader, previous.installation
    config_hash = deploy._telegram_sender_hash(item.source_sha, item.pair.sender_attempt_id)
    item = replace(item, pair=replace(item.pair, sender_config_hash=config_hash))
    reader.set_state(item.controller_id, True)
    reader.set_state(item.pair.sender_id, True)
    reader.fields[("container", item.controller_id, "NetworkSettings.Ports")] = {
        "8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]
    }
    reader.inventory_value = replace(
        reader.inventory_value,
        containers=tuple(
            replace(
                c,
                labels=tuple(
                    (key, config_hash if key == "com.docker.compose.config-hash" else value)
                    for key, value in c.labels
                ),
                networks=(network_name,),
            )
            if c.ident == item.pair.sender_id
            else c
            for c in reader.inventory_value.containers
        ),
        networks=tuple(
            replace(n, attached_ids=(item.controller_id,))
            if n.name == "boca-socios_boca_private"
            else replace(n, attached_ids=(item.pair.sender_id,))
            if n.name == network_name
            else n
            for n in reader.inventory_value.networks
        ),
    )
    root = tmp_path / service._ROOT
    root.mkdir(mode=0o700)
    service._new(root / service._BINDING, b"fixture authenticated binding")
    monkeypatch.setattr(service, "_home", lambda: tmp_path)
    monkeypatch.setattr(service, "read_installed_binding", lambda _: item)
    monkeypatch.setattr(production, "TelegramProductionDockerIO", lambda: reader)
    record = sender_record()
    image_id = next(
        c.image_id for c in reader.inventory_value.containers if c.ident == item.pair.sender_id
    )
    record.update(Id=item.pair.sender_id, Image=image_id)
    record["Config"].update(
        Image=item.controller_image,
        Cmd=[
            "python",
            "-m",
            "boca_socios.notify.telegram_worker",
            "serve-v2",
            item.source_sha,
            item.pair.sender_attempt_id,
        ],
    )
    record["HostConfig"]["NetworkMode"] = network_name
    record["NetworkSettings"]["Networks"] = {network_name: {}}
    record["Config"]["Labels"].update(
        {
            deploy.BROWSER_ATTEMPT_LABEL: item.installation_run_id,
            deploy.TELEGRAM_ATTEMPT_LABEL: item.pair.sender_attempt_id,
            "com.docker.compose.config-hash": config_hash,
            "org.opencontainers.image.revision": item.source_sha,
        }
    )
    monkeypatch.setattr(deploy, "_browser_inspect_record", lambda _: record)
    events = []

    def docker_read(*args, **kwargs):
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps(
                {
                    "Id": image_id,
                    "RepoDigests": [item.controller_image],
                    "Config": {
                        "Env": ["PATH=/usr/local/bin:/usr/bin"],
                        "Labels": {"org.opencontainers.image.revision": item.source_sha},
                    },
                }
            )
        if args[:3] == ("docker", "network", "inspect"):
            return json.dumps(
                {
                    "Name": network_name,
                    "Driver": "bridge",
                    "Scope": "local",
                    "Internal": False,
                    "Attachable": False,
                    "Ingress": False,
                    "Containers": {item.pair.sender_id: {}},
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.network": "telegram_egress",
                    },
                }
            )
        assert args[:2] == ("docker", "logs")
        events.append("READY")
        return f"BOCA_TELEGRAM_READY state=VERIFIED source_sha={item.source_sha} api_accepted=1 identity=pinned"

    monkeypatch.setattr(deploy, "_run", docker_read)
    monkeypatch.setattr(
        cleanup, "_docker", lambda *_args: pytest.fail("unexpected controller/Docker mutation")
    )

    def verify(storage, *_args, **_kwargs):
        events.append("V2")
        return PairingCustodyReceipt(
            "0" * 40 if mode == "custody_changed" else item.source_sha, "f" * 64, 12345
        )

    monkeypatch.setattr(InstalledMaintenance, "verify", verify)

    def call(storage, operation, request):
        assert operation == "publish-status"
        assert len(storage.context.volumes) == 3
        events.append("PUBLISH")
        raw = (
            _canonical(
                {
                    "version": 1,
                    **request,
                    "configured": "VERIFIED",
                    "paired": "VERIFIED",
                    "human_receipt": "UNVERIFIED",
                }
            )
            + b"\n"
        )
        return {
            "state": "STATUS_PUBLISHED",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "configured": "VERIFIED",
            "paired": "VERIFIED",
        }

    monkeypatch.setattr(InstalledMaintenance, "call", call)
    from boca_socios.host_telegram_installed_context import (
        TelegramContextError,
        resolve_installed_context,
    )

    with pytest.raises(TelegramContextError):
        resolve_installed_context(
            previous.attempt_id,
            lease=previous.lease,
            reader=reader,
            expected_source_sha=item.source_sha,
            workflow_sha=previous.workflow_sha,
        )
    if mode == "pending":
        from boca_socios import host_on_demand_sender_update as update

        service._new(root / service._UPDATING, b"fixture journal")
        monkeypatch.setattr(update, "pending", lambda _: (item, item, item.pair.sender_attempt_id))
    if mode != "publish":
        with pytest.raises(sender.SenderActivationError, match="INDETERMINATE"):
            sender.recover_installed_sender(
                lease=previous.lease,
                expected_source_sha=item.source_sha,
                workflow_sha=previous.workflow_sha,
                attempt_id=previous.attempt_id,
            )
        assert events == ([] if mode == "pending" else ["READY", "V2"])
        assert reader.effects == []
        return
    receipt = sender.recover_installed_sender(
        lease=previous.lease,
        expected_source_sha=item.source_sha,
        workflow_sha=previous.workflow_sha,
        attempt_id=previous.attempt_id,
    )
    assert receipt.state == "RECOVERED" and receipt.sender_state == "VERIFIED"
    assert events == ["READY", "V2", "PUBLISH"]
    assert reader.effects == []


def test_v2_acceptance_attestor_matches_canonical_network_and_refuses_legacy(monkeypatch):
    import json

    from boca_socios import host_first_deploy as deploy
    from test_host_browser_runtime_lifecycle import (
        IMAGE,
        SENDER_ID,
        SOURCE,
        sender_image,
        sender_record,
    )

    record = sender_record(running=False)
    controller = "9" * 64
    record["Name"] = "/" + deploy.TELEGRAM_TEST_NAME
    record["Config"]["Cmd"] = [
        "python",
        "-m",
        "boca_socios.telegram_one_shot",
        "test-v2",
        SOURCE,
        "777",
    ]
    record["Config"]["Labels"]["com.docker.compose.service"] = "telegram-test"
    record["Config"]["Env"].remove("BOCA_DB_PATH=/data/boca.sqlite3")
    record["Config"]["Healthcheck"] = {
        "Test": ["NONE"],
        "Interval": 30000000000,
        "Timeout": 5000000000,
        "StartPeriod": 15000000000,
        "Retries": 3,
    }
    record["State"].update(ExitCode=0, Status="created")
    record["HostConfig"]["NetworkMode"] = deploy.TELEGRAM_V2_NETWORK
    record["HostConfig"]["SecurityOpt"] = ["no-new-privileges"]
    record["NetworkSettings"]["Networks"] = {deploy.TELEGRAM_V2_NETWORK: {}}

    def read(*args):
        if args[:3] == ("docker", "ps", "-a"):
            return controller + "\n" + SENDER_ID
        if args[:2] == ("docker", "inspect"):
            return json.dumps(
                record if args[-1] == SENDER_ID else {"Id": controller, "Name": "/controller"}
            )
        assert args[:3] == ("docker", "image", "inspect")
        return sender_image()

    monkeypatch.setattr(deploy, "_run", read)
    assert (
        deploy._telegram_test_finished(
            IMAGE, SOURCE, "", "", controller, v2_attempt="777", created_id=SENDER_ID
        )
        == SENDER_ID
    )
    record["HostConfig"]["NetworkMode"] = deploy.TELEGRAM_NETWORK
    with pytest.raises(deploy.PreflightError):
        deploy._telegram_test_finished(
            IMAGE, SOURCE, "", "", controller, v2_attempt="777", created_id=SENDER_ID
        )
