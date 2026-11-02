"""Validate manual first-deployment coordinates before contacting a host."""

from __future__ import annotations

import sys

from boca_socios.deploy_inputs import DeployInputError, validate_deploy_inputs


def main() -> int:
    browser_ipc_v2 = len(sys.argv) == 7 and sys.argv[1] == "--browser-ipc-v2"
    if not browser_ipc_v2 and len(sys.argv) != 6:
        print(
            "usage: check_deploy_inputs.py [--browser-ipc-v2] IMAGE SHA SERVICE BUDGET RELEASE_RUN_ID",
            file=sys.stderr,
        )
        return 2
    try:
        validate_deploy_inputs(
            *sys.argv[2:] if browser_ipc_v2 else sys.argv[1:], browser_ipc_v2=browser_ipc_v2
        )
    except DeployInputError as exc:
        print(f"BOCA_NO_GO: {exc}", file=sys.stderr)
        return 1
    print("BOCA_DISPATCH_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
