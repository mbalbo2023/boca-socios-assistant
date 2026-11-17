"""Offline direct custody: no legacy filenames, no usable partial install."""

import importlib
import json
import os
import time
from importlib.util import find_spec

import pytest

from boca_socios import telegram_bootstrap as boot

MODULE = "boca_socios.telegram_direct_custody"
STAGE = "boca_telegram_direct_stage_v1.json"
MARK = "telegram_direct_commit_v1"
TOKEN = "123456:offline_fake_only"  # noqa: S105
CHAT = "325471"
SOURCE = "c" * 40
BASE = {"source_sha": SOURCE, "lease_binding": "a" * 64}


def _helper():
    assert find_spec(MODULE) is not None, "direct custody helper is missing"
    return importlib.import_module(MODULE)


@pytest.fixture
def dirs(tmp_path):
    data, final = tmp_path / "data", tmp_path / "custody"
    data.mkdir(mode=0o700)
    final.mkdir(mode=0o700)
    value = {
        "version": 1,
        "purpose": "boca-telegram-direct-owner-stage-v1",
        "repository": boot.REPOSITORY,
        "uid": 10001,
        "stage_id": "b" * 64,
        "staged_at": int(time.time()),
        "source_sha": SOURCE,
        "bot_token": TOKEN,
        "chat_id": CHAT,
    }
    (data / STAGE).write_bytes(boot._canonical(value))
    (data / STAGE).chmod(0o600)
    return data, final


def call(op, dirs, req):
    return _helper().execute_direct(op, *dirs, req, uid=os.getuid())


def test_same_installed_source_can_consume_two_day_old_owner_stage(dirs):
    path = dirs[0] / STAGE
    stage = json.loads(path.read_bytes())
    stage["staged_at"] = int(time.time()) - 2 * 86400
    path.write_bytes(boot._canonical(stage))
    req = {**BASE, **call("inspect-direct", dirs, BASE)}
    call("install-direct", dirs, req)
    assert call("verify-direct", dirs, req) == {
        "state": "INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING"
    }


@pytest.mark.parametrize("invalid", [0, -1, True, "123", 1.5, 2**63])
def test_invalid_or_future_timestamp_rejected_before_preflight_witness(dirs, invalid):
    path = dirs[0] / STAGE
    stage = json.loads(path.read_bytes())
    stage["staged_at"] = invalid
    path.write_bytes(boot._canonical(stage))
    with pytest.raises(ValueError):
        call("inspect-direct", dirs, BASE)
    assert not list(dirs[1].iterdir())


@pytest.mark.parametrize("key", [False, True])
def test_direct_install_is_redacted_and_never_legacy_activatable(dirs, key):
    data, final = dirs
    if key:
        boot.prepare(final, uid=os.getuid())
    req = {**BASE, **call("inspect-direct", dirs, BASE)}
    first = call("install-direct", dirs, req)
    assert first == {"state": "WRITTEN_SENDER_OFF"}
    result = call("verify-direct", dirs, req)
    assert result == {"state": "INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING"}
    assert (data / STAGE).exists()
    for name, value in (("direct_bot_token", TOKEN), ("direct_chat_id", CHAT)):
        assert (final / name).read_text() == value
        assert (final / name).stat().st_mode & 0o777 == 0o400
    assert all(item not in repr(req) + repr(result) for item in [TOKEN, CHAT])
    with pytest.raises(boot.BootstrapError):
        boot.verify(final, uid=os.getuid())
    with pytest.raises(ValueError):
        call("install-direct", dirs, req)
    (final / "direct_chat_id").chmod(0o600)
    (final / "direct_chat_id").write_text("325472")
    (final / "direct_chat_id").chmod(0o400)
    with pytest.raises(ValueError):
        call("verify-direct", dirs, req)


@pytest.mark.parametrize("after", ["direct_bot_token", "direct_chat_id", MARK])
def test_interruption_is_not_an_ack_and_never_reinstalls(dirs, monkeypatch, after):
    boot.prepare(dirs[1], uid=os.getuid())
    req = {**BASE, **call("inspect-direct", dirs, BASE)}
    original = boot._write_new

    def crash(fd, name, value, uid):
        original(fd, name, value, uid)
        if name == after:
            raise OSError("injected loss of acknowledgement")

    monkeypatch.setattr(boot, "_write_new", crash)
    if after == MARK:
        # Simulate loss of the ACK after the completed marker publication.
        publisher = _helper()._publish_marker

        def lost_ack(fd, content, uid):
            publisher(fd, content, uid)
            raise OSError("lost completed publish ACK")

        monkeypatch.setattr(_helper(), "_publish_marker", lost_ack)
    with pytest.raises(ValueError):
        call("install-direct", dirs, req)
    with pytest.raises(ValueError):
        call("install-direct", dirs, req)
    with pytest.raises(ValueError):
        boot.verify(dirs[1], uid=os.getuid())
    if after != MARK:
        with pytest.raises(ValueError):
            call("verify-direct", dirs, req)
    else:
        assert call("verify-direct", dirs, req)["state"].endswith("STAGE_CLEANUP_PENDING")


