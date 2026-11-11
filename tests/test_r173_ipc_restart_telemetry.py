"""Only exact worker-owned, fixed-category telemetry may be reset on IPC restart."""

from __future__ import annotations

import os

import pytest

from boca_socios.browser import activity_events, ipc_server
from boca_socios.browser.ipc_protocol import SyntheticIPCError


def _directory(tmp_path):
    directory = tmp_path / "ipc"
    directory.mkdir(mode=0o711)
    directory.chmod(0o711)
    return directory


def _reset(directory):
    return activity_events.reset_chromium_activity(
        path=directory / "chromium-events.jsonl",
        owner_uid=os.geteuid(),
        owner_gid=os.getegid(),
    )


def test_restart_clears_only_previous_fixed_category_chromium_evidence(tmp_path):
    directory = _directory(tmp_path)
    for name in ("chromium-events.jsonl", "chromium-events.previous"):
        file = directory / name
        file.write_text('{"v":1,"e":"browser_closed"}\n')
        file.chmod(0o644)

    _reset(directory)

    assert list(directory.iterdir()) == []


@pytest.mark.parametrize("name", ["unreviewed.db", "synthetic.sock"])
def test_restart_rejects_unknown_file_without_touching_existing_telemetry(tmp_path, name):
    directory = _directory(tmp_path)
    telemetry = directory / "chromium-events.jsonl"
    telemetry.touch(mode=0o644)
    other = directory / name
    other.touch(mode=0o600)

    with pytest.raises(SyntheticIPCError):
        _reset(directory)

    assert telemetry.exists() and other.exists()


@pytest.mark.parametrize("case", ["symlink", "unsafe_permissions", "over_quota"])
def test_restart_rejects_untrusted_telemetry_without_removing_it(tmp_path, case):
    directory = _directory(tmp_path)
    telemetry = directory / "chromium-events.jsonl"
    if case == "symlink":
        target = tmp_path / "owned-outside"
        target.write_text("must not be touched")
        telemetry.symlink_to(target)
    else:
        telemetry.write_bytes(b"x" * (activity_events.MAX_ACTIVITY_BYTES + 1))
        telemetry.chmod(0o600 if case == "unsafe_permissions" else 0o644)

    with pytest.raises(SyntheticIPCError):
        _reset(directory)

    assert telemetry.is_symlink() if case == "symlink" else telemetry.exists()


def test_ipc_server_restart_checks_telemetry_before_binding():
    # The boot contract must not accept an old Chromium log as an unexpected
    # file and then falsely label a safe clean restart as IPC_MOUNT_NOT_EMPTY.
    import inspect

    source = inspect.getsource(ipc_server.UnixSyntheticWorker.start)
    assert "reset_chromium_activity" in source
    assert source.index("reset_chromium_activity") < source.index("listener.bind")
