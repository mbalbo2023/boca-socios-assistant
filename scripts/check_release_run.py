"""Check bounded GitHub release-run metadata before host SSH is configured."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from boca_socios.release_run import ReleaseRunError, validate_release_run


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: check_release_run.py JSON SOURCE_SHA RUN_ID", file=sys.stderr)
        return 2
    try:
        path = Path(sys.argv[1])
        if path.stat().st_size > 65_536:
            raise ReleaseRunError("release metadata exceeds size limit")
        data = json.loads(path.read_text(encoding="utf-8"))
        validate_release_run(data, sys.argv[2], sys.argv[3])
    except (OSError, UnicodeError, json.JSONDecodeError, ReleaseRunError) as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    print("BOCA_RELEASE_RUN_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
