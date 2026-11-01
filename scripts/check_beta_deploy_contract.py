"""Validate the resolved optional BETA Compose model without disclosing owner data."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from boca_socios.deploy_contract import validate_beta_contract


def main() -> int:
    if len(sys.argv) != 3:
        print("BETA_COMPOSE_NO_GO: expected model path and immutable image", file=sys.stderr)
        return 1
    try:
        model = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        validate_beta_contract(
            model,
            sys.argv[2],
            os.environ.get("BOCA_PANEL_ORIGIN", ""),
            os.environ.get("BOCA_OWNER_SUBJECT", ""),
        )
    except (OSError, ValueError, TypeError):
        print("BETA_COMPOSE_NO_GO: reviewed isolated model mismatch", file=sys.stderr)
        return 1
    print("BETA_COMPOSE_PASS: Boca-only served package on host loopback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
