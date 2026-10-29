"""A deployment dispatch must carry exact immutable, Boca-only coordinates."""

import pytest

from boca_socios.deploy_inputs import DeployInputError, validate_deploy_inputs

SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
BUDGET = "0.5cpu-256m-64pids"


def test_exact_deploy_coordinates_pass() -> None:
    validate_deploy_inputs(IMAGE, SHA, "controller", BUDGET, "123456")


@pytest.mark.parametrize(
    ("image", "sha", "service", "budget", "run_id"),
    [
        ("ghcr.io/mbalbo2023/boca-socios-assistant:latest", SHA, "controller", BUDGET, "1"),
        (IMAGE, "bad", "controller", BUDGET, "1"),
        (IMAGE, SHA, "worker", BUDGET, "1"),
        (IMAGE, SHA, "controller", "2cpu-4g", "1"),
        (IMAGE, SHA, "controller", BUDGET, "0"),
        (IMAGE, SHA, "controller", BUDGET, "1; id"),
    ],
)
def test_mutable_or_unsafe_dispatch_fails(
    image: str, sha: str, service: str, budget: str, run_id: str
) -> None:
    with pytest.raises(DeployInputError):
        validate_deploy_inputs(image, sha, service, budget, run_id)
