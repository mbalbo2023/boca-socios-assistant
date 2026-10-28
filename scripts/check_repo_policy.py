"""Fail-closed checks to keep this project separate from unrelated workloads."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    workflow_files = list((root / ".github" / "workflows").glob("*.yml"))
    failures: list[str] = []
    if "name: boca-socios" not in compose:
        failures.append("Compose project must be exactly boca-socios")
    if "BOCA_RUNTIME_MODE: simulation" not in compose:
        failures.append("default Compose runtime must be simulation-only")
    if "mem_limit: 256m" not in compose or "cpus: 0.50" not in compose:
        failures.append("controller resource limits must be retained")
    for forbidden in (
        "network_mode: host",
        "privileged: true",
        "container_name:",
        "ports:",
        "pid: host",
        "volumes_from:",
        "docker.sock",
        "/var/run/",
        "external: true",
    ):
        if forbidden in compose:
            failures.append(f"forbidden Compose feature: {forbidden}")
    if not workflow_files:
        failures.append("CI workflow is required")
    for workflow in workflow_files:
        data = workflow.read_text(encoding="utf-8")
        for forbidden in (
            "pull_request_target:",
            "runs-on: self-hosted",
            "docker system prune",
            "docker volume prune",
            "ssh ",
            "scp ",
        ):
            if forbidden in data:
                failures.append(f"forbidden workflow pattern in {workflow.name}: {forbidden}")
    for relative in ("AGENTS.md", ".github/CODEOWNERS", ".github/pull_request_template.md"):
        if not (root / relative).is_file():
            failures.append(f"missing governance file: {relative}")
    for finding in failures:
        print(f"POLICY_FAIL: {finding}", file=sys.stderr)
    if failures:
        return 1
    print("POLICY_PASS: isolated Compose, simulation gate and PR governance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
