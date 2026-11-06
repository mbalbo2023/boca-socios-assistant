"""Offline two-SHA release lineage gate for future protected Telegram GO_B.

The reviewed workflow source may advance after the *same* immutable BETA
image was published. The two hashes must be independently authenticated:

* workflow SHA is the current main HEAD checked with check_main_ref.py;
* image source SHA is the exact signed controller+browser release provenance;
* this parser verifies a bounded projection of GitHub's compare API, proving
  that the image source remains an ancestor of the current workflow source.

This module never visits GitHub itself, executes Docker, opens SSH, reads
tokens or grants Telegram GO. A forged JSON file is not a protected receipt.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_BYTES = 512


class TelegramLineageNoGo(ValueError):
    """Static error class: never echo untrusted JSON or private values."""


@dataclass(frozen=True, slots=True)
class TelegramDualSourceReceipt:
    """Source ancestry only, no authorization and no physical host claim."""

    image_source_sha: str
    workflow_sha: str
    state: str = "ANCESTRY_OBSERVED_NO_GO"
    independent_go_b: bool = False
    host_effects: bool = False
    sender_state: str = "OFF"


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TelegramLineageNoGo("telegram_source_lineage_json_invalid")
        result[key] = value
    return result


def verify_dual_source_lineage(
    *, image_source_sha: str, workflow_sha: str, compare_json: bytes
) -> TelegramDualSourceReceipt:
    """Validate canonical, redacted compare API response without granting GO."""
    try:
        if (
            type(image_source_sha) is not str
            or _SHA.fullmatch(image_source_sha) is None
            or type(workflow_sha) is not str
            or _SHA.fullmatch(workflow_sha) is None
            or type(compare_json) is not bytes
            or not 2 <= len(compare_json) <= _MAX_BYTES
        ):
            raise ValueError("unreviewed SHA/compare")
        parsed = json.loads(compare_json.decode("ascii"), object_pairs_hook=_unique)
        if (
            type(parsed) is not dict
            or set(parsed) != {"status", "ahead_by", "behind_by", "base_sha", "merge_base_sha"}
            or json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "ascii"
            )
            != compare_json
            or type(parsed["ahead_by"]) is not int
            or type(parsed["behind_by"]) is not int
            or not 0 <= parsed["ahead_by"] <= 100_000
            or parsed["behind_by"] != 0
            or parsed["base_sha"] != image_source_sha
            or parsed["merge_base_sha"] != image_source_sha
        ):
            raise ValueError("untrusted ancestry")
        if image_source_sha == workflow_sha:
            if parsed["status"] != "identical" or parsed["ahead_by"] != 0:
                raise ValueError("identical source drift")
        elif parsed["status"] != "ahead" or parsed["ahead_by"] < 1:
            raise ValueError("workflow source not descendant")
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise TelegramLineageNoGo("telegram_source_lineage_unverified") from None
    return TelegramDualSourceReceipt(image_source_sha, workflow_sha)


def main(args: list[str] | None = None) -> int:
    """Runner-only CLI: source hashes and reduced GitHub API file; no network."""
    values = sys.argv[1:] if args is None else args
    if len(values) != 3:
        print("BOCA_TELEGRAM_LINEAGE state=NO_GO reason=invalid_arguments sender=OFF")
        return 2
    try:
        candidate = Path(values[2])
        if not candidate.is_absolute() or candidate.is_symlink() or not candidate.is_file():
            raise ValueError("compare path")
        actual = candidate.read_bytes()
        # `jq -cS` emits exactly one terminal LF; normalize only that frame
        # byte, leaving the canonical JSON body unchanged and bounded.
        if actual.endswith(b"\n"):
            actual = actual[:-1]
        receipt = verify_dual_source_lineage(
            image_source_sha=values[0], workflow_sha=values[1], compare_json=actual
        )
        if receipt.independent_go_b or receipt.host_effects or receipt.sender_state != "OFF":
            raise ValueError("invalid nonauthorizing receipt")
    except (OSError, ValueError):
        print("BOCA_TELEGRAM_LINEAGE state=NO_GO reason=unverified sender=OFF")
        return 1
    print("BOCA_TELEGRAM_LINEAGE state=ANCESTRY_OBSERVED_NO_GO host=untouched sender=OFF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
