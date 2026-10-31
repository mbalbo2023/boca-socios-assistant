"""Validate the resolved Compose JSON using an exact approved image digest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from boca_socios.deploy_contract import ContractError, validate_contract


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Boca-only deployment model")
    parser.add_argument("model", type=Path, help="docker compose config --format json output")
    parser.add_argument("image", help="approved immutable GHCR image reference")
    args = parser.parse_args()
    try:
        model = json.loads(args.model.read_text(encoding="utf-8"))
        validate_contract(model, args.image)
    except (OSError, json.JSONDecodeError, ContractError) as exc:
        # Do not echo model values or the source file's contents.
        reason = str(exc) if isinstance(exc, ContractError) else "unreadable Compose model"
        print(f"CONTRACT_FAIL: {reason}", file=sys.stderr)
        return 1
    print("CONTRACT_PASS: isolated simulation-only controller")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
