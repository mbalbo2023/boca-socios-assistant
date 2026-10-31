"""Fail closed if a queued manual operation no longer targets current main."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from boca_socios.deploy_inputs import DeployInputError, validate_main_ref


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_main_ref.py MAIN_REF_JSON SOURCE_SHA", file=sys.stderr)
        return 2
    try:
        with Path(sys.argv[1]).open("rb") as response:
            raw = response.read(8193)
        if len(raw) > 8192:
            raise DeployInputError("current main ref response is too large")
        validate_main_ref(json.loads(raw), sys.argv[2])
    except (OSError, ValueError) as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    print("BOCA_MAIN_REF_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
