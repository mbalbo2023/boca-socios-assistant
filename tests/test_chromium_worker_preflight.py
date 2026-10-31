"""Nonroot and browser-binary gates for the isolated offline Chromium smoke."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def worker():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_chromium_worker.py"
    spec = importlib.util.spec_from_file_location("chromium_worker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_rejects_root_even_with_browser_binary(tmp_path: Path) -> None:
    module = worker()
    browser = tmp_path / "chrome"
    browser.touch()
    with pytest.raises(module.WorkerPreflightError, match="nonroot"):
        module.validate_worker_identity(0, browser)


def test_worker_rejects_another_nonroot_uid(tmp_path: Path) -> None:
    module = worker()
    browser = tmp_path / "chrome"
    browser.touch()
    with pytest.raises(module.WorkerPreflightError, match="worker_uid_mismatch"):
        module.validate_worker_identity(1000, browser)


def test_worker_rejects_missing_browser_binary(tmp_path: Path) -> None:
    module = worker()
    with pytest.raises(module.WorkerPreflightError, match="browser_missing"):
        module.validate_worker_identity(10002, tmp_path / "missing")


def test_worker_accepts_installed_browser_under_nonroot_identity(tmp_path: Path) -> None:
    browser = tmp_path / "chrome"
    browser.touch()
    worker().validate_worker_identity(10002, browser)
