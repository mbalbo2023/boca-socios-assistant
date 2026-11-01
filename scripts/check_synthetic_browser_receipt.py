"""Accept only one fixed, nonsecret offline Chromium synthetic CI receipt."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, value in pairs:
        if name in fields:
            raise ValueError("duplicate synthetic browser field")
        fields[name] = value
    return fields


def validate_receipt(raw: str) -> bool:
    """Do not infer a Boca ticket, a remote visit, or a verified host from this."""
    if not isinstance(raw, str) or len(raw) > 256 or not raw.endswith("\n") or raw.count("\n") != 1:
        raise ValueError("invalid synthetic browser receipt framing")
    try:
        document = json.loads(raw[:-1], object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError):
        raise ValueError("invalid synthetic browser receipt") from None
    if (
        not isinstance(document, dict)
        or set(document) != {"mode", "result", "notices"}
        or document["mode"] != "synthetic_only"
        or document["result"] != "reserved_in_simulator"
        or type(document["notices"]) is not int
        or document["notices"] != 1
    ):
        raise ValueError("invalid synthetic browser outcome")
    return True


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) != 1:
            raise ValueError("exactly one receipt path required")
        path = Path(arguments[0])
        if path.stat().st_size > 256:
            raise ValueError("oversized synthetic browser receipt")
        if validate_receipt(path.read_text(encoding="ascii")):
            print("BOCA_CHROMIUM_SYNTHETIC state=PASS mode=offline_only notices=1")
            return 0
    except (OSError, ValueError, UnicodeError):
        pass
    print("BOCA_CHROMIUM_SYNTHETIC state=NO_GO", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
