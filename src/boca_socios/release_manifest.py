"""Bind a deployment digest to the successful image release run that published it."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from boca_socios.deploy_inputs import DeployInputError, validate_deploy_inputs


class ReleaseManifestError(ValueError):
    """The release artifact is missing, malformed or describes another image."""


def make_manifest(image_ref: str, source_sha: str, run_id: str) -> dict[str, str]:
    try:
        validate_deploy_inputs(image_ref, source_sha, "controller", "0.5cpu-256m-64pids", run_id)
    except DeployInputError as exc:
        raise ReleaseManifestError("invalid release coordinates") from exc
    return {"image_ref": image_ref, "source_sha": source_sha, "release_run_id": run_id}


def validate_manifest(value: object, image_ref: str, source_sha: str, run_id: str) -> None:
    expected = make_manifest(image_ref, source_sha, run_id)
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ReleaseManifestError("invalid release manifest fields")
    if any(type(value[key]) is not str or value[key] != expected[key] for key in expected):
        raise ReleaseManifestError("release manifest does not match approved digest and run")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ReleaseManifestError("duplicate release manifest field")
        fields[key] = value
    return fields


def read_manifest(path: Path) -> object:
    try:
        # Open once without following a symlink, then bound the same file that
        # is parsed. This prevents metadata/read races on downloaded artifacts.
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC), "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 1024:
                raise ReleaseManifestError("release manifest is not a bounded regular file")
            data = stream.read(1025)
            if len(data) != metadata.st_size:
                raise ReleaseManifestError("release manifest changed while reading")
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError("release manifest cannot be read") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind Boca image digest to a release run")
    subcommands = parser.add_subparsers(dest="command", required=True)
    writer = subcommands.add_parser("write")
    writer.add_argument("image_ref")
    writer.add_argument("source_sha")
    writer.add_argument("run_id")
    checker = subcommands.add_parser("verify")
    checker.add_argument("path", type=Path)
    checker.add_argument("image_ref")
    checker.add_argument("source_sha")
    checker.add_argument("run_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            print(json.dumps(make_manifest(args.image_ref, args.source_sha, args.run_id)))
        else:
            validate_manifest(
                read_manifest(args.path), args.image_ref, args.source_sha, args.run_id
            )
            print("BOCA_RELEASE_MANIFEST_PASS")
    except ReleaseManifestError as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
