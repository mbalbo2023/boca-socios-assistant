"""R179 fixed-argument entrypoint and canonical redacted Actions receipts.

No Docker output, exception text, host paths, session data or raw SQLite inode
is printable. Both modes run only from an SHA-verified protected memfd bundle
in the owner rootless namespace; the Action independently authenticates
main, release and role-specific GHCR immutable image manifests before APPLY.
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, get_args

if TYPE_CHECKING:
    from boca_socios import host_boca_pair_upgrade as upgrade

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SQLITE_PREFIX = b"BOCA_SQLITE_IDENTITY "
_UPGRADE_PREFIX = b"BOCA_PAIR_UPGRADE "
_MAX_LINE = 1024
_SQLITE_FIELDS = frozenset(
    {
        "schema",
        "attempt_id",
        "state",
        "observer_writes",
        "foreign_resources_touched",
        "cutover_authorized",
    }
)
_UPGRADE_FIELDS = frozenset(
    {
        "schema",
        "attempt_id",
        "state",
        "cleanup",
        "old_restored",
        "commit_started",
        "controller_id",
        "worker_id",
        "failed_phase",
    }
)


class PairUpgradeCliError(ValueError):
    """An untrusted or contaminated protected runner receipt."""


class SuccessorPreflightIneligible(PairUpgradeCliError):
    """No host operation has begun; successor adapter remains interlocked."""


def _successor_preflight(
    run: str, source: str, controller: str, worker: str, release_run: str
) -> None:
    """Validate the protected runner payload, never retry historical R179.

    Activation requires a future reviewed wiring of protected same-lease
    witness/cleanup V2. This route is intentionally PRE-EFFECT NO_GO even with
    genuine release manifests, until those contracts can be proven end to end.
    """
    from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
    from boca_socios.host_boca_upgrade_release_bridge import verify_bundled_release

    if not _run_id(run) or not re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", sys.argv[0]):
        raise SuccessorPreflightIneligible("Boca successor protected memfd missing")
    try:
        with zipfile.ZipFile(sys.argv[0]) as archive:
            proof = archive.read("release/runner-proof.json")
            controller_manifest = archive.read("release/boca-release-manifest.json")
            paired_manifest = archive.read("release/boca-browser-release-manifest.json")
        verify_bundled_release(
            proof,
            controller_manifest,
            paired_manifest,
            CandidateRelease(source, release_run, controller, worker),
        )
    except Exception:
        raise SuccessorPreflightIneligible("Boca successor release transport unverified") from None
    # Neither a verified release nor a historical R189 summary supplies
    # an installed-pair graph, an authenticated observation run, or an
    # effectful stage/archive/R108 cleanup with same-lease durable receipt.
    raise SuccessorPreflightIneligible("Boca successor transaction remains ineligible")


def _run_id(value: object) -> bool:
    return type(value) is str and _RUN.fullmatch(value) is not None


def _canonical(prefix: bytes, item: dict[str, object]) -> bytes:
    return prefix + json.dumps(item, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise PairUpgradeCliError("duplicate Boca receipt key")
        output[key] = value
    return output


def _payload(raw: bytes, prefix: bytes, attempt: str, fields: frozenset[str]) -> dict[str, object]:
    if (
        not _run_id(attempt)
        or type(raw) is not bytes
        or not 0 < len(raw) <= _MAX_LINE
        or not raw.startswith(prefix)
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
    ):
        raise PairUpgradeCliError("Boca receipt boundary invalid")
    try:
        data = json.loads(raw[len(prefix) :], object_pairs_hook=_unique)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PairUpgradeCliError("Boca receipt is not canonical JSON") from exc
    if (
        not isinstance(data, dict)
        or data.keys() != fields
        or data.get("schema") != 1
        or type(data["schema"]) is not int
        or data.get("attempt_id") != attempt
        or _canonical(prefix, data) != raw
    ):
        raise PairUpgradeCliError("Boca receipt shape or attempt mismatch")
    return data


def encode_sqlite(run_id: str, state: str) -> bytes:
    if not _run_id(run_id) or state not in ("VERIFIED_STABLE", "NO_GO"):
        raise PairUpgradeCliError("Boca SQLite witness category invalid")
    return _canonical(
        _SQLITE_PREFIX,
        {
            "schema": 1,
            "attempt_id": run_id,
            "state": state,
            "observer_writes": 0,
            "foreign_resources_touched": 0,
            "cutover_authorized": False,
        },
    )


def verify_sqlite(raw: bytes, run_id: str) -> bytes:
    value = _payload(raw, _SQLITE_PREFIX, run_id, _SQLITE_FIELDS)
    if (
        value["state"] not in ("VERIFIED_STABLE", "NO_GO")
        or type(value["observer_writes"]) is not int
        or value["observer_writes"] != 0
        or type(value["foreign_resources_touched"]) is not int
        or value["foreign_resources_touched"] != 0
        or value["cutover_authorized"] is not False
    ):
        raise PairUpgradeCliError("Boca SQLite observer cannot authorize effects")
    return raw


def _upgrade_fields_ok(value: dict[str, object]) -> bool:
    from boca_socios import host_boca_pair_upgrade as upgrade

    state, cleanup = value["state"], value["cleanup"]
    restored, committed = value["old_restored"], value["commit_started"]
    controller, worker = value["controller_id"], value["worker_id"]
    if (
        state not in ("ACCEPTED", "RECOVERED", "NO_GO")
        or cleanup not in ("ACCEPT", "NO_GO", "INDETERMINATE")
        or type(restored) is not bool
        or type(committed) is not bool
        or restored
        and committed
        or value["failed_phase"] not in get_args(upgrade.PairPhase)
        or any(
            item is not None and (type(item) is not str or _HEX.fullmatch(item) is None)
            for item in (controller, worker)
        )
        or controller is not None
        and controller == worker
        or (state == "ACCEPTED")
        != (cleanup == "ACCEPT" and committed and not restored and value["failed_phase"] == "NONE")
        or state == "RECOVERED"
        and not (cleanup == "ACCEPT" and restored and not committed)
        or state == "NO_GO"
        and restored
        and cleanup == "ACCEPT"
        or state == "ACCEPTED"
        and (controller is None or worker is None)
    ):
        return False
    return True


def encode_upgrade(receipt: upgrade.PairUpgradeReceipt) -> bytes:
    from boca_socios import host_boca_pair_upgrade as upgrade

    if type(receipt) is not upgrade.PairUpgradeReceipt or not _run_id(receipt.attempt_id):
        raise PairUpgradeCliError("Boca pair terminal object invalid")
    value: dict[str, object] = {"schema": 1, **asdict(receipt)}
    if not _upgrade_fields_ok(value):
        raise PairUpgradeCliError("Boca pair terminal state incoherent")
    raw = _canonical(_UPGRADE_PREFIX, value)
    verify_upgrade(raw, receipt.attempt_id)
    return raw


def verify_upgrade(raw: bytes, run_id: str) -> bytes:
    value = _payload(raw, _UPGRADE_PREFIX, run_id, _UPGRADE_FIELDS)
    if not _upgrade_fields_ok(value):
        raise PairUpgradeCliError("Boca pair terminal cannot prove acceptance")
    return raw


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] in ("verify-sqlite", "verify-upgrade") and _run_id(args[1]):
        # Runner parses a SINGLE bounded line; neither mode touches the host.
        try:
            raw = sys.stdin.buffer.read(_MAX_LINE + 1)
            if args[0] == "verify-sqlite":
                verify_sqlite(raw, args[1])
            else:
                verify_upgrade(raw, args[1])
        except (PairUpgradeCliError, OSError, UnicodeError):
            return 3
        sys.stdout.buffer.write(raw)
        return 0
    if len(args) == 2 and args[0] == "observe-sqlite" and _run_id(args[1]):
        from boca_socios import host_boca_sqlite_identity as sqlite
        from boca_socios import host_first_deploy as host

        state = "NO_GO"
        try:
            if (
                sqlite.observe_sqlite_identity(host._checked_docker_storage_dir())
                == "VERIFIED_STABLE"
            ):
                state = "VERIFIED_STABLE"
        except Exception:
            state = "NO_GO"  # Fixed public category, never a host/private traceback.
        sys.stdout.buffer.write(encode_sqlite(args[1], state)) if argv is None else print(
            encode_sqlite(args[1], state).decode("ascii"), end=""
        )
        return 0 if state == "VERIFIED_STABLE" else 3
    if len(args) == 6 and args[0] == "apply" and _run_id(args[1]):
        # Existing single protected APPLY selector now goes exclusively to
        # the successor preflight; the historical one-shot EXIT1 backend is
        # never executed again, even when four form pins look plausible.
        from boca_socios import host_boca_pair_upgrade as upgrade

        try:
            _successor_preflight(args[1], args[2], args[3], args[4], args[5])
            raise SuccessorPreflightIneligible("Boca successor lacks activated cleanup receipt")
        except SuccessorPreflightIneligible:
            raw = encode_upgrade(
                upgrade.PairUpgradeReceipt(
                    attempt_id=args[1],
                    state="NO_GO",
                    cleanup="INDETERMINATE",
                    old_restored=False,
                    commit_started=False,
                    controller_id=None,
                    worker_id=None,
                    failed_phase="ATTEST",
                )
            )
        except Exception:
            # Any unknown exception remains indeterminate, never ACCEPT.
            # Future activation must preserve post-marker uncertainty here.
            refused = upgrade.PairUpgradeReceipt(
                attempt_id=args[1],
                state="NO_GO",
                cleanup="INDETERMINATE",
                old_restored=False,
                commit_started=True,
                controller_id=None,
                worker_id=None,
                failed_phase="COMMIT_MARKER",
            )
            raw = encode_upgrade(refused)
        sys.stdout.buffer.write(raw) if argv is None else print(raw.decode("ascii"), end="")
        return 0 if b'"state":"ACCEPTED"' in raw else 3
    return 3


if __name__ == "__main__":  # pragma: no cover - protected memfd ZIP executes this entrypoint
    raise SystemExit(main())
