"""Only the digest printed for the exact reviewed SHA may be recorded."""

import pytest

from boca_socios.image_release import ReleaseError, parse_push_digest

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def test_exact_push_digest_is_bound_to_commit() -> None:
    output = f"layer: Pushed\nsha-{SHA}: digest: {DIGEST} size: 1234\n"
    assert parse_push_digest(output, SHA) == (
        f"ghcr.io/mbalbo2023/boca-socios-assistant@{DIGEST}"
    )


@pytest.mark.parametrize(
    "output",
    [
        "layer: Pushed\n",
        f"sha-{'c' * 40}: digest: {DIGEST} size: 1234\n",
        f"sha-{SHA}: digest: sha256:{'g' * 64} size: 1234\n",
        f"sha-{SHA}: digest: {DIGEST} size: 1234\nsha-{SHA}: digest: {DIGEST} size: 1234\n",
        f"prefix sha-{SHA}: digest: {DIGEST} size: 1234\n",
    ],
)
def test_missing_wrong_or_ambiguous_digest_fails(output: str) -> None:
    with pytest.raises(ReleaseError):
        parse_push_digest(output, SHA)


def test_invalid_commit_sha_is_rejected() -> None:
    with pytest.raises(ReleaseError):
        parse_push_digest(f"sha-{SHA}: digest: {DIGEST} size: 1234", "bad")
