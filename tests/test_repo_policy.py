"""Only the protected first-deploy workflow can contain host commands."""

import runpy
from pathlib import Path

check_policy = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/check_repo_policy.py")
)["check_policy"]


def _root(tmp_path: Path) -> Path:
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / "AGENTS.md").touch()
    (tmp_path / ".github/CODEOWNERS").touch()
    (tmp_path / ".github/pull_request_template.md").touch()
    (tmp_path / "compose.yaml").write_text(
        "name: boca-socios\nBOCA_RUNTIME_MODE: simulation\nmem_limit: 256m\ncpus: 0.50\n"
    )
    return tmp_path


def test_ssh_in_another_workflow_is_blocked(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ".github/workflows/ci.yml").write_text("workflow_dispatch:\nssh host\n")
    assert any("forbidden workflow pattern" in finding for finding in check_policy(root))


def test_dedicated_workflow_without_approval_gates_is_blocked(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ".github/workflows/boca-first-deploy.yml").write_text("ssh host\n")
    assert any("missing gate" in finding for finding in check_policy(root))


def test_duplicate_adr_number_is_blocked(tmp_path: Path) -> None:
    root = _root(tmp_path)
    adr = root / "docs/ADR"
    adr.mkdir(parents=True)
    (adr / "0045-local-status-projection.md").write_text("# Panel\n")
    (adr / "0045-readonly-host-readiness.md").write_text("# Host\n")
    assert "duplicate ADR number: 0045" in check_policy(root)