@pytest.mark.parametrize("crash_at", ["pre_link", "post_link", "preexisting_marker"])
def test_final_marker_never_visible_partially_written_and_preserves_orphan(
    dirs, monkeypatch, crash_at
):
    final = dirs[1]
    req = {**BASE, **call("inspect-direct", dirs, BASE)}
    original_link = os.link

    def interrupted(src, dst, **kwargs):
        assert dst == MARK
        assert not (final / MARK).exists()
        before = (final / src).stat()
        assert before.st_mode & 0o777 == 0o400 and before.st_nlink == 1
        assert json.loads((final / src).read_bytes())["stage_id"] == "b" * 64
        if crash_at == "pre_link":
            raise OSError("interrupted before publication")
        if crash_at == "preexisting_marker":
            (final / MARK).write_bytes(b"untouched")
        original_link(src, dst, **kwargs)
        raise OSError("interrupted after publication")

    monkeypatch.setattr(os, "link", interrupted)
    with pytest.raises(ValueError):
        call("install-direct", dirs, req)
    assert any(p.name.startswith(".") for p in final.iterdir())
    if crash_at == "post_link":
        assert (final / MARK).stat().st_nlink == 2
        assert json.loads((final / MARK).read_bytes())["stage_id"] == "b" * 64
    elif crash_at == "preexisting_marker":
        assert (final / MARK).read_bytes() == b"untouched"
    else:
        assert not (final / MARK).exists()
    with pytest.raises(ValueError):
        call("verify-direct", dirs, req)
    with pytest.raises(ValueError):
        call("install-direct", dirs, req)


@pytest.mark.parametrize(
    "bad",
    [
        "uid",
        "stale",
        "source",
        "symlink",
        "hardlink",
        "mode",
        "previous",
        "v2stage",
        "lease",
        "swap",
        "bool",
        "chat",
        "duplicate",
        "key",
        "orphan",
    ],
)
def test_untrusted_staging_cannot_create_any_custody(dirs, bad):
    data, final = dirs
    path = data / STAGE
    req = {**BASE, **call("inspect-direct", dirs, BASE)}
    value = json.loads(path.read_bytes())
    if bad in {"stale", "uid", "source", "bool", "chat"}:
        field, v = {
            "stale": ("staged_at", 0),
            "uid": ("uid", 0),
            "source": ("source_sha", "e" * 40),
            "bool": ("version", True),
            "chat": ("chat_id", "-1"),
        }[bad]
        value[field] = v
        path.write_bytes(boot._canonical(value))
    elif bad == "symlink":
        path.rename(data / "moved")
        path.symlink_to(data / "moved")
    elif bad == "hardlink":
        os.link(path, data / "linked")
    elif bad == "swap":
        path.rename(data / "moved")
        path.write_bytes((data / "moved").read_bytes())
        path.chmod(0o600)
    elif bad == "mode":
        path.chmod(0o644)
    elif bad == "previous":
        (final / "bot_token").touch()
    elif bad == "v2stage":
        (data / "boca_telegram_pairing_stage_v2.json").touch()
    elif bad == "lease":
        req["lease_binding"] = "e" * 64
    elif bad == "duplicate":
        path.write_bytes(b'{"version":1,' + path.read_bytes()[1:])
    elif bad == "orphan":
        (data / ("." + STAGE + "." + "a" * 32 + ".tmp")).touch()
    else:
        (final / boot.PRIVATE_KEY).write_bytes(b"invalid")
    with pytest.raises(ValueError):
        call("install-direct", dirs, req)
    assert not (final / "direct_bot_token").exists()


def test_networkless_image_contract_and_bound_workflow_receipt():
    from boca_socios.host_first_deploy import _telegram_container
    from boca_socios.host_telegram_backend import TelegramBackendReceipt, verify_backend_receipt
    from boca_socios.host_telegram_cli import OPERATIONS

    assert OPERATIONS.get("telegram-install-direct") == "install-direct"
    for op in ("inspect-direct", "install-direct", "verify-direct"):
        argv = _telegram_container(
            "img",
            "telegram_maintenance",
            op,
            writable=False,
            maintenance_name="boca-socios-telegram-maint-42-" + "b" * 16,
        )
        assert argv[argv.index("--user") + 1] == "10001:10001"
        assert argv[argv.index("--network") + 1] == "none"
        assert argv[argv.index("--log-driver") + 1] == "none"
        assert "--env" not in argv and "--env-file" not in argv
        assert [a for a in argv if a.startswith("type=volume")] == [
            "type=volume,source=boca-socios_boca_data,target=/data,volume-nocopy,readonly",
            "type=volume,source=boca-socios_boca_telegram,target=/run/telegram,volume-nocopy"
            + ("" if op == "install-direct" else ",readonly"),
        ]
    args = {"operation": "install-direct", "attempt_id": "42", "expected_source_sha": SOURCE}
    receipt = TelegramBackendReceipt(
        "install-direct",
        "42",
        SOURCE,
        "INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING",
        "CONTROLLER_HEALTHY_ENGINE_OFF",
    )
    assert verify_backend_receipt(receipt.redacted_json(), **args) == receipt.redacted_json()
    for change in ({"state": "READY"}, {"sender_state": "VERIFIED"}, {"attempt_id": "43"}):
        forged = boot._canonical({**json.loads(receipt.redacted_json()), **change})
        with pytest.raises(ValueError):
            verify_backend_receipt(forged, **args)


