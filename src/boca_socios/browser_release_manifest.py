"""Companion evidence for two images published by one protected release run.

The controller's original three-field release manifest stays unchanged so
legacy Boca first-install gates continue to verify their exact v1 contract.
This separate bounded manifest is for a future, separately reviewed browser
install gate; writing it does not authorize a host operation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from boca_socios.release_manifest import ReleaseManifestError, make_manifest, read_manifest

_BROWSER_REPOSITORY = "ghcr.io/mbalbo2023/boca-socios-assistant-browser"
_BROWSER_REF = re.compile(rf"{re.escape(_BROWSER_REPOSITORY)}@sha256:[0-9a-f]{{64}}\Z")


class BrowserReleaseManifestError(ValueError):
    """Both approved immutable images cannot be bound to one exact release."""


def make_browser_manifest(
    controller_image_ref: str, browser_image_ref: str, source_sha: str, run_id: str
) -> dict[str, str]:
    if any(
        type(coordinate) is not str
        for coordinate in (controller_image_ref, browser_image_ref, source_sha, run_id)
    ):
        raise BrowserReleaseManifestError("invalid release coordinate type")
    try:
        controller = make_manifest(controller_image_ref, source_sha, run_id)
    except ReleaseManifestError:
        raise BrowserReleaseManifestError("invalid controller release coordinates") from None
    if (
        not isinstance(browser_image_ref, str)
        or not _BROWSER_REF.fullmatch(browser_image_ref)
        or browser_image_ref.split("@", 1)[1] == controller_image_ref.split("@", 1)[1]
    ):
        raise BrowserReleaseManifestError("invalid browser image digest")
    return {
        "source_sha": controller["source_sha"],
        "run_id": controller["release_run_id"],
        "controller_digest": controller["image_ref"],
        "browser_digest": browser_image_ref,
    }


def validate_browser_manifest(
    value: object, controller_image_ref: str, browser_image_ref: str, source_sha: str, run_id: str
) -> None:
    expected = make_browser_manifest(controller_image_ref, browser_image_ref, source_sha, run_id)
    if not isinstance(value, dict) or set(value) != set(expected):
        raise BrowserReleaseManifestError("invalid browser release manifest fields")
    if any(type(value[key]) is not str or value[key] != expected[key] for key in expected):
        raise BrowserReleaseManifestError("browser release coordinates mismatched")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind both Boca image digests to one release")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("write", "verify"):
        action = commands.add_parser(command)
        if command == "verify":
            action.add_argument("path", type=Path)
        action.add_argument("controller_image_ref")
        action.add_argument("browser_image_ref")
        action.add_argument("source_sha")
        action.add_argument("run_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            print(
                json.dumps(
                    make_browser_manifest(
                        args.controller_image_ref,
                        args.browser_image_ref,
                        args.source_sha,
                        args.run_id,
                    )
                )
            )
        else:
            validate_browser_manifest(
                read_manifest(args.path),
                args.controller_image_ref,
                args.browser_image_ref,
                args.source_sha,
                args.run_id,
            )
            print("BROWSER_RELEASE_MANIFEST_PASS")
    except (BrowserReleaseManifestError, ReleaseManifestError):
        print("BOCA_BROWSER_RELEASE_NO_GO", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
