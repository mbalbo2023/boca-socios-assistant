"""R172 reviewed worker entrypoint and smallest dedicated URL-config mount.

These are code/argv contracts only; never start Docker or the owner blackboxes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

WORKER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
CONTROLLER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64


def _mounts(argv: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == "--mount")


def test_browser_worker_has_ipc_server_entrypoint_and_readonly_url_config() -> None:
    argv = host._cutover_worker_create_argv(WORKER_IMAGE, "a" * 40, "123456", "c" * 64)
    assert argv[-3:] == ("python", "-m", "boca_socios.browser.ipc_server")
    assert _mounts(argv) == (
        "type=volume,source=boca-socios_boca_browser_ipc,target=/run/boca-browser-ipc,volume-nocopy",
        "type=volume,source=boca-socios_boca_site_config,target=/run/boca-site-config,readonly,volume-nocopy",
    )
    assert not any("boca_data" in value or "boca_key" in value for value in _mounts(argv))


def test_candidate_controller_writes_only_dedicated_url_config_volume() -> None:
    argv = host._cutover_candidate_create_argv(
        CONTROLLER_IMAGE,
        "a" * 40,
        "123456",
        "http://localhost:8443",
        "owner",
        "c" * 64,
        control_directory=Path("/home/boca-deploy/.boca-on-demand/socket"),
    )
    assert (
        "type=volume,source=boca-socios_boca_site_config,target=/run/boca-site-config,volume-nocopy"
        in _mounts(argv)
    )


def test_overlay_declares_exact_url_volume_and_ipc_server() -> None:
    overlay = Path(__file__).resolve().parents[1] / "compose.beta.browser.yaml"
    source = overlay.read_text(encoding="utf-8")
    assert 'command: ["python", "-m", "boca_socios.browser.ipc_server"]' in source
    assert "boca_site_config:/run/boca-site-config:ro" in source
    assert "boca_site_config:/run/boca-site-config" in source
    assert "name: boca-socios_boca_site_config" in source


def test_site_config_volume_is_created_with_boca_only_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, ...]] = []

    def run(*argv: str, **_kwargs: object) -> str:
        created.append(argv)
        return host.BROWSER_SITE_CONFIG_VOLUME

    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(
        host,
        "_browser_validate_site_config_volume",
        lambda attempt: created.append(("validated", attempt)),
        raising=False,
    )

    def probe(phase: str, attempt: str, argv: tuple[str, ...]) -> str:
        assert phase == "site-config-init" and attempt == "123456"
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
        assert "--mount" in argv
        assert (
            "type=volume,source=boca-socios_boca_site_config,target=/run/boca-site-config,volume-nocopy"
            in argv
        )
        assert "CHOWN" in argv and "FOWNER" in argv
        return "BOCA_SITE_CONFIG_DIR_PASS"

    monkeypatch.setattr(host, "_browser_named_probe", probe)
    host._browser_create_site_config_volume(WORKER_IMAGE, "123456")
    assert created == [
        (
            "docker",
            "volume",
            "create",
            "--driver",
            "local",
            "--label",
            "com.docker.compose.project=boca-socios",
            "--label",
            "com.docker.compose.volume=boca_site_config",
            "--label",
            "boca.socios.browser-ipc-attempt=123456",
            "boca-socios_boca_site_config",
        ),
        ("validated", "123456"),
        ("validated", "123456"),
    ]
