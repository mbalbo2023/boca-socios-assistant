"""Fail-closed, read-only companion artifact gate for a future pre-SSH browser install.

CLI is deliberately fixed; no artifact content or coordinates are logged.
The controller v1 manifest and its deploy validator remain untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

from boca_socios.browser_release_manifest import (
    BrowserReleaseManifestError,
    validate_browser_manifest,
)
from boca_socios.release_manifest import ReleaseManifestError, read_manifest


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) != 6 or arguments[0] != "verify":
            raise BrowserReleaseManifestError("invalid companion command")
        _, artifact, source_sha, run_id, controller_digest, browser_digest = arguments
        validate_browser_manifest(
            read_manifest(Path(artifact)),
            controller_digest,
            browser_digest,
            source_sha,
            run_id,
        )
    except (ReleaseManifestError, BrowserReleaseManifestError):
        print("BOCA_BROWSER_RELEASE_MANIFEST_NO_GO", file=sys.stderr)
        return 1
    print("BOCA_BROWSER_RELEASE_MANIFEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
