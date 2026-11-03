"""Issue #281: inspect only existing host browser binary; never launch it."""

from pathlib import Path

import pytest


def test_approved_workflow_exposes_only_manual_host_chrome_inspect() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    assert "chrome-host-inspect" in workflow
    assert "if: inputs.operation == 'chrome-host-inspect'" in workflow
    assert "src/boca_socios/host_chrome_inspect.py" in workflow
    assert "BOCA_HOST_CHROME\\ state=" in workflow
    assert "timeout --signal=TERM --kill-after=5s 30s ssh" in workflow


def test_binary_inspection_checks_boca_uid_and_exact_published_names(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_chrome_inspect as inspector

    monkeypatch.setattr(inspector.os, "getuid", lambda: 10001)
    monkeypatch.setattr(
        inspector.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None
    )
    assert inspector.main("a" * 40) == 0
    assert capsys.readouterr().out == "BOCA_HOST_CHROME state=PRESENT kind=chromium uid=10001\n"


def test_missing_chrome_reports_absent_not_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_chrome_inspect as inspector

    monkeypatch.setattr(inspector.os, "getuid", lambda: 10001)
    monkeypatch.setattr(inspector.shutil, "which", lambda _name: None)
    assert inspector.main("a" * 40) == 0
    assert capsys.readouterr().out == "BOCA_HOST_CHROME state=ABSENT kind=none uid=10001\n"


def test_wrong_identity_never_touches_browser_inventory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_chrome_inspect as inspector

    monkeypatch.setattr(inspector.os, "getuid", lambda: 0)
    monkeypatch.setattr(inspector.shutil, "which", lambda _name: pytest.fail("inventory"))
    assert inspector.main("a" * 40) == 1
    assert capsys.readouterr().out == "BOCA_HOST_CHROME state=NO_GO kind=none uid=unverified\n"


def test_invalid_sha_rejects_before_host_inventory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_chrome_inspect as inspector

    monkeypatch.setattr(inspector.os, "getuid", lambda: pytest.fail("identity"))
    assert inspector.main("not-a-sha") == 1
    assert capsys.readouterr().out == "BOCA_HOST_CHROME state=NO_GO kind=none uid=unverified\n"
