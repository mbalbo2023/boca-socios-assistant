"""Runtime-only opt-in for owner-authenticated Telegram V2 staging.

No Telegram provider call, real token, host, Docker, migration or HTTP port.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import runtime as runtime_module
from boca_socios.config import Settings
from boca_socios.owner_origin import SSH_LOOPBACK_ORIGIN
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    PairingStageConflict,
)
from boca_socios.runtime import _configured_telegram_pairing_stager
from test_telegram_pairing_staging import _sealed_v2


def _settings(directory: Path, *, mode: str = "off") -> Settings:
    return Settings(
        environment="staging",
        runtime_mode="simulation",
        db_path=directory / "boca.sqlite3",
        master_key_file=directory / "master_key",
        panel_origin=SSH_LOOPBACK_ORIGIN,
        owner_subject="owner",
        passkey_credential_id_file=directory / "credential_id",
        passkey_public_key_der_file=directory / "public_key",
        bind_host="0.0.0.0",  # noqa: S104 - container-local, no host exposure
        bind_port=8443,
        browser_backend="ipc",
        telegram_pairing_stage_mode=mode,
    )


def test_staging_is_default_off_without_touching_volumes(tmp_path: Path) -> None:
    directory = tmp_path / "missing-volume"
    settings = _settings(directory)
    settings.validate_beta()

    assert _configured_telegram_pairing_stager(settings, boca_volume_root=directory) is None
    assert not directory.exists()


def test_explicit_staging_writes_only_encrypted_v2_to_preexisting_boca_volume(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, mode="encrypted-only")
    settings.validate_beta()
    callback = _configured_telegram_pairing_stager(settings, boca_volume_root=tmp_path)
    assert callback is not None
    assert list(tmp_path.iterdir()) == []
    envelope, fingerprint = _sealed_v2()

    receipt = callback(envelope)

    target = tmp_path / STAGING_FILENAME
    assert receipt.state == "STAGED_PENDING_PROTECTED_CUTOVER"
    assert receipt.recipient_fingerprint == fingerprint
    assert target.is_file()
    assert target.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [target]
    assert envelope not in target.read_bytes()
    with pytest.raises(PairingStageConflict, match="pairing_stage_exists"):
        callback(envelope)


def test_missing_preexisting_boca_volume_fails_before_enabling_post(tmp_path: Path) -> None:
    directory = tmp_path / "not-created"
    settings = _settings(directory, mode="encrypted-only")
    settings.validate_beta()

    with pytest.raises(ValueError, match="private Telegram staging unavailable"):
        _configured_telegram_pairing_stager(settings, boca_volume_root=directory)
    assert not directory.exists()


def test_runtime_rejects_wrong_volume_symlink_or_unsafe_directory(tmp_path: Path) -> None:
    settings = _settings(tmp_path, mode="encrypted-only")
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="private Telegram staging unavailable"):
        _configured_telegram_pairing_stager(settings, boca_volume_root=other)

    link = tmp_path / "alias"
    link.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="private Telegram staging unavailable"):
        _configured_telegram_pairing_stager(
            _settings(link, mode="encrypted-only"), boca_volume_root=link
        )

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe.chmod(0o777)
    with pytest.raises(ValueError, match="private Telegram staging unavailable"):
        _configured_telegram_pairing_stager(
            _settings(unsafe, mode="encrypted-only"), boca_volume_root=unsafe
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"browser_backend": "off"},
        {"environment": "production"},
        {"panel_origin": "https://boca.invalid"},
        {"bind_host": "127.0.0.1"},
        {"bind_port": 9443},
    ],
)
def test_staging_never_wires_controller_only_or_non_localhost_beta(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    settings = replace(_settings(tmp_path, mode="encrypted-only"), **changes)
    with pytest.raises(ValueError, match="private Telegram staging"):
        settings.validate_beta()
    with pytest.raises(ValueError, match="private Telegram staging"):
        _configured_telegram_pairing_stager(settings, boca_volume_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_invalid_mode_fails_closed_without_creating_any_stage(tmp_path: Path) -> None:
    settings = _settings(tmp_path, mode="provider-online")
    with pytest.raises(ValueError, match="Telegram staging mode"):
        settings.validate_beta()
    assert list(tmp_path.iterdir()) == []


def test_settings_environment_defaults_off_and_only_explicit_optin_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOCA_TELEGRAM_PAIRING_STAGE_MODE", raising=False)
    assert Settings.from_environment().telegram_pairing_stage_mode == "off"
    monkeypatch.setenv("BOCA_TELEGRAM_PAIRING_STAGE_MODE", "encrypted-only")
    assert Settings.from_environment().telegram_pairing_stage_mode == "encrypted-only"
    monkeypatch.setenv("BOCA_TELEGRAM_PAIRING_STAGE_MODE", "telegram-online")
    with pytest.raises(ValueError, match="Telegram staging mode"):
        Settings.from_environment().validate_beta()


@pytest.mark.parametrize("mode,enabled", [("off", False), ("encrypted-only", True)])
def test_real_beta_builder_passes_callback_only_after_explicit_optin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    enabled: bool,
) -> None:
    """Test actual runtime→private-panel injection without any host listener."""
    settings = _settings(tmp_path, mode=mode)
    observed: list[object] = []

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

    actual_stager_factory = runtime_module._configured_telegram_pairing_stager
    monkeypatch.setattr(
        runtime_module,
        "_configured_telegram_pairing_stager",
        lambda supplied: actual_stager_factory(supplied, boca_volume_root=tmp_path),
    )
    monkeypatch.setattr(runtime_module, "_browser_for_beta", lambda *_a, **_k: (object(), 30.0))
    monkeypatch.setattr(runtime_module, "_read_config_file", lambda *_a, **_k: b"fixture")
    monkeypatch.setattr(runtime_module, "_configured_event", lambda _path: {})
    monkeypatch.setattr(runtime_module, "PasskeyOwnerAuthentication", lambda **_k: object())
    monkeypatch.setattr(runtime_module.LocalBetaRuntime, "start", lambda **_k: FakeRuntime())
    monkeypatch.setattr(runtime_module, "_LoopbackHTTPWSGIServer", FakeServer)

    def panel_factory(**kwargs: object) -> object:
        observed.append(kwargs["telegram_pairing_stager"])
        return object()

    monkeypatch.setattr(runtime_module, "PrivatePanelApplication", panel_factory)
    served = runtime_module.build_beta_server(settings)
    try:
        assert isinstance(served.server, FakeServer)
        assert len(observed) == 1
        assert callable(observed[0]) is enabled
        assert list(tmp_path.iterdir()) == []
    finally:
        served.close()
