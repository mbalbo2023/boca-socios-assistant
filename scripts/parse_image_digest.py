"""Extract the immutable image reference from a bounded docker push log."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from boca_socios.image_release import ReleaseError, parse_push_digest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Boca image push digest")
    parser.add_argument("push_log", type=Path)
    parser.add_argument("commit_sha")
    parser.add_argument("--role", choices=("controller", "browser"), default="controller")
    args = parser.parse_args()
    try:
        if args.push_log.stat().st_size > 1_048_576:
            raise ReleaseError("push log exceeds size limit")
        result = parse_push_digest(
            args.push_log.read_text(encoding="utf-8"), args.commit_sha, role=args.role
        )
    except (OSError, UnicodeError, ReleaseError) as exc:
        reason = str(exc) if isinstance(exc, ReleaseError) else "unreadable push evidence"
        print(f"RELEASE_FAIL: {reason}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
