"""Verify the exact R96 #844 stage-remediation triplet under Python -O.

Reuse the existing fail-closed, typed GitHub run verifier; never authenticate
remote evidence with Python assertions that PYTHONOPTIMIZE can disable.
"""

from __future__ import annotations

import sys

from scripts.check_worker_recovery_dispatch import _read_json, _run

PREPARE = 42381545964
INCIDENT = 42388694186
READONLY = 42388994569
SOURCE = "e3cbd38856a2aa75e9ec5e276335da0be6ed520b"
WORKFLOW = ".github/workflows/boca-first-deploy.yml"


def verify_triplet(observed: object, failed: object, prepared: object) -> None:
    """Reject substitutions, unresolved runs and non-first workflow attempts."""
    if len({PREPARE, INCIDENT, READONLY}) != 3:
        raise ValueError("R96 triplet contains duplicate run IDs")
    _run(observed, number=READONLY, source=SOURCE, conclusion="success", workflow=WORKFLOW)
    _run(failed, number=INCIDENT, source=SOURCE, conclusion="failure", workflow=WORKFLOW)
    _run(prepared, number=PREPARE, source=SOURCE, conclusion="success", workflow=WORKFLOW)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 6 or args[3:] != [str(INCIDENT), str(PREPARE), str(READONLY)]:
        print("BOCA_REMEDIATION_GATE state=NO_GO reason=INPUT", file=sys.stderr)
        return 2
    try:
        observed, failed, prepared = (_read_json(path) for path in args[:3])
        verify_triplet(observed, failed, prepared)
    except (OSError, ValueError, TypeError) as exc:
        print(f"BOCA_REMEDIATION_GATE state=NO_GO reason={type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        "BOCA_REMEDIATION_GATE state=PASS"
        f" incident={INCIDENT} prepare={PREPARE} readonly={READONLY}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
