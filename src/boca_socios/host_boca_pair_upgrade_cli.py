"""R179 fixed-argument entrypoint and canonical redacted Actions receipts.

No Docker output, exception text, host paths, session data or raw SQLite inode
is printable. Both modes run only from an SHA-verified protected memfd bundle
in the owner rootless namespace; the Action independently authenticates
main, release and role-specific GHCR immutable image manifests before APPLY.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from boca_socios import host_boca_pair_upgrade as upgrade
    from boca_socios.host_boca_successor_integrations import BoundSuccessorInputs

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


@dataclass(frozen=True, slots=True)
class BoundSuccessorPreflight:
    """Validated runner-bound coordinates and inert reviewed stage bytes.

    The protected memfd/bootstrap independently pins these bytes to main.
    This object has no original installed Compose digest, lease, journal,
    Docker interface or authority to install a successor pair.
    """

    inputs: BoundSuccessorInputs
    base: bytes
    overlay: bytes
    seccomp: bytes
    base_sha: str
    overlay_sha: str
    seccomp_sha: str

    def __post_init__(self) -> None:
        # The result is a public Python value, not a capability. Revalidate
        # its frozen local digests even if constructed outside the CLI.
        from boca_socios import host_cutover_stage as guarded
        from boca_socios.host_boca_successor_integrations import BoundSuccessorInputs

        values = (self.base, self.overlay, self.seccomp)
        hashes = (self.base_sha, self.overlay_sha, self.seccomp_sha)
        if (
            type(self.inputs) is not BoundSuccessorInputs
            or self.inputs.apply_authorized is not False
            or any(
                type(data) is not bytes or not 0 < len(data) <= guarded.MAX_FILE for data in values
            )
            or any(
                type(digest) is not str or hashlib.sha256(data).hexdigest() != digest
                for data, digest in zip(values, hashes, strict=True)
            )
            or len(set(hashes)) != 3
        ):
            raise SuccessorPreflightIneligible("Boca successor stage transport unverified")

    @property
    def apply_authorized(self) -> Literal[False]:
        return False


def _successor_preflight(
    run: str,
    source: str,
    controller: str,
    worker: str,
    release_run: str,
    observation_run: str | None,
    retained_observation_run: str | None,
) -> BoundSuccessorPreflight:
    """Bind the protected runner payload, never retry historical R179.

    Returning typed transport and exact stage bytes alone grants no effect.
    The protected CLI must still enter the reviewed same-lease graph, which
    alone can attest physical identities, cleanup V2 and durable postflight.
    """
    from boca_socios.host_boca_successor_integrations import verify_runner_bound_host_inputs
    from boca_socios.host_boca_upgrade_retained_bridge import verify_bundled_retained

    if (
        not _run_id(run)
        or observation_run is None
        or not _run_id(observation_run)
        or retained_observation_run is None
        or not _run_id(retained_observation_run)
        or not re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", sys.argv[0])
    ):
        raise SuccessorPreflightIneligible("Boca successor protected memfd missing")
    try:
        with zipfile.ZipFile(sys.argv[0]) as archive:
            proof = archive.read("release/runner-proof.json")
            controller_manifest = archive.read("release/boca-release-manifest.json")
            paired_manifest = archive.read("release/boca-browser-release-manifest.json")
            observation_proof = archive.read("release/observation-proof.json")
            observation_receipt = archive.read("release/boca-pair-observation.receipt")
            retained_proof = archive.read("release/retained-proof.json")
            retained_receipt = archive.read("release/boca-retained-observation.receipt")
            current_v2 = archive.read("release/current-pair-v2.receipt")
            base = archive.read("compose.beta.yaml")
            overlay = archive.read("compose.beta.browser.yaml")
            seccomp = archive.read("docker/seccomp_profile.json")
        base_sha, overlay_sha, seccomp_sha = (
            hashlib.sha256(data).hexdigest() for data in (base, overlay, seccomp)
        )
        bound = verify_runner_bound_host_inputs(
            attempt_id=run,
            source_sha=source,
            controller_ref=controller,
            worker_ref=worker,
            release_run_id=release_run,
            observation_run_id=observation_run,
            release_proof=proof,
            controller_manifest=controller_manifest,
            paired_manifest=paired_manifest,
            observation_proof=observation_proof,
            observation_receipt=observation_receipt,
            retained_receipt=retained_receipt,
            current_pair_v2=current_v2,
        )
        # A V1 proof only applies when R188's installed pair is still the
        # currently observed one. After a successor B -> C, R188 is purely an
        # original resource-creator seed, not a proof of the *current* CIDs.
        # A reviewed runner instead bundles the independently authenticated
        # current-pair V2 envelope and this exact disabled legacy sentinel.
        if retained_proof != b'{"state":"NO_GO"}\n':
            verify_bundled_retained(
                retained_proof,
                retained_receipt,
                observation_proof,
                observation_receipt,
                source,
                retained_observation_run,
                observation_run,
                run,
                release_run,
            )
        historical_run = bound.custody.observation_run_id
        if historical_run != retained_observation_run:
            raise SuccessorPreflightIneligible("Boca successor R188 seed run mismatched")
        return BoundSuccessorPreflight(
            bound, base, overlay, seccomp, base_sha, overlay_sha, seccomp_sha
        )
    except Exception:
        raise SuccessorPreflightIneligible("Boca successor release transport unverified") from None


def _execute_reviewed_successor(preflight: BoundSuccessorPreflight) -> upgrade.PairUpgradeReceipt:
    """Execute the reviewed successor under exactly one protected lease.

    The caller must have authenticated the cold-URL, rootless subuid and
    protected ZIP preflight. ``run_pair_upgrade`` owns the lease and invokes
    ``backend_factory`` only after durable journal intent. No historical
    R179 actor is constructed here. Exceptions from this function may follow
    irreversible effects and must never be called a pre-effect refusal.
    """
    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios import host_boca_guarded_successor_backend_v4 as guarded
    from boca_socios import host_boca_pair_upgrade as upgrade
    from boca_socios import host_boca_successor_assembly_v3 as assembly
    from boca_socios import host_boca_technical_terminal_bridge_v3 as terminal

    if type(preflight) is not BoundSuccessorPreflight:
        raise SuccessorPreflightIneligible("Boca reviewed successor preflight missing")
    try:
        preflight.__post_init__()
        graph = assembly.prepare_inert_same_lease(preflight)
        witness = terminal.OneShotTechnicalTerminalBridge(graph)
        factory_called = False

        def only_after_intent(
            plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease
        ) -> guarded.GuardedTechnicalSuccessorBackend:
            nonlocal factory_called
            if factory_called or plan is not graph.plan:
                raise SuccessorPreflightIneligible("Boca successor factory replay/mismatch")
            # The engine calls this with its held lease only after
            # graph.stage.intent persisted the original evidence O_EXCL.
            factory_called = True
            return guarded.GuardedTechnicalSuccessorBackend(graph, witness, lease)

        outcome = upgrade.run_pair_upgrade(
            graph.plan,
            backend_factory=only_after_intent,
            terminal_preflight=graph.stage.intent,
            commit_marker=graph.journal.commit,
            terminal_sink=witness,
        )
        if (
            type(outcome) is not upgrade.PairUpgradeReceipt
            or outcome.attempt_id != graph.plan.attempt_id
        ):
            raise SuccessorPreflightIneligible("Boca successor terminal unverified")
        encoded = encode_upgrade(outcome)
        # A future protected caller must never report an engine-level
        # ACCEPTED without the exact independently re-read O_EXCL SUCCESS
        # terminal. An in-memory receipt or cleanup text is insufficient.
        technical = witness.technical_terminal
        if outcome.accepted:
            if (
                type(technical) is not terminal.TechnicalTerminalEvidence
                or technical.attempt_id != graph.plan.attempt_id
                or technical.raw != encoded
                or technical.sha256 != hashlib.sha256(encoded).hexdigest()
                or technical.terminal_state != "TECHNICAL_ACCEPTED_OWNER_PENDING"
                or technical.beta_deploy != "NO_GO"
                or technical.passkey_attested is not False
            ):
                raise SuccessorPreflightIneligible("Boca successor durable terminal missing")
        elif technical is not None:
            raise SuccessorPreflightIneligible("Boca successor contradictory terminal")
        return outcome
    except Exception:
        raise SuccessorPreflightIneligible("Boca successor same-lease proof incomplete") from None


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
    if len(args) in (6, 7, 8) and args[0] == "apply" and _run_id(args[1]):
        # The historical one-shot R179 actor is never entered again. The
        # read-only preflight and the potentially effectful successor have
        # separate error boundaries: after entry, commit may be irreversible.
        from boca_socios import host_boca_pair_upgrade as upgrade

        try:
            preflight = _successor_preflight(
                args[1],
                args[2],
                args[3],
                args[4],
                args[5],
                args[6] if len(args) >= 7 else None,
                args[7] if len(args) == 8 else None,
            )
            if type(preflight) is not BoundSuccessorPreflight:
                raise SuccessorPreflightIneligible("Boca successor transport not typed")
            preflight.__post_init__()
        except Exception:
            # ONLY errors preceding the actor/lease can prove no host effect.
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
            sys.stdout.buffer.write(raw) if argv is None else print(raw.decode("ascii"), end="")
            return 3
        try:
            outcome = _execute_reviewed_successor(preflight)
            if type(outcome) is not upgrade.PairUpgradeReceipt or outcome.attempt_id != args[1]:
                raise SuccessorPreflightIneligible("Boca successor outcome not bound")
            raw = encode_upgrade(outcome)
        except BaseException:
            # An exception can occur after STAGE, PARK, COMMIT, retirement,
            # durable terminal write or lease release. No synthetic canonical
            # NO_GO with commit_started=False is truthful at this point.
            uncertain = (
                b"BOCA_PAIR_UPGRADE state=INDETERMINATE reason=POST_ENTRY_UNVERIFIED "
                b"action=READ_ONLY_RCA_NO_AUTOMATIC_RETRY\n"
            )
            sys.stdout.buffer.write(uncertain) if argv is None else print(
                uncertain.decode("ascii"), end=""
            )
            return 3
        sys.stdout.buffer.write(raw) if argv is None else print(raw.decode("ascii"), end="")
        return 0 if outcome.accepted else 3
    return 3


if __name__ == "__main__":  # pragma: no cover - protected memfd ZIP executes this entrypoint
    raise SystemExit(main())
