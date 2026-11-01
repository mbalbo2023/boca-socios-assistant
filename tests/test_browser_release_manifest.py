"""The browser release is a companion to, never a replacement for, controller v1."""

import json
from pathlib import Path
from runpy import run_path

import pytest

from boca_socios.browser_release_manifest import (
    BrowserReleaseManifestError,
    main,
    make_browser_manifest,
    validate_browser_manifest,
)
from boca_socios.release_manifest import make_manifest, read_manifest

SHA = "a" * 40
CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "c" * 64
RUN = "123456"


def test_companion_roundtrip_binds_both_digest_repositories_and_one_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["write", CONTROLLER, BROWSER, SHA, RUN]) == 0
    path = tmp_path / "browser-release.json"
    path.write_text(capsys.readouterr().out)
    assert read_manifest(path) == make_browser_manifest(CONTROLLER, BROWSER, SHA, RUN)
    assert set(make_browser_manifest(CONTROLLER, BROWSER, SHA, RUN)) == {
        "source_sha",
        "run_id",
        "controller_digest",
        "browser_digest",
    }
    assert main(["verify", str(path), CONTROLLER, BROWSER, SHA, RUN]) == 0
    assert "BROWSER_RELEASE_MANIFEST_PASS" in capsys.readouterr().out
    assert make_manifest(CONTROLLER, SHA, RUN) == {
        "image_ref": CONTROLLER,
        "source_sha": SHA,
        "release_run_id": RUN,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"controller_digest": BROWSER},
        {"browser_digest": CONTROLLER},
        {"browser_digest": "ghcr.io/unrelated/browser@sha256:" + "c" * 64},
        {"browser_digest": "ghcr.io/mbalbo2023/boca-socios-assistant-browser:latest"},
        {"browser_digest": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "g" * 64},
        {"source_sha": "d" * 40},
        {"run_id": "123457"},
        {"run_id": True},
        {"unreviewed": "field"},
        {"browser_digest": None},
    ],
)
def test_mixed_swapped_mutable_or_extra_coordinates_fail_closed(change: dict[str, object]) -> None:
    value: dict[str, object] = make_browser_manifest(CONTROLLER, BROWSER, SHA, RUN)
    value.update(change)
    with pytest.raises(BrowserReleaseManifestError):
        validate_browser_manifest(value, CONTROLLER, BROWSER, SHA, RUN)


def test_malformed_companion_and_invalid_source_coordinates_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(BrowserReleaseManifestError):
        make_browser_manifest(CONTROLLER, BROWSER, "bad", RUN)
    with pytest.raises(BrowserReleaseManifestError):
        make_browser_manifest(CONTROLLER, BROWSER, SHA, "0")
    with pytest.raises(BrowserReleaseManifestError):
        make_browser_manifest(CONTROLLER, CONTROLLER, SHA, RUN)
    for browser in (
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser:latest",
        "ghcr.io/other/browser@sha256:" + "c" * 64,
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "x" * 64,
    ):
        with pytest.raises(BrowserReleaseManifestError):
            make_browser_manifest(CONTROLLER, browser, SHA, RUN)

    path = tmp_path / "browser-release.json"
    path.write_text(json.dumps(make_browser_manifest(CONTROLLER, BROWSER, SHA, RUN)) + "\n")
    symlink = tmp_path / "redirect.json"
    symlink.symlink_to(path)
    assert main(["verify", str(symlink), CONTROLLER, BROWSER, SHA, RUN]) == 1
    path.write_text("x" * 1025)
    assert main(["verify", str(path), CONTROLLER, BROWSER, SHA, RUN]) == 1
    path.write_text('{"browser_digest":"one","browser_digest":"two"}')
    assert main(["verify", str(path), CONTROLLER, BROWSER, SHA, RUN]) == 1


def test_other_valid_browser_digest_is_not_accepted_for_one_release() -> None:
    manifest = make_browser_manifest(CONTROLLER, BROWSER, SHA, RUN)
    other = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "d" * 64
    with pytest.raises(BrowserReleaseManifestError):
        validate_browser_manifest(manifest, CONTROLLER, other, SHA, RUN)


def test_companion_cli_refuses_incomplete_or_unexpected_arguments() -> None:
    with pytest.raises(SystemExit):
        main(["write", CONTROLLER, SHA, RUN])


def test_fixed_pre_ssh_script_verifies_only_exact_companion_without_leaking_coordinates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/parse_browser_release_manifest.py")
    )["main"]
    path = tmp_path / "companion.json"
    path.write_text(json.dumps(make_browser_manifest(CONTROLLER, BROWSER, SHA, RUN)))
    arguments = ["verify", str(path), SHA, RUN, CONTROLLER, BROWSER]
    assert parser(arguments) == 0
    assert capsys.readouterr().out.strip() == "BOCA_BROWSER_RELEASE_MANIFEST_PASS"
    for altered in (
        ["write", *arguments[1:]],
        arguments[:-1],
        [*arguments, "extra"],
        [*arguments[:2], "d" * 40, *arguments[3:]],
        [*arguments[:3], "123457", *arguments[4:]],
        [*arguments[:4], BROWSER, arguments[5]],
        [*arguments[:5], CONTROLLER],
    ):
        assert parser(altered) == 1
        output = capsys.readouterr()
        assert "BOCA_BROWSER_RELEASE_MANIFEST_NO_GO" in output.err
        assert SHA not in output.err and BROWSER not in output.err
