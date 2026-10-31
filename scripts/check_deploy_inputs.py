"""Validate manual first-deployment coordinates before contacting a host."""

from __future__ import annotations

import sys

from boca_socios.deploy_inputs import DeployInputError, validate_deploy_inputs


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "usage: check_deploy_inputs.py IMAGE SHA SERVICE BUDGET RELEASE_RUN_ID", file=sys.stderr
        )
        return 2
    try:
        validate_deploy_inputs(*sys.argv[1:])
    except DeployInputError as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    print("BOCA_DISPATCH_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
