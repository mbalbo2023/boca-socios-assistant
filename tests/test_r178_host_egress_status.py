"""R178: pinned Boca-only, running-worker diagnostic; zero container lifecycle effects."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from boca_socios import host_on_demand_status as status
from test_host_on_demand_status import PINS, host  # noqa: F401 - imported pytest fixture


@pytest.fixture
def prepared(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], list[str]]:
    state, events = request.getfixturevalue("host")
    state.update(state="running", pid=42, healthy=True, engine=True)
    network = {"boca-socios_boca_browser_egress": {"IPAddress": "172.30.0.2"}}

    class DockerMetadata:
        def field(self, kind: str, container: str, name: str) -> object:
            assert kind == "container"
            assert len(container) == 64
            assert name == "NetworkSettings.Networks"
            events.append("network")
            return network

    monkeypatch.setattr(status, "ProductionRootlessDockerIO", DockerMetadata)
    monkeypatch.setattr(
        status.cleanup,
        "_docker",
        lambda *args: (
            events.append("exec")
            or _assert_exact_exec_args(args)
            or "BOCA_WORKER_EGRESS state=PASS dns=PASS https=PASS\n"
        ),
    )
    return state, events


def _assert_exact_exec_args(args: tuple[str, ...]) -> None:
    assert args[:3] == ("exec", "--user", "10002:10002")
    assert len(args) == 8
    assert len(args[3]) == 64
    assert args[4:] == ("python", "-m", "boca_socios.browser.egress_probe", "--once")


def test_running_worker_performs_only_boca_exact_cid_exec(
    prepared: object, capsys: pytest.CaptureFixture[str]
) -> None:
    state, events = prepared
    assert status.main(["host-egress", *PINS]) == 0
    result = capsys.readouterr()
    assert result.out == (
        f"BOCA_ON_DEMAND_EGRESS run={PINS[3]} source={PINS[0]} state=PASS dns=PASS https=PASS\n"
    )
    assert not result.err
    assert events.count("exec") == 1
    assert events.count("physical") == 2
    assert events.count("network") == 2
    assert state["state"] == "running"


def test_stopped_worker_no_go_without_start_or_exec(
    prepared: object, capsys: pytest.CaptureFixture[str]
) -> None:
    state, events = prepared
    state.update(state="exited", pid=0, healthy=False)
    assert status.main(["host-egress", *PINS]) == 0
    assert capsys.readouterr().out.endswith("state=NO_GO stage=worker_stopped\n")
    assert "exec" not in events


def test_running_worker_with_network_none_refuses_before_exec(
    prepared: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, events = prepared

    class Disconnected:
        def field(self, *_args: object) -> object:
            return {}

    monkeypatch.setattr(status, "ProductionRootlessDockerIO", Disconnected)
    assert status.main(["host-egress", *PINS]) == 0
    assert capsys.readouterr().out.endswith("state=NO_GO stage=network_unverified\n")
    assert "exec" not in events


@pytest.mark.parametrize("reason", ["dns", "tls", "https"])
def test_dns_tls_https_failures_retained_as_safe_categories(
    prepared: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reason: str,
) -> None:
    monkeypatch.setattr(
        status.cleanup,
        "_docker",
        lambda *_a: f"BOCA_WORKER_EGRESS state=NO_GO stage={reason}\n",
    )
    assert status.main(["host-egress", *PINS]) == 0
    assert capsys.readouterr().out.endswith(f"state=NO_GO stage={reason}\n")


def test_raw_docker_failure_never_escapes_or_gets_claimed_green(
    prepared: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failure(*_a: str) -> str:
        raise RuntimeError("PRIVATE_TOKEN=sensitive /url/exposed")

    monkeypatch.setattr(status.cleanup, "_docker", failure)
    assert status.main(["host-egress", *PINS]) == 3
    output = capsys.readouterr()
    assert output.out == status.NO_GO + "\n"
    assert "PRIVATE_TOKEN" not in output.out + output.err


def test_runner_verifier_rejects_mismatched_run_and_invalid_output(
    prepared: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert status.main(["host-egress", *PINS]) == 0
    receipt = capsys.readouterr().out
    for variant in (
        receipt.replace(f"run={PINS[3]}", "run=123", 1),
        receipt.replace("dns=PASS", "dns=not_checked"),
        receipt + receipt,
        receipt + "SECRET=abc\n",
    ):
        monkeypatch.setattr(status.sys, "stdin", io.TextIOWrapper(io.BytesIO(variant.encode())))
        assert status.main(["verify-egress", *PINS]) == 3
        assert capsys.readouterr().out == status.NO_GO + "\n"
    monkeypatch.setattr(status.sys, "stdin", io.TextIOWrapper(io.BytesIO(receipt.encode())))
    assert status.main(["verify-egress", *PINS]) == 0
    assert capsys.readouterr().out == receipt


def test_no_synthetic_probe_uses_url_or_modifies_host_storage(prepared: object) -> None:
    _, events = prepared
    from boca_socios.browser import egress_probe

    assert egress_probe._HOST == "example.com"
    assert "boca" not in egress_probe._HOST
    assert "site" not in egress_probe._HOST
    assert not any(part in Path(egress_probe.__file__).name for part in ("site", "telegram"))
    assert "exec" not in events
