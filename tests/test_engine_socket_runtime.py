"""Opt-in IPC controller starts/stops only its private UDS, never another port."""

from threading import Event
from unittest.mock import Mock

import pytest

from boca_socios.runtime import ServedBeta


def test_served_ipc_beta_starts_engine_uds_and_closes_it_with_http() -> None:
    stopping = Event()
    server = Mock()
    server.handle_request.side_effect = lambda: stopping.set()
    runtime = Mock()
    uds = Mock()
    served = ServedBeta(server, runtime, engine_socket=uds)

    served.serve_until(stopping)

    uds.start.assert_called_once_with()
    server.handle_request.assert_called_once_with()
    server.server_close.assert_called_once_with()
    uds.close.assert_called_once_with()
    runtime.close.assert_called_once_with()
    served.close()  # Idempotent resource ownership.
    uds.close.assert_called_once()


def test_failed_uds_init_never_serves_partial_ipc_controller() -> None:
    server = Mock()
    runtime = Mock()
    uds = Mock()
    uds.start.side_effect = RuntimeError("synthetic-local-test")
    served = ServedBeta(server, runtime, engine_socket=uds)

    with pytest.raises(RuntimeError):
        served.serve_until(Event())

    server.handle_request.assert_not_called()
    server.server_close.assert_called_once()
    uds.close.assert_called_once()
    runtime.close.assert_called_once()


def test_legacy_controller_mode_has_no_new_control_socket() -> None:
    stopping = Event()
    server = Mock()
    server.handle_request.side_effect = lambda: stopping.set()
    runtime = Mock()
    served = ServedBeta(server, runtime)
    assert served.engine_socket is None
    served.serve_until(stopping)
    runtime.close.assert_called_once()


def test_ipc_listener_is_constructed_only_when_bounded_http_run_begins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boca_socios.runtime as runtime_module

    stopping = Event()
    server = Mock()
    server.handle_request.side_effect = lambda: stopping.set()
    runtime = Mock()
    uds = Mock()
    constructor = Mock(return_value=uds)
    monkeypatch.setattr(runtime_module, "LocalEngineSocket", constructor)
    served = ServedBeta(server, runtime, enable_engine_socket=True)
    constructor.assert_not_called()  # Build alone must remain side-effect-free.
    served.serve_until(stopping)
    constructor.assert_called_once_with(runtime.commands)
    uds.start.assert_called_once()
    uds.close.assert_called_once()


def test_socket_close_failure_still_closes_bridge_and_command_host() -> None:
    server = Mock()
    runtime = Mock()
    bridge = Mock()
    uds = Mock()
    uds.close.side_effect = RuntimeError("synthetic-close-failure")
    served = ServedBeta(server, runtime, bridge=bridge, engine_socket=uds)
    with pytest.raises(RuntimeError):
        served.close()
    bridge.close.assert_called_once()
    runtime.close.assert_called_once()
