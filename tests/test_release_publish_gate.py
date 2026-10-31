"""Manual image publication must not rerun or publish stale main source."""

from pathlib import Path


def test_manual_image_publication_checks_attempt_and_live_main_before_effects() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/release-image.yml"
    ).read_text()
    publish = workflow.split("  publish:\n", maxsplit=1)[1]
    assert publish.index('test "$GITHUB_RUN_ATTEMPT" = 1') < publish.index(
        "Build one local controller image"
    )
    checks = [
        index
        for index in range(len(publish))
        if publish.startswith("python scripts/check_main_ref.py", index)
    ]
    assert len(checks) == 2
    assert checks[0] < publish.index("Build one local controller image")
    assert (
        publish.index("Scan the image that will be published")
        < checks[1]
        < publish.index("Log in only after successful scan")
    )
    assert publish.count('gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"') == 2
