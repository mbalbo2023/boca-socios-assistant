"""Only the digest printed for the exact reviewed SHA may be recorded."""

import sys
from pathlib import Path
from runpy import run_path

import pytest

from boca_socios.image_release import ReleaseError, parse_push_digest

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def test_exact_push_digest_is_bound_to_commit() -> None:
    output = f"layer: Pushed\nsha-{SHA}: digest: {DIGEST} size: 1234\n"
    assert parse_push_digest(output, SHA) == (f"ghcr.io/mbalbo2023/boca-socios-assistant@{DIGEST}")


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


def test_browser_push_digest_requires_its_own_ghcr_repository_header() -> None:
    header = "The push refers to repository [ghcr.io/mbalbo2023/boca-socios-assistant-browser]"
    output = f"{header}\nlayer: Pushed\nsha-{SHA}: digest: {DIGEST} size: 1234\n"
    assert parse_push_digest(output, SHA, role="browser") == (
        f"ghcr.io/mbalbo2023/boca-socios-assistant-browser@{DIGEST}"
    )
    with pytest.raises(ReleaseError):
        parse_push_digest(output, SHA, role="controller")
    for altered in (
        output.replace("-browser]", "]"),
        output.replace(header + "\n", ""),
        output.replace(header, header + "\n" + header),
        output.replace("size: 1234", "size: 1234\n" + f"sha-{SHA}: digest: {DIGEST} size: 1"),
    ):
        with pytest.raises(ReleaseError):
            parse_push_digest(altered, SHA, role="browser")


def test_unknown_image_role_and_wrong_browser_commit_fail() -> None:
    with pytest.raises(ReleaseError):
        parse_push_digest("", SHA, role="worker-unknown")
    with pytest.raises(ReleaseError):
        parse_push_digest(
            "The push refers to repository [ghcr.io/mbalbo2023/boca-socios-assistant-browser]"
            + f"\nsha-{SHA}: digest: {DIGEST} size: 1234\n",
            "d" * 40,
            role="browser",
        )


def test_browser_push_cli_requires_exact_digest_and_repo(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    parse_cli = run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/parse_image_digest.py")
    )["main"]
    log = tmp_path / "browser-push.log"
    header = "The push refers to repository [ghcr.io/mbalbo2023/boca-socios-assistant-browser]"
    log.write_text(f"{header}\nsha-{SHA}: digest: {DIGEST} size: 1234\n")
    monkeypatch.setattr(sys, "argv", ["parse_image_digest.py", str(log), SHA, "--role", "browser"])
    assert parse_cli() == 0
    assert capsys.readouterr().out.strip() == (
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@" + DIGEST
    )
    log.write_text(f"sha-{SHA}: digest: {DIGEST} size: 1234\n")
    assert parse_cli() == 1
    assert "RELEASE_FAIL" in capsys.readouterr().err
    log.write_text("x" * 1_048_577)
    assert parse_cli() == 1