def test_direct_workflow_never_publishes_a_success_after_lost_remote_ack(tmp_path):
    from boca_socios.host_telegram_backend import TelegramBackendReceipt
    from test_r309_telegram_prepare_transport import STEP, _enabled, _run, _shell

    op = "telegram-install-direct"
    assert _enabled(STEP, op)
    assert _enabled("Prove Telegram release ancestry and build installed transaction", op)
    for name in (
        "Recheck current main before Telegram post-install custody",
        "Mark Telegram host attempt before starting existing Boca daemon",
        "Start only stopped existing dedicated Boca daemon",
        "Execute protected Telegram schema, custody or one-shot test",
        "Stop positively identified Boca services after Telegram custody",
    ):
        assert not _enabled(name, op)
    script = _shell(STEP)
    tail = script[script.index('if [[ "$verification_rc"') :]
    normal = TelegramBackendReceipt(
        "install-direct",
        "42",
        SOURCE,
        "INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING",
        "CONTROLLER_HEALTHY_ENGINE_OFF",
    )
    for remote in (0, 7):
        summary = tmp_path / f"summary-{remote}"
        result = _run(
            ["/bin/bash", "-euo", "pipefail", "-c", tail],
            tmp_path,
            env={
                "BOCA_OPERATION": op,
                "verification_rc": "0",
                "remote_rc": str(remote),
                "verified": "BOCA_TELEGRAM_HOST " + normal.redacted_json().decode(),
                "GITHUB_STEP_SUMMARY": str(summary),
                "PATH": "/usr/bin:/bin",
            },
        )
        assert (result.returncode == 0) == (remote == 0)
        assert ("INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING" in summary.read_text()) == (
            remote == 0
        )


def test_committed_pair_can_be_read_without_the_transient_stage_or_original_lease(dirs):
    req = {**BASE, **call("inspect-direct", dirs, BASE)}
    call("install-direct", dirs, req)
    # Model a separately authorized cleanup. The installer itself may never do this.
    (dirs[0] / STAGE).unlink()
    verifier = getattr(_helper(), "verify_committed", None)
    assert callable(verifier), "missing independent read-only verifier"
    assert verifier(dirs[1], SOURCE, "b" * 64, uid=os.getuid()) == {"state": "INSTALLED_SENDER_OFF"}
    for source, stage_id in [(SOURCE, "d" * 64), ("e" * 40, "b" * 64)]:
        with pytest.raises(ValueError):
            verifier(dirs[1], source, stage_id, uid=os.getuid())
    path = dirs[1] / "direct_chat_id"
    path.chmod(0o600)
    path.write_text("123456")
    path.chmod(0o400)
    with pytest.raises(ValueError):
        verifier(dirs[1], SOURCE, "b" * 64, uid=os.getuid())


@pytest.mark.parametrize("uncertain", [False, True])
def test_host_requires_independent_reader_and_retired_writer_before_restore(dirs, uncertain):
    from types import SimpleNamespace

    from boca_socios import host_telegram_backend as backend

    state = {"stopped": False, "observed": False}

    class Context:
        installation = SimpleNamespace(
            source_sha=SOURCE,
            controller_id="d" * 64,
            worker_id="e" * 64,
            pair=SimpleNamespace(sender_running=False, sender_id=None),
        )
        attempt_id, workflow_sha, binding_digest = "42", "a" * 40, "f" * 64
        volumes = (("boca-socios_boca_telegram", "local"),)

        def healthy(self):
            assert not state["stopped"]

        def stop(self):
            self.healthy()
            state["stopped"] = True

        def stopped(self):
            assert state["stopped"]

        def restore(self):
            assert state["observed"], "never restore with an unretired writer"
            state["stopped"] = False

    class Storage:
        direct_writer_retired = True

        def call(self, op, request):
            if op == "owner-identity":
                return {"owner_digest": "b" * 64}
            if op == "install-direct":
                assert state["stopped"]
                if uncertain:
                    self.direct_writer_retired = False
                    raise ValueError("writer retirement could not be proved")
            if op == "verify-direct":
                assert state["stopped"]
                state["observed"] = True
            return call(op, dirs, request)

    if uncertain:
        with pytest.raises(backend.TelegramBackendError) as exc:
            backend._direct_install(Context(), Storage())
        assert exc.value.receipt.state == "CLEANUP_INDETERMINATE"
        assert exc.value.receipt.restoration == "INDETERMINATE"
        assert state["stopped"]
    else:
        receipt = backend._direct_install(Context(), Storage())
        assert receipt.state == "INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING"
        assert not state["stopped"] and state["observed"]
