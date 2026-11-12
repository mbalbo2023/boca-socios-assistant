"""The controller's locked dependencies must not rebuild for a source-only edit.

This is a static Dockerfile contract: the cloud test container has no Docker
daemon. The actual cache hit and wall-time still require an Actions benchmark.
"""

from __future__ import annotations

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_controller_dependency_layer_is_before_any_source_copy() -> None:
    """A source-only edit must invalidate project install, not locked dependencies."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    build = text.split(" AS runtime", 1)[0]
    manifest_copy = "COPY pyproject.toml uv.lock README.md ./"
    locked_deps = "RUN uv sync --locked --no-dev --no-install-project"
    source_copy = "COPY src ./src"
    project_install = "RUN uv sync --locked --no-dev --no-editable"
    assert build.index(manifest_copy) < build.index(locked_deps)
    assert build.index(locked_deps) < build.index(source_copy)
    assert build.index(source_copy) < build.index(project_install)
    assert build.count(locked_deps) == 1
    assert build.count(project_install) == 1


def test_controller_runtime_keeps_exact_final_package_and_isolation() -> None:
    """Moving dependency installation cannot drop the actual Boca wheel."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "uv sync --locked --no-dev --no-install-project" in text
    assert "uv sync --locked --no-dev --no-editable" in text
    assert "COPY --from=build /app/.venv /app/.venv" in text
    assert "from boca_socios.security.credential_vault import CredentialVault" in text
    assert "USER 10001:10001" in text
    assert "--offline" not in text
    assert "--no-cache" not in text.split(" AS runtime", 1)[0].split("COPY pyproject.toml", 1)[1]
    assert "COPY . ." not in text
