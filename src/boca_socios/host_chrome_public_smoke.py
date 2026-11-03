"""One-shot public Boca login-page smoke with the already installed host Chrome.

The test NEVER submits a form, uses credentials/cookies, touches the queue or
prints page data. Run only as dedicated UID 10001 in the protected GitHub gate.
Its temporary profile and entire browser process group are torn down even on
timeouts. A bot challenge is reported and never bypassed.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

LOGIN_URL = "https://bocasocios.bocajuniors.com.ar/auth/login"
_NAMES = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
_CHALLENGES = ("verify you are human", "checking your browser", "captcha", "unusual traffic")


class _InputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.password_field = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "input" and str(dict(attrs).get("type") or "").lower() == "password":
            self.password_field = True


def _classify(html: str) -> str:
    sample = html[:1_000_000].lower()
    if any(marker in sample for marker in _CHALLENGES):
        return "CHALLENGE"
    if "<html" not in sample:
        return "NO_GO"
    parser = _InputParser()
    parser.feed(sample)
    return "FORM_VISIBLE" if parser.password_field else "OTHER_PAGE"


def _browser_argv(binary: str, profile: str) -> list[str]:
    return [
        binary,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--virtual-time-budget=10000",
        f"--user-data-dir={profile}",
        "--dump-dom",
        LOGIN_URL,
    ]


def _launch_and_teardown(binary: str, profile: str) -> str:
    process = subprocess.Popen(  # noqa: S603
        _browser_argv(binary, profile),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=25)
        if process.returncode != 0 or len(stdout) > 2_000_000:
            return ""
        return stdout.decode("utf-8", errors="replace")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def main(source_sha: str) -> int:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None or os.getuid() != 10001:
        print("BOCA_CHROME_PUBLIC state=NO_GO cleanup=VERIFIED")
        return 1
    state = "NO_GO"
    cleanup = "VERIFIED"
    try:
        binary = next((path for name in _NAMES if (path := shutil.which(name))), None)
        if binary is not None:
            with tempfile.TemporaryDirectory(prefix="boca-chrome-public-", dir="/tmp") as profile:
                html = _launch_and_teardown(binary, profile)
                state = _classify(html)
    except (OSError, ValueError, subprocess.SubprocessError):
        cleanup = "INDETERMINATE"
        state = "NO_GO"
    except Exception:
        # The temporary profile cleanup is not proven on an unexpected error.
        cleanup = "INDETERMINATE"
        state = "NO_GO"
    print(f"BOCA_CHROME_PUBLIC state={state} cleanup={cleanup}")
    return 0 if state == "FORM_VISIBLE" and cleanup == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) == 2 else ""))
