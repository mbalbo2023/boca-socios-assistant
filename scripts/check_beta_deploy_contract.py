"""Validate the resolved optional BETA Compose model without disclosing owner data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from boca_socios.deploy_contract import (
    ContractError,
    validate_beta_browser_contract,
    validate_beta_contract,
)


def main() -> int:
    legacy_v1 = len(sys.argv) == 3
    browser_ipc_v2 = len(sys.argv) == 4 and sys.argv[3] == "--topology=browser-ipc-v2"
    if not (legacy_v1 or browser_ipc_v2):
        print("BETA_COMPOSE_NO_GO: expected model path and immutable image", file=sys.stderr)
        return 1
    try:
        model = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        origin = os.environ.get("BOCA_PANEL_ORIGIN", "")
        owner = os.environ.get("BOCA_OWNER_SUBJECT", "")
        if legacy_v1:
            validate_beta_contract(model, sys.argv[2], origin, owner)
        else:
            overlay = (
                Path(__file__).resolve().parents[1] / "compose.beta.browser.yaml"
            ).read_bytes()
            validate_beta_browser_contract(
                model,
                sys.argv[2],
                os.environ.get("BOCA_BROWSER_IMAGE", ""),
                origin,
                owner,
                os.environ.get("BOCA_BROWSER_SECCOMP_PATH", ""),
                os.environ.get("BOCA_BROWSER_ATTEMPT_ID", ""),
                staged_overlay=overlay,
                overlay_sha=hashlib.sha256(overlay).hexdigest(),
            )
    except ContractError as exc:
        # Only a fixed field label may reach Actions. Never print Compose values,
        # actual URLs, owner identifiers, credentials or arbitrary map keys.
        field = str(exc).split(" keys (", 1)[0]
        if not re.fullmatch(r"invalid [A-Za-z0-9 _.-]{1,100}", field):
            field = "reviewed isolated model mismatch"
        print(f"BETA_COMPOSE_NO_GO: {field}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError):
        print("BETA_COMPOSE_NO_GO: reviewed isolated model mismatch", file=sys.stderr)
        return 1
    if browser_ipc_v2:
        print(
            "BETA_BROWSER_COMPOSE_PASS: Boca-only IPC worker; dedicated egress, no public worker port"
        )
    else:
        print("BETA_COMPOSE_PASS: Boca-only served package on host loopback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
