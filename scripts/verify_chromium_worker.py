"""Offline Chromium startup check; no external site or reservation is visited.

Run inside the separate nonroot browser image with Docker networking disabled.
The public Boca observer is an independent, opt-in command in the same image.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


class WorkerPreflightError(RuntimeError):
    """The browser process cannot start within the intended identity boundary."""


def validate_worker_identity(uid: int, executable_path: Path) -> None:
    if uid == 0:
        raise WorkerPreflightError("nonroot_required")
    if not executable_path.is_file():
        raise WorkerPreflightError("browser_missing")


async def verify() -> None:
    from playwright.async_api import async_playwright

    phase = "initialize"
    try:
        async with async_playwright() as api:
            phase = "binary"
            validate_worker_identity(os.geteuid(), Path(api.chromium.executable_path))
            phase = "launch"
            browser = await api.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                timeout=15_000,
                args=["--disable-background-networking"],
            )
            try:
                phase = "context"
                context = await browser.new_context(
                    accept_downloads=False, service_workers="block", java_script_enabled=True
                )
                try:
                    phase = "page"
                    page = await context.new_page()
                    # Browser-internal page: no fake reservation or external URL.
                    phase = "navigate"
                    await page.goto("about:blank", timeout=5_000)
                    phase = "evaluate"
                    if await page.evaluate("1 + 1") != 2:
                        raise WorkerPreflightError("javascript_engine_unavailable")
                finally:
                    phase = "close_context"
                    await context.close()
            finally:
                phase = "close_browser"
                await browser.close()
    except WorkerPreflightError:
        raise
    except Exception as error:
        # A fixed phase and class cannot reveal browser paths or page content.
        raise WorkerPreflightError(f"{phase}_{type(error).__name__}") from None


def main() -> int:
    try:
        asyncio.run(asyncio.wait_for(verify(), timeout=30))
    except WorkerPreflightError as error:
        print(f"chromium_worker_stopped: {error}", file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt) as error:
        # Browser errors can include paths, URLs and page content; discard them.
        print(f"chromium_worker_stopped: {type(error).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({"mode": "offline_chromium_startup", "result": "pass"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
