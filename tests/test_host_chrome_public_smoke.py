"""The first live-site diagnostic must never submit credentials or bookings."""

from pathlib import Path

import pytest

from boca_socios import host_chrome_public_smoke as smoke


def test_workflow_is_protected_and_has_a_single_read_only_public_smoke() -> None:
    source = Path(".github/workflows/boca-first-deploy.yml").read_text()
    assert "chrome-host-public-smoke" in source
    assert "if: inputs.operation == 'chrome-host-public-smoke'" in source
    assert "src/boca_socios/host_chrome_public_smoke.py" in source
    assert "BOCA_CHROME_PUBLIC\\ state=(FORM_VISIBLE|OTHER_PAGE|CHALLENGE|NO_GO)" in source


def test_invalid_input_or_wrong_uid_refuses_before_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(smoke.os, "getuid", lambda: 10001)
    assert smoke.main("bad") == 1
    monkeypatch.setattr(smoke.os, "getuid", lambda: 10002)
    assert smoke.main("a" * 40) == 1
    assert capsys.readouterr().out.count("BOCA_CHROME_PUBLIC state=NO_GO cleanup=VERIFIED") == 2


def test_html_classification_is_bounded() -> None:
    assert smoke._classify('<html><input type="password"></html>') == "FORM_VISIBLE"
    assert smoke._classify("<html><p>Verify you are human</p></html>") == "CHALLENGE"
    assert smoke._classify("<html><body>OK</body></html>") == "OTHER_PAGE"
    assert smoke._classify("network failure") == "NO_GO"


def test_fixed_target_and_flags_never_bypass_browser_sandbox(tmp_path: Path) -> None:
    args = smoke._browser_argv("/usr/bin/google-chrome-stable", str(tmp_path))
    assert smoke.LOGIN_URL == "https://bocasocios.bocajuniors.com.ar/auth/login"
    assert args[0] == "/usr/bin/google-chrome-stable"
    assert args[-1] == smoke.LOGIN_URL
    assert "--headless=new" in args
    assert "--no-sandbox" not in args
    assert "--ignore-certificate-errors" not in args
    assert "--disable-web-security" not in args
    assert "--disable-blink-features=AutomationControlled" not in args


def test_successful_fake_chrome_shuts_down_and_cleans_private_profile(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(smoke.os, "getuid", lambda: 10001)
    monkeypatch.setattr(
        smoke.shutil,
        "which",
        lambda name: "/usr/bin/google-chrome-stable" if name == "google-chrome-stable" else None,
    )
    profiles: list[str] = []

    def pretend_run(binary: str, profile: str) -> str:
        assert binary == "/usr/bin/google-chrome-stable"
        profiles.append(profile)
        assert Path(profile).exists()
        return '<html><input type="password"></html>'

    monkeypatch.setattr(smoke, "_launch_and_teardown", pretend_run)
    assert smoke.main("a" * 40) == 0
    assert len(profiles) == 1 and not Path(profiles[0]).exists()
    assert capsys.readouterr().out == "BOCA_CHROME_PUBLIC state=FORM_VISIBLE cleanup=VERIFIED\n"
