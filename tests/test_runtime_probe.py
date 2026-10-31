"""The in-container read-only probe must prove applied cgroup v2 limits."""

from pathlib import Path

import pytest

from boca_socios import runtime_probe as probe


def _private_cgroup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.controllers").write_text("cpu memory pids\n")
    (root / "cpu.max").write_text("50000 100000\n")
    (root / "memory.max").write_text("268435456\n")
    (root / "pids.max").write_text("64\n")
    proc = tmp_path / "self-cgroup"
    proc.write_text("0::/\n")
    monkeypatch.setattr(probe, "CGROUP_ROOT", root)
    monkeypatch.setattr(probe, "SELF_CGROUP", proc)
    return root


def test_private_cgroup_probe_reports_only_bounded_effective_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _private_cgroup(tmp_path, monkeypatch)
    assert probe.main() == 0
    assert capsys.readouterr().out.strip() == (
        '{"cpu_quota":50000,"cpu_period":100000,"memory_bytes":268435456,"pids_limit":64}'
    )


def test_missing_cgroup_v2_mount_is_no_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _private_cgroup(tmp_path, monkeypatch)
    (root / "cgroup.controllers").unlink()
    assert probe.main() == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("filename", "value"),
    [
        ("cpu.max", "max 100000\n"),
        ("cpu.max", "100000 100000\n"),
        ("memory.max", "max\n"),
        ("memory.max", "536870912\n"),
        ("pids.max", "max\n"),
        ("pids.max", "65\n"),
        ("self-cgroup", "0::/user.slice/other\n"),
        ("cpu.max", "0" * 129),
    ],
)
def test_missing_or_relaxed_effective_limits_are_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    filename: str,
    value: str,
) -> None:
    root = _private_cgroup(tmp_path, monkeypatch)
    target = tmp_path / filename if filename == "self-cgroup" else root / filename
    target.write_text(value)
    assert probe.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "BOCA_CGROUP_NO_GO"
