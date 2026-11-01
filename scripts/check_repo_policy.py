"""Fail-closed checks to keep this project separate from unrelated workloads."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def check_policy(root: Path) -> list[str]:
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
        ):
            if forbidden in data:
                failures.append(f"forbidden workflow pattern in {workflow.name}: {forbidden}")
        if workflow.name == "boca-first-deploy.yml":
            # This single, manual workflow is the only reviewed host path.
            # Keep the generic SSH ban in every other workflow.
            for required in (
                "workflow_dispatch:",
                "environment: boca-first-deploy",
                "BOCA_HOST_READONLY_ENV_READY",
                "BOCA_DEPLOY_ENV_READY",
                'test "$BOCA_HOST_READONLY_ENV_READY" = ready',
                'test "$BOCA_DEPLOY_ENV_READY" = ready',
                'test "$GITHUB_RUN_ATTEMPT" = 1',
                "python scripts/check_main_ref.py",
                "StrictHostKeyChecking yes",
                "BatchMode yes",
                "BOCA_DEPLOY_KNOWN_HOSTS",
                "github.ref == 'refs/heads/main'",
                "github.actor == 'mbalbo2023'",
                "python3 - preflight",
                "python3 - observe",
                "python3 - apply",
            ):
                if required not in data:
                    failures.append(f"first-deploy workflow missing gate: {required}")
            # PRs have separate pending slots; every manual operation shares
            # the same fixed host mutex, independent of inputs/ref/run/SHA.
            concurrency = (
                "concurrency:\n"
                "  group: ${{ github.event_name == 'pull_request' && "
                "format('boca-first-deploy-pr-{0}', github.event.pull_request.number) "
                "|| 'boca-first-deploy' }}\n"
                "  cancel-in-progress: false\n"
            )
            pattern = r"^" + re.escape(concurrency) + r"(?=\n|$)"
            if re.search(pattern, data, re.MULTILINE) is None:
                failures.append(
                    "first-deploy workflow missing gate: isolated PR/manual concurrency"
                )
        else:
            for forbidden in ("ssh ", "scp "):
                if forbidden in data:
                    failures.append(f"forbidden workflow pattern in {workflow.name}: {forbidden}")
    for relative in ("AGENTS.md", ".github/CODEOWNERS", ".github/pull_request_template.md"):
        if not (root / relative).is_file():
            failures.append(f"missing governance file: {relative}")
    adr_numbers: set[str] = set()
    for adr in (root / "docs/ADR").glob("*.md"):
        match = re.fullmatch(r"(\d{4})-[a-z0-9-]+\.md", adr.name)
        if match is None:
            continue
        number = match.group(1)
        if number in adr_numbers:
            failures.append(f"duplicate ADR number: {number}")
        adr_numbers.add(number)
    return failures


def main() -> int:
    failures = check_policy(Path(__file__).resolve().parents[1])
    for finding in failures:
        print(f"POLICY_FAIL: {finding}", file=sys.stderr)
    if failures:
        return 1
    print("POLICY_PASS: isolated Compose, simulation gate and PR governance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
