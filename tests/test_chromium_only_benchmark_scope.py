"""Chromium-only measurement must never substitute the full production browser."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/chromium-only-size-benchmark.yml"
BENCHMARK = ROOT / "benchmarks/chromium_only/Dockerfile"


def test_size_comparison_is_pr_only_and_has_no_release_or_host_permissions() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  pull_request:\n" in workflow
    assert "    paths:\n" in workflow
    assert "  workflow_dispatch:" not in workflow
    assert "  push:" not in workflow
    assert "  contents: read" in workflow
    assert "  packages: write" not in workflow
    assert "publish-reviewed-image" not in workflow
    assert "BOCA_CHROMIUM_ONLY_BENCHMARK" in workflow
    assert "host_delta=UNVERIFIED" in workflow
    assert "product_unchanged=true" in workflow
    assert "docker image save" in workflow
    for forbidden in ("ssh ", "docker push", "docker prune", "docker image rm"):
        assert forbidden not in workflow


def test_comparison_installs_only_chromium_but_does_not_change_product() -> None:
    benchmark = BENCHMARK.read_text(encoding="utf-8")
    product = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    assert "FROM ${BENCHMARK_BASE}" in benchmark
    assert "python -m playwright install --with-deps chromium" in benchmark
    assert "playwright==1.64.1" in benchmark
    assert "COPY scripts/verify_chromium_worker.py" in benchmark
    assert "COPY src/boca_socios/browser/" not in benchmark
    assert "mcr.microsoft.com/playwright/python:v1.64.1-noble@sha256:" in product
    assert "python -m playwright install --with-deps chromium" in product
