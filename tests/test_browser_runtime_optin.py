"""The isolated UNIX browser can only be selected explicitly for served BETA."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from boca_socios import runtime as runtime_module
from boca_socios.browser.contracts import SimulationOutcome
from boca_socios.browser.ipc_client import UnixSyntheticBrowser
from boca_socios.browser.ipc_protocol import SOCKET_PATH, SyntheticIPCError
from boca_socios.config import Settings
from boca_socios.integration import operational


def _settings(tmp_path: Path, backend: str = "off") -> Settings:
    return Settings(
        environment="staging",
        runtime_mode="simulation",
        db_path=tmp_path / "boca.sqlite3",
        master_key_file=tmp_path / "boca.key",
        panel_origin="http://localhost:8443",
        owner_subject="synthetic-owner",
        passkey_credential_id_file=tmp_path / "credential_id",
        passkey_public_key_der_file=tmp_path / "public.der",
        bind_host="0.0.0.0",  # noqa: S104 - isolated synthetic Compose controller fixture
        bind_port=8443,
        browser_backend=backend,
    )


def test_browser_backend_environment_defaults_to_off_and_is_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BOCA_BROWSER_BACKEND", raising=False)
    assert Settings.from_environment().browser_backend == "off"
    monkeypatch.setenv("BOCA_BROWSER_BACKEND", "ipc")
    assert Settings.from_environment().browser_backend == "ipc"
    for invalid in ("on", "live", "chromium", "automatic", "IPC", ""):
        with pytest.raises(ValueError, match="browser"):
            _settings(tmp_path, invalid).validate_beta()


def test_browser_opt_in_is_only_for_private_ssh_origin_and_staging(tmp_path: Path) -> None:
    allowed = _settings(tmp_path, "ipc")
    allowed.validate_beta()
    for variant in (
        replace(allowed, panel_origin="https://boca.example.test"),
        replace(allowed, bind_host="127.0.0.1"),
        replace(allowed, bind_port=9443),
        replace(allowed, environment="production"),
        replace(allowed, engine_mode="on"),
        replace(allowed, runtime_mode="live"),
    ):
        with pytest.raises(ValueError):
            variant.validate_beta()


def test_off_mode_stays_inert_and_explicit_fake_injection_stays_available(tmp_path: Path) -> None:
    class FakeBrowser:
        async def simulate_general_reservation(self) -> SimulationOutcome:
            return SimulationOutcome.RESERVED_IN_SIMULATOR

    default, budget = runtime_module._browser_for_beta(_settings(tmp_path))
    assert isinstance(default, runtime_module._LocalSyntheticBrowser)
    assert budget == 5.0
    supplied = FakeBrowser()
    selected, budget = runtime_module._browser_for_beta(_settings(tmp_path), supplied)
    assert selected is supplied and budget == 5.0
    with pytest.raises(ValueError, match="ambiguous"):
        runtime_module._browser_for_beta(_settings(tmp_path, "ipc"), supplied)


def test_explicit_ipc_requires_uid_and_known_socket_before_any_storage_or_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, "ipc")
    monkeypatch.setattr(runtime_module.os, "geteuid", lambda: 10000)
    monkeypatch.setattr(runtime_module.os, "getegid", lambda: 10001)
    with pytest.raises(ValueError, match="browser worker"):
        runtime_module.build_beta_server(settings)
    assert not settings.db_path.exists()

    monkeypatch.setattr(runtime_module.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(runtime_module.os, "getegid", lambda: 10001)

    def missing_socket(*_args: object, **_kwargs: object) -> None:
        raise SyntheticIPCError("ipc_socket_unverified")

    monkeypatch.setattr("boca_socios.browser.ipc_protocol.socket_identity", missing_socket)
    with pytest.raises(ValueError, match="browser worker"):
        runtime_module.build_beta_server(settings)
    assert not settings.db_path.exists()


def test_valid_explicit_ipc_preflight_selects_only_fixed_unix_path_and_longer_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_module.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(runtime_module.os, "getegid", lambda: 10001)
    checked: list[Path] = []

    def verify(path: Path, *, uid: int) -> tuple[int, int]:
        assert uid == 10002
        checked.append(path)
        return (123, 456)

    monkeypatch.setattr("boca_socios.browser.ipc_protocol.socket_identity", verify)
    selected, timeout = runtime_module._browser_for_beta(_settings(tmp_path, "ipc"))
    assert isinstance(selected, UnixSyntheticBrowser)
    assert timeout == 30.0
    assert checked == [SOCKET_PATH]


@pytest.mark.parametrize("on_demand", [False, True])
def test_served_beta_wires_ipc_port_and_thirty_second_command_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_demand: bool
) -> None:
    settings = replace(_settings(tmp_path, "ipc"), bot_control="on-demand" if on_demand else "off")
    selected = UnixSyntheticBrowser()
    calls: list[dict[str, object]] = []
    panel_calls: list[dict[str, object]] = []

    class FakeRuntime:
        members = object()
        commands = object()

        def close(self) -> None:
            pass

    class FakeServer:
        def __init__(self, *_args: object) -> None:
            self.app: object | None = None

        def set_app(self, app: object) -> None:
            self.app = app

        def server_close(self) -> None:
            pass

    def browser_for_beta(
        provided: Settings, injected: object | None = None
    ) -> tuple[UnixSyntheticBrowser, float]:
        assert provided is settings and injected is None
        return selected, 30.0

    def start_runtime(**kwargs: object) -> FakeRuntime:
        calls.append(kwargs)
        return FakeRuntime()

    monkeypatch.setattr(runtime_module, "_browser_for_beta", browser_for_beta)
    monkeypatch.setattr(runtime_module, "_read_config_file", lambda *_a, **_k: b"fixture")
    monkeypatch.setattr(runtime_module, "PasskeyOwnerAuthentication", lambda **_k: object())
    monkeypatch.setattr(runtime_module, "_configured_event", lambda _path: {})
    monkeypatch.setattr(runtime_module.LocalBetaRuntime, "start", start_runtime)
    monkeypatch.setattr(
        runtime_module, "PrivatePanelApplication", lambda **kw: panel_calls.append(kw) or object()
    )
    monkeypatch.setattr(runtime_module, "_LoopbackHTTPWSGIServer", FakeServer)
    served = runtime_module.build_beta_server(settings)
    try:
        assert isinstance(served.server, FakeServer)
        assert served.server.app is not None
        if on_demand:
            assert isinstance(calls[0]["browser"], runtime_module._LocalSyntheticBrowser)
            assert calls[0]["bot_session"].on_start is not None
            assert served.observation_session is not None
            assert panel_calls[0]["automatic_monitor"].snapshot()["latest"] is None
        else:
            assert calls[0]["browser"] is selected
        assert calls[0]["command_timeout_seconds"] == 30.0
        assert panel_calls[0]["source_sha"] == settings.source_sha
    finally:
        served.close()


@pytest.mark.parametrize("command_timeout", [5.0, 30.0])
def test_local_beta_runtime_passes_command_timeout_only_to_existing_coordinator(
    tmp_path: Path, command_timeout: float
) -> None:
    key_file = tmp_path / "master.key"
    key_file.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
    key_file.chmod(0o400)
    observed: list[float] = []

    class FakeBrowser:
        async def simulate_general_reservation(self) -> SimulationOutcome:
            return SimulationOutcome.RESERVED_IN_SIMULATOR

    class FakeCommands:
        def close(self) -> None:
            pass

    def start_commands(coordinator: object, **_kwargs: object) -> FakeCommands:
        observed.append(coordinator._timeout)  # type: ignore[attr-defined]
        return FakeCommands()

    with patch.object(operational.BetaCommandHost, "start", side_effect=start_commands):
        runtime = operational.LocalBetaRuntime.start(
            database_path=tmp_path / "boca.sqlite3",
            key_file=key_file,
            browser=FakeBrowser(),
            initialize_new=True,
            command_timeout_seconds=command_timeout,
        )
        runtime.close()
    assert observed == [command_timeout]


def test_initialize_beta_refuses_browser_opt_in_without_creating_storage(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "ipc")
    with pytest.raises(ValueError, match="initialization"):
        runtime_module.initialize_beta(settings)
    assert not settings.db_path.exists()


@pytest.mark.parametrize("backend,expect_socket", [("off", False), ("ipc", True)])
def test_full_beta_config_preflight_verifies_socket_only_when_explicitly_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    backend: str,
    expect_socket: bool,
) -> None:
    from boca_socios import beta_config_preflight

    settings = _settings(tmp_path, backend)
    monkeypatch.setattr(
        runtime_module.Settings, "from_environment", classmethod(lambda _cls: settings)
    )
    monkeypatch.setattr(beta_config_preflight, "check_beta_config", lambda *_a, **_k: None)
    socket_checks: list[str] = []

    def verify_socket(_settings: Settings) -> tuple[object, float]:
        socket_checks.append("checked")
        raise ValueError("synthetic browser worker boundary unavailable")

    monkeypatch.setattr(runtime_module, "_browser_for_beta", verify_socket)
    code = runtime_module.main(("check-beta-config",))
    assert socket_checks == (["checked"] if expect_socket else [])
    assert code == (1 if expect_socket else 0)
    event = json.loads(capsys.readouterr().out)["event"]
    assert event == ("beta_config_unavailable" if expect_socket else "beta_config_ready")


def test_bot_control_is_an_explicit_ssh_only_simulation_ipc_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BOCA_BOT_CONTROL", raising=False)
    assert not Settings.from_environment().bot_on_demand
    monkeypatch.setenv("BOCA_BOT_CONTROL", "on-demand")
    assert Settings.from_environment().bot_on_demand
    allowed = replace(_settings(tmp_path, "ipc"), bot_control="on-demand")
    allowed.validate_beta()
    for variant in (
        replace(allowed, bot_control="ON-DEMAND"),
        replace(allowed, bot_control=""),
        replace(allowed, browser_backend="off"),
        replace(allowed, site_bridge_mode="poll"),
        replace(allowed, environment="production"),
        replace(allowed, panel_origin="https://example.invalid"),
        replace(allowed, engine_mode="on"),
        replace(allowed, runtime_mode="live"),
    ):
        with pytest.raises(ValueError):
            variant.validate_beta()


def test_on_demand_cold_uses_real_ipc_port_without_inspecting_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(_settings(tmp_path, "ipc"), bot_control="on-demand")
    monkeypatch.setattr(
        "boca_socios.browser.ipc_protocol.socket_identity",
        lambda *_a, **_k: pytest.fail("cold panel touched the worker socket"),
    )
    monkeypatch.setattr(runtime_module.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(runtime_module.os, "getegid", lambda: 10001)
    selected, timeout = runtime_module._browser_for_beta(settings)
    assert isinstance(selected, UnixSyntheticBrowser)
    assert timeout == 30
    monkeypatch.setattr(runtime_module.os, "getegid", lambda: 10002)
    with pytest.raises(ValueError, match="worker boundary"):
        runtime_module._browser_for_beta(settings)


@pytest.mark.parametrize("receipt", [None, "REQUESTED", "CLAIMED", "UNCERTAIN", "APPLIED"])
def test_on_demand_reboot_opens_panel_but_never_recovers_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt: str | None
) -> None:
    from uuid import uuid4

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from boca_socios.integration.beta import BetaCoordinator
    from boca_socios.panel.lifecycle_intents import LifecycleIntentStore, host_marker
    from boca_socios.storage.database import Database

    legacy = _settings(tmp_path, "off")
    legacy.master_key_file.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
    legacy.master_key_file.chmod(0o400)
    assert legacy.passkey_credential_id_file is not None
    assert legacy.passkey_public_key_der_file is not None
    legacy.passkey_credential_id_file.write_bytes(b"local-test-credential")
    public_key = ec.generate_private_key(ec.SECP256R1()).public_key()
    legacy.passkey_public_key_der_file.write_bytes(
        public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    runtime_module.initialize_beta(legacy)
    database = Database(legacy.db_path)
    operation_id = str(uuid4())
    if receipt is not None:
        LifecycleIntentStore(database).request("bot", "start", operation_id)
        with database.connection() as connection, connection:
            for phase in ("CLAIMED", "UNCERTAIN", "APPLIED"):
                if phase == "CLAIMED" and receipt == "REQUESTED":
                    break
                if phase == "UNCERTAIN" and receipt != "UNCERTAIN":
                    continue
                connection.execute(
                    "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                    host_marker(operation_id, "bot", "start", phase),
                )
                if phase == receipt:
                    break

    def no_replay(*_a: object, **_k: object) -> None:
        pytest.fail("cold boot started command recovery")

    monkeypatch.setattr(BetaCoordinator, "recover", no_replay)
    monkeypatch.setattr(
        "boca_socios.browser.ipc_protocol.socket_identity",
        lambda *_a, **_k: pytest.fail("cold boot accessed worker"),
    )
    actual_select = runtime_module._browser_for_beta

    def controller_select(settings: Settings, supplied: object) -> tuple[object, float]:
        with monkeypatch.context() as identity:
            identity.setattr(runtime_module.os, "geteuid", lambda: 10001)
            identity.setattr(runtime_module.os, "getegid", lambda: 10001)
            return actual_select(settings, supplied)

    monkeypatch.setattr(runtime_module, "_browser_for_beta", controller_select)
    http_server = runtime_module._LoopbackHTTPWSGIServer
    monkeypatch.setattr(
        runtime_module,
        "_LoopbackHTTPWSGIServer",
        lambda _addr, handler: http_server(("127.0.0.1", 0), handler),
    )
    served = runtime_module.build_beta_server(
        replace(legacy, browser_backend="ipc", bot_control="on-demand")
    )
    try:
        assert served.runtime.commands.engine_stopped
        assert served.runtime.ready
        status: list[str] = []
        response = served.server.get_app()(
            {
                "PATH_INFO": "/healthz",
                "REQUEST_METHOD": "GET",
                "wsgi.url_scheme": "http",
                "HTTP_HOST": "localhost:8443",
            },
            lambda result, _headers: status.append(result),
        )
        assert response == [b"BOCA_BETA_READY"] and status == ["200 OK"]
        with pytest.raises(RuntimeError, match="stopped"):
            served.runtime.commands.begin(str(uuid4()), member_id="member", event_id="event")
        assert not served.runtime.commands.stop_engine()
        assert not served.runtime.commands.stop_engine()
        assert served.runtime.commands.engine_stopped
    finally:
        served.close()
