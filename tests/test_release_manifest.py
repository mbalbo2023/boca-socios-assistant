"""A cited successful release must have published the exact approved digest."""

import json
from pathlib import Path

import pytest

from boca_socios.release_manifest import (
    ReleaseManifestError,
    main,
    make_manifest,
    read_manifest,
    validate_manifest,
)

SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
OTHER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64
RUN = "123456"


def test_manifest_roundtrip_binds_release_and_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["write", IMAGE, SHA, RUN]) == 0
    manifest = tmp_path / "release.json"
    manifest.write_text(capsys.readouterr().out)
    assert read_manifest(manifest) == make_manifest(IMAGE, SHA, RUN)
    assert main(["verify", str(manifest), IMAGE, SHA, RUN]) == 0


@pytest.mark.parametrize(
    "changed",
    [
        {"image_ref": OTHER_IMAGE},
        {"source_sha": "d" * 40},
        {"release_run_id": "123457"},
        {"unreviewed": "field"},
        {"image_ref": None},
    ],
)
def test_other_image_run_or_extra_field_is_no_go(changed: dict[str, object]) -> None:
    manifest: dict[str, object] = make_manifest(IMAGE, SHA, RUN)
    manifest.update(changed)
    with pytest.raises(ReleaseManifestError):
        validate_manifest(manifest, IMAGE, SHA, RUN)


@pytest.mark.parametrize("payload", ["", "not json", "{}", "[]"])
def test_missing_or_malformed_artifact_is_no_go(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "release.json"
    path.write_text(payload)
    with pytest.raises(ReleaseManifestError):
        validate_manifest(read_manifest(path), IMAGE, SHA, RUN)


def test_symlink_or_oversized_artifact_is_no_go(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text(json.dumps(make_manifest(IMAGE, SHA, RUN)))
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(ReleaseManifestError):
        read_manifest(tmp_path / "link.json")
    target.write_text(" " * 1025)
    with pytest.raises(ReleaseManifestError):
        read_manifest(target)


def test_duplicate_digest_field_is_ambiguous_and_no_go(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    path.write_text(
        '{"image_ref":"first","image_ref":"second",'
        f'"source_sha":"{SHA}","release_run_id":"{RUN}"}}'
    )
    with pytest.raises(ReleaseManifestError, match="duplicate"):
        read_manifest(path)


def test_workflow_checks_artifact_before_host_credentials() -> None:
    root = Path(__file__).resolve().parents[1]
    deploy = (root / ".github/workflows/boca-first-deploy.yml").read_text()
    release = (root / ".github/workflows/release-image.yml").read_text()
    assert release.index("python -m boca_socios.release_manifest write") < release.index(
        "uses: actions/upload-artifact@"
    )
    assert "if-no-files-found: error" in release
    assert "overwrite: false" in release
    assert deploy.index("python scripts/check_release_run.py") < deploy.index("gh run download")
    assert (
        deploy.index("gh run download")
        < deploy.index("python -m boca_socios.release_manifest verify")
        < deploy.index("Configure pinned SSH host key")
    )
