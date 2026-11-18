"""Forensic READ_ONLY observer for fixed Boca #1241/#1251; NEVER replays APPLY.

The host ZIP contains only this stdlib module and the existing inert stage
openat helpers. Its stdout is a PRIVATE binary frame sent through the pinned
Boca SSH pipe to a runner-only 0600 file, never a log or public receipt.
Canonical terminal verification happens ONLY in the full runner checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from typing import Any

from boca_socios import host_cutover_stage as stage

INCIDENT = "44315372494"
G16_SOURCE = "75b00d8e1cd903d3d727a2628134a27fd740fc42"
G17_SOURCE = "7f20bf0acf43b2e17812bfc35efc86a552b5a404"
RELEASE_RUN = "44313076076"

# The original G17 #1241 coordinates remain frozen. G18 #1251 has a
# separate fixed frame/profile, sharing this *same* inert stage reader.
INCIDENT_1251 = "44352430452"
OLD_SOURCE_1251 = G17_SOURCE
NEW_SOURCE_1251 = "dbd3f1c494c341c980625da3660e10cc28fa8446"
RELEASE_RUN_1251 = "44348462224"

_PREFIX = f".boca-pair-upgrade-{INCIDENT}."
_PREFIX_1251 = f".boca-pair-upgrade-{INCIDENT_1251}."
_LIMITS = {
    "evidence": 4096,
    "intent": 1024,
    "commit": 64,
    "technical-postflight-v2": 8192,
    "terminal": 1024,
}
_MAGIC = b"BOCA_G17_1241_PRIVATE_V1\x00"
_MAGIC_1251 = b"BOCA_G18_1251_PRIVATE_V1\x00"
_TERMINAL_PREFIX = b"BOCA_PAIR_UPGRADE "
_TECHNICAL_PREFIX = b"BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2 "
_FRAME_LIMIT = 4096
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_CID = re.compile(r"[a-f0-9]{64}\Z")


class IncidentNoGo(ValueError):
    """Finite, redacted classification, never a host exception or private path."""


def _reject(reason: str = "MARKER_UNVERIFIED") -> IncidentNoGo:
    return IncidentNoGo(reason)


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return (
        a.st_dev,
        a.st_ino,
        a.st_mode,
        a.st_uid,
        a.st_gid,
        a.st_nlink,
        a.st_size,
        a.st_mtime_ns,
        a.st_ctime_ns,
    ) == (
        b.st_dev,
        b.st_ino,
        b.st_mode,
        b.st_uid,
        b.st_gid,
        b.st_nlink,
        b.st_size,
        b.st_mtime_ns,
        b.st_ctime_ns,
    )


def _stable_dir(fd: int, before: os.stat_result) -> None:
    """Bind the named Boca directory to its original protected directory fd."""
    try:
        current = os.stat(stage.ROOT, follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or not _same(before, current):
            raise _reject("DIRECTORY_DRIFT")
        if not _same(before, os.fstat(fd)):
            raise _reject("DIRECTORY_DRIFT")
    except OSError:
        raise _reject("DIRECTORY_DRIFT") from None


def _read_snapshot(prefix: str = _PREFIX) -> dict[str, tuple[bytes, os.stat_result] | None]:
    try:
        fd = stage._root_fd()
    except (OSError, stage.StageError):
        raise _reject("HOST_IDENTITY_UNVERIFIED") from None
    try:
        directory = stage._checked_dir(fd)
        _stable_dir(fd, directory)
        first: dict[str, tuple[bytes, os.stat_result] | None] | None = None
        for _ in range(2):
            seen: dict[str, tuple[bytes, os.stat_result] | None] = {}
            for suffix, limit in _LIMITS.items():
                name = prefix + suffix
                try:
                    named_before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    seen[suffix] = None
                    continue
                except OSError:
                    raise _reject() from None
                if not stat.S_ISREG(named_before.st_mode):
                    raise _reject()
                try:
                    raw, inode = stage._read_file(fd, name, None, limit=limit)
                    named_after = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except (OSError, stage.StageError):
                    raise _reject() from None
                if not _same(named_before, inode) or not _same(named_after, inode):
                    raise _reject("DOUBLE_READ_DRIFT")
                seen[suffix] = (raw, inode)
            _stable_dir(fd, directory)
            if first is None:
                first = seen
            elif any(
                (a is None) != (b is None)
                or a is not None
                and b is not None
                and (a[0] != b[0] or not _same(a[1], b[1]))
                for a, b in zip(first.values(), seen.values(), strict=True)
            ):
                raise _reject("DOUBLE_READ_DRIFT")
        if first is None:
            raise _reject()
        return first
    finally:
        os.close(fd)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise _reject()
        result[name] = value
    return result


def _json(raw: bytes, prefix: bytes = b"", *, newline: bool = False) -> dict[str, Any]:
    if not raw.startswith(prefix):
        raise _reject()
    data = raw[len(prefix) :]
    if newline:
        if not data.endswith(b"\n") or data.count(b"\n") != 1:
            raise _reject()
        data = data[:-1]
    try:
        value = json.loads(
            data,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(_reject()),
        )
        if type(value) is not dict or _canonical(value) != data:
            raise _reject()
        return value
    except (TypeError, ValueError, UnicodeError):
        raise _reject() from None


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise _reject() from None


def _cid(value: object) -> bool:
    return type(value) is str and _CID.fullmatch(value) is not None


def _check_markers(values: dict[str, bytes]) -> tuple[str, str]:
    """Validate journal/source/technical relations; do NOT parse terminal states."""
    evidence = _json(values["evidence"])
    intent = _json(values["intent"])
    proof = _json(values["technical-postflight-v2"], _TECHNICAL_PREFIX, newline=True)
    plan, witness, release = (
        evidence.get("plan"),
        evidence.get("witness"),
        evidence.get("release"),
    )
    if (
        evidence.get("version") != "boca-successor-pair-intent-evidence-v1"
        or set(evidence) != {"version", "plan", "release", "witness"}
        or type(plan) is not dict
        or type(witness) is not dict
        or type(release) is not dict
        or type(intent) is not dict
        or set(plan)
        != {
            "attempt_id",
            "observation_run_id",
            "old_attempt_id",
            "old_source_sha",
            "old_controller_id",
            "old_worker_id",
            "old_controller_image_id",
            "old_worker_image_id",
            "new_source_sha",
            "release_run_id",
            "controller_ref",
            "worker_ref",
        }
        or set(release)
        != {
            "source_sha",
            "release_run_id",
            "controller_ref",
            "worker_ref",
            "controller_manifest_sha256",
            "paired_manifest_sha256",
        }
        or set(witness)
        != {
            "observation_run_id",
            "old_attempt_id",
            "old_source_sha",
            "controller_id",
            "worker_id",
            "controller_image_id",
            "worker_image_id",
            "control_inode_sha256",
            "retained",
        }
        or set(intent)
        != {
            "attempt",
            "evidence_sha256",
            "old_controller",
            "old_worker",
            "old_source",
            "new_source",
            "release",
        }
        or (
            plan.get("attempt_id"),
            plan.get("old_source_sha"),
            plan.get("new_source_sha"),
            plan.get("release_run_id"),
        )
        != (INCIDENT, G16_SOURCE, G17_SOURCE, RELEASE_RUN)
        or (
            intent.get("attempt"),
            intent.get("old_source"),
            intent.get("new_source"),
            intent.get("release"),
        )
        != (INCIDENT, G16_SOURCE, G17_SOURCE, RELEASE_RUN)
        or intent.get("evidence_sha256") != hashlib.sha256(values["evidence"]).hexdigest()
        or values["commit"] != hashlib.sha256(values["intent"]).hexdigest().encode("ascii")
        or (
            release.get("source_sha"),
            release.get("release_run_id"),
            release.get("controller_ref"),
            release.get("worker_ref"),
        )
        != (G17_SOURCE, RELEASE_RUN, plan.get("controller_ref"), plan.get("worker_ref"))
        or (
            witness.get("old_source_sha"),
            witness.get("controller_id"),
            witness.get("worker_id"),
            witness.get("observation_run_id"),
            witness.get("old_attempt_id"),
        )
        != (
            G16_SOURCE,
            plan.get("old_controller_id"),
            plan.get("old_worker_id"),
            plan.get("observation_run_id"),
            plan.get("old_attempt_id"),
        )
        or intent.get("old_controller") != plan.get("old_controller_id")
        or intent.get("old_worker") != plan.get("old_worker_id")
        or witness.get("controller_image_id") != plan.get("old_controller_image_id")
        or witness.get("worker_image_id") != plan.get("old_worker_image_id")
        or not _cid(witness.get("control_inode_sha256"))
        or stage.CONTROLLER.fullmatch(str(plan.get("controller_ref"))) is None
        or stage.WORKER.fullmatch(str(plan.get("worker_ref"))) is None
        or not all(_cid(value) for value in (intent["old_controller"], intent["old_worker"]))
        or proof.get("schema") != 2
        or type(proof.get("schema")) is not int
        or proof.get("state") != "TECHNICAL_PROOF_ONLY"
        or (
            proof.get("attempt_id"),
            proof.get("source_sha"),
            proof.get("release_run_id"),
        )
        != (INCIDENT, G17_SOURCE, RELEASE_RUN)
        or proof.get("controller_manifest_sha256") != release.get("controller_manifest_sha256")
        or proof.get("paired_manifest_sha256") != release.get("paired_manifest_sha256")
        or any(
            not _cid(value)
            for value in (
                release.get("controller_manifest_sha256"),
                release.get("paired_manifest_sha256"),
            )
        )
        or proof.get("rootless_uid") != 10001
        or proof.get("rootless_gid") != 10001
        or proof.get("beta_deploy") != "NO_GO"
        or type(proof.get("observer_writes")) is not int
        or proof.get("observer_writes") != 0
        or type(proof.get("foreign_resources_touched")) is not int
        or proof.get("foreign_resources_touched") != 0
        or proof.get("passkey_chrome") != "NOT_ATTESTED"
    ):
        raise _reject()
    pair, binding = proof.get("pair"), proof.get("binding")
    if type(pair) is not dict or type(binding) is not dict:
        raise _reject()
    panel, cleanup = proof.get("panel"), proof.get("cleanup")
    if (
        type(panel) is not dict
        or panel.get("origin") != "http://localhost:8443"
        or panel.get("probe") != "HEALTH_HTTP_200"
        or panel.get("scope") != "LOOPBACK_HEALTH_ONLY"
        or type(cleanup) is not dict
        or cleanup.get("status") != "ACCEPT"
        or cleanup.get("r108") != "RETAINED_ATTESTED"
        or not _cid(cleanup.get("sha256"))
    ):
        raise _reject()
    services = pair.get("services")
    if (
        pair.get("attempt_id") != INCIDENT
        or pair.get("source_sha") != G17_SOURCE
        or type(services) is not list
        or len(services) != 2
        or any(type(service) is not dict for service in services)
        or (
            binding.get("installation_attempt"),
            binding.get("source_sha"),
            binding.get("controller_image_ref"),
            binding.get("worker_image_ref"),
        )
        != (INCIDENT, G17_SOURCE, plan.get("controller_ref"), plan.get("worker_ref"))
    ):
        raise _reject()
    controller, worker = binding.get("controller_id"), binding.get("worker_id")
    if (
        not _cid(controller)
        or not _cid(worker)
        or controller == worker
        or services[0].get("container_id") != controller
        or services[1].get("container_id") != worker
        or len({intent["old_controller"], intent["old_worker"], controller, worker}) != 4
    ):
        raise _reject()
    terminal = values["terminal"]
    if (
        not terminal.startswith(_TERMINAL_PREFIX)
        or not terminal.endswith(b"\n")
        or terminal.count(b"\n") != 1
    ):
        raise _reject()
    return controller, worker


def _frame(metadata: dict[str, object], terminal: bytes = b"", *, magic: bytes = _MAGIC) -> bytes:
    raw = _canonical(metadata)
    if len(raw) > 2048 or len(terminal) > 1024:
        raise _reject("FRAME_UNVERIFIED")
    packet = magic + len(raw).to_bytes(2, "big") + len(terminal).to_bytes(2, "big") + raw + terminal
    finished = packet + hashlib.sha256(packet).digest()
    if len(finished) > _FRAME_LIMIT:
        raise _reject("FRAME_UNVERIFIED")
    return finished


def _unframe(raw: bytes, observation_run: str, magic: bytes) -> tuple[dict[str, Any], bytes]:
    """Same bounded private-frame decoder for either immutable incident."""
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= _FRAME_LIMIT
        or not raw.startswith(magic)
        or len(raw) < len(magic) + 4 + 32
        or _RUN.fullmatch(observation_run) is None
    ):
        raise _reject("FRAME_UNVERIFIED")
    at = len(magic)
    json_length = int.from_bytes(raw[at : at + 2], "big")
    terminal_length = int.from_bytes(raw[at + 2 : at + 4], "big")
    if json_length > 2048 or terminal_length > 1024:
        raise _reject("FRAME_UNVERIFIED")
    if (
        len(raw) != at + 4 + json_length + terminal_length + 32
        or hashlib.sha256(raw[:-32]).digest() != raw[-32:]
    ):
        raise _reject("FRAME_UNVERIFIED")
    return _json(raw[at + 4 : at + 4 + json_length]), raw[at + 4 + json_length : -32]


def _precommit_evidence_1251(raw: bytes) -> dict[str, Any]:
    """Verify the unchanged successor evidence schema before classifying absence."""
    evidence = _json(raw)
    if (
        set(evidence) != {"version", "plan", "release", "witness"}
        or evidence.get("version") != "boca-successor-pair-intent-evidence-v1"
    ):
        raise _reject()
    plan, release, witness = evidence.get("plan"), evidence.get("release"), evidence.get("witness")
    if not isinstance(plan, dict) or not isinstance(release, dict) or not isinstance(witness, dict):
        raise _reject()
    if (
        set(plan)
        != {
            "attempt_id",
            "observation_run_id",
            "old_attempt_id",
            "old_source_sha",
            "old_controller_id",
            "old_worker_id",
            "old_controller_image_id",
            "old_worker_image_id",
            "new_source_sha",
            "release_run_id",
            "controller_ref",
            "worker_ref",
        }
        or set(release)
        != {
            "source_sha",
            "release_run_id",
            "controller_ref",
            "worker_ref",
            "controller_manifest_sha256",
            "paired_manifest_sha256",
        }
        or set(witness)
        != {
            "observation_run_id",
            "old_attempt_id",
            "old_source_sha",
            "controller_id",
            "worker_id",
            "controller_image_id",
            "worker_image_id",
            "control_inode_sha256",
            "retained",
        }
        or (
            plan.get("attempt_id"),
            plan.get("old_source_sha"),
            plan.get("new_source_sha"),
            plan.get("release_run_id"),
        )
        != (INCIDENT_1251, OLD_SOURCE_1251, NEW_SOURCE_1251, RELEASE_RUN_1251)
        or (
            release.get("source_sha"),
            release.get("release_run_id"),
            release.get("controller_ref"),
            release.get("worker_ref"),
        )
        != (
            NEW_SOURCE_1251,
            RELEASE_RUN_1251,
            plan.get("controller_ref"),
            plan.get("worker_ref"),
        )
        or (
            witness.get("observation_run_id"),
            witness.get("old_attempt_id"),
            witness.get("old_source_sha"),
            witness.get("controller_id"),
            witness.get("worker_id"),
            witness.get("controller_image_id"),
            witness.get("worker_image_id"),
        )
        != (
            plan.get("observation_run_id"),
            plan.get("old_attempt_id"),
            OLD_SOURCE_1251,
            plan.get("old_controller_id"),
            plan.get("old_worker_id"),
            plan.get("old_controller_image_id"),
            plan.get("old_worker_image_id"),
        )
        or not all(
            _cid(value)
            for value in (
                plan.get("old_controller_id"),
                plan.get("old_worker_id"),
                witness.get("control_inode_sha256"),
                release.get("controller_manifest_sha256"),
                release.get("paired_manifest_sha256"),
            )
        )
        or plan.get("old_controller_id") == plan.get("old_worker_id")
        or any(
            type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
            for value in (plan.get("old_controller_image_id"), plan.get("old_worker_image_id"))
        )
        or stage.CONTROLLER.fullmatch(str(plan.get("controller_ref"))) is None
        or stage.WORKER.fullmatch(str(plan.get("worker_ref"))) is None
        or not _retained_pins_1251_valid(witness.get("retained"))
        or any(
            _RUN.fullmatch(str(value)) is None
            for value in (plan.get("observation_run_id"), plan.get("old_attempt_id"))
        )
    ):
        raise _reject()
    return plan


def _retained_pins_1251_valid(value: object) -> bool:
    """Match the six literal ResourcePins fields emitted by SuccessorPairJournal."""
    expected = {
        "ipc_creator_attempt": _RUN,
        "ipc_inode_sha256": _CID,
        "site_creator_attempt": _RUN,
        "site_inode_sha256": _CID,
        "egress_creator_attempt": _RUN,
        "egress_id": _CID,
    }
    return (
        type(value) is dict
        and set(value) == set(expected)
        and all(
            type(value[key]) is str and pattern.fullmatch(value[key]) is not None
            for key, pattern in expected.items()
        )
    )


def _precommit_intent_1251(raw: bytes, evidence: bytes, plan: dict[str, Any]) -> None:
    intent = _json(raw)
    if (
        set(intent)
        != {
            "attempt",
            "evidence_sha256",
            "old_controller",
            "old_worker",
            "old_source",
            "new_source",
            "release",
        }
        or (
            intent.get("attempt"),
            intent.get("old_source"),
            intent.get("new_source"),
            intent.get("release"),
        )
        != (INCIDENT_1251, OLD_SOURCE_1251, NEW_SOURCE_1251, RELEASE_RUN_1251)
        or intent.get("evidence_sha256") != hashlib.sha256(evidence).hexdigest()
        or (intent.get("old_controller"), intent.get("old_worker"))
        != (plan.get("old_controller_id"), plan.get("old_worker_id"))
    ):
        raise _reject()


def observe_private_1251(observation_run: str) -> bytes:
    """Host-side #1251 PRECOMMIT classification; output is private binary only."""
    if _RUN.fullmatch(observation_run) is None or observation_run == INCIDENT_1251:
        return _frame(
            {
                "run": observation_run[:20],
                "state": "UNKNOWN",
                "reason": "RUN_UNVERIFIED",
                "present": [],
                "sha256": {},
            },
            magic=_MAGIC_1251,
        )
    try:
        snapshot = _read_snapshot(_PREFIX_1251)
        present = sorted(key for key, value in snapshot.items() if value is not None)
        digests = {
            key: hashlib.sha256(item[0]).hexdigest()
            for key, item in snapshot.items()
            if item is not None
        }
        values = {key: item[0] for key, item in snapshot.items() if item is not None}
        if not present:
            state, reason = "UNKNOWN", "NO_MARKERS"
        elif "commit" in values or "technical-postflight-v2" in values:
            state, reason = "UNKNOWN", "POSTCOMMIT_MARKER_PRESENT"
        elif "evidence" not in values or "terminal" in values and "intent" not in values:
            state, reason = "UNKNOWN", "CHAIN_OUT_OF_ORDER"
        else:
            plan = _precommit_evidence_1251(values["evidence"])
            if "intent" not in values:
                state, reason = "PRECOMMIT_EVIDENCE_ONLY", "EVIDENCE_ONLY"
            else:
                _precommit_intent_1251(values["intent"], values["evidence"], plan)
                if "terminal" not in values:
                    state, reason = "PRECOMMIT_INTENT_ONLY", "INTENT_NO_TERMINAL"
                elif (
                    not values["terminal"].startswith(_TERMINAL_PREFIX)
                    or not values["terminal"].endswith(b"\n")
                    or values["terminal"].count(b"\n") != 1
                ):
                    raise _reject()
                else:
                    # Only runner-side canonical CLI decides terminal semantics.
                    state, reason = "PRECOMMIT_TERMINAL_PENDING", "VERIFY_ON_RUNNER"
        return _frame(
            {
                "run": observation_run,
                "state": state,
                "reason": reason,
                "present": present,
                "sha256": digests,
            },
            values.get("terminal", b"") if state == "PRECOMMIT_TERMINAL_PENDING" else b"",
            magic=_MAGIC_1251,
        )
    except (IncidentNoGo, OSError, ValueError, TypeError):
        return _frame(
            {
                "run": observation_run,
                "state": "NO_GO",
                "reason": "MARKER_UNVERIFIED",
                "present": [],
                "sha256": {},
            },
            magic=_MAGIC_1251,
        )


def verify_private_1251(raw: bytes, observation_run: str) -> str:
    """Runner-only #1251 parser delegates terminal validity to canonical CLI."""
    end = "observer_writes=0 recovery_authorized=false beta_deploy=NO_GO exclusive_cause=UNPROVEN"
    bad = f"BOCA_G18_INCIDENT_1251_READONLY_V1 state=NO_GO reason=FRAME_UNVERIFIED {end}"
    try:
        metadata, terminal = _unframe(raw, observation_run, _MAGIC_1251)
        state, reason = metadata.get("state"), metadata.get("reason")
        present, digests = metadata.get("present"), metadata.get("sha256")
        if (
            set(metadata) != {"run", "state", "reason", "present", "sha256"}
            or metadata["run"] != observation_run
            or type(present) is not list
            or present != sorted(set(present))
            or any(key not in _LIMITS for key in present)
            or type(digests) is not dict
            or set(digests) != set(present)
            or any(not _cid(value) for value in digests.values())
        ):
            return bad
        mask = ",".join(present) if present else "NONE"
        if (
            state == "UNKNOWN"
            and reason
            in (
                "NO_MARKERS",
                "POSTCOMMIT_MARKER_PRESENT",
                "CHAIN_OUT_OF_ORDER",
                "RUN_UNVERIFIED",
            )
            and not terminal
        ):
            if reason == "NO_MARKERS" and present:
                return bad
            if reason == "POSTCOMMIT_MARKER_PRESENT" and not (
                "commit" in present or "technical-postflight-v2" in present
            ):
                return bad
            if reason == "CHAIN_OUT_OF_ORDER" and (
                "evidence" in present and ("terminal" not in present or "intent" in present)
            ):
                return bad
            return f"BOCA_G18_INCIDENT_1251_READONLY_V1 state=UNKNOWN reason={reason} markers={mask} {end}"
        if state == "NO_GO" and reason == "MARKER_UNVERIFIED" and not terminal and not present:
            return f"BOCA_G18_INCIDENT_1251_READONLY_V1 state=NO_GO reason={reason} markers={mask} {end}"
        if (
            state == "PRECOMMIT_EVIDENCE_ONLY"
            and reason == "EVIDENCE_ONLY"
            and present == ["evidence"]
            and not terminal
        ):
            return f"BOCA_G18_INCIDENT_1251_READONLY_V1 state={state} reason={reason} markers={mask} {end}"
        if (
            state == "PRECOMMIT_INTENT_ONLY"
            and reason == "INTENT_NO_TERMINAL"
            and present == ["evidence", "intent"]
            and not terminal
        ):
            return f"BOCA_G18_INCIDENT_1251_READONLY_V1 state={state} reason={reason} markers={mask} {end}"
        if (
            state != "PRECOMMIT_TERMINAL_PENDING"
            or reason != "VERIFY_ON_RUNNER"
            or present != ["evidence", "intent", "terminal"]
            or not terminal
            or digests.get("terminal") != hashlib.sha256(terminal).hexdigest()
        ):
            return bad
        # Import the production CLI only in the full GitHub runner checkout,
        # never the four-entry inert ZIP on the Boca host.
        from boca_socios.host_boca_pair_upgrade_cli import verify_upgrade

        try:
            verify_upgrade(terminal, INCIDENT_1251)
        except ValueError:
            return (
                "BOCA_G18_INCIDENT_1251_READONLY_V1 state=NO_GO "
                f"reason=TERMINAL_UNVERIFIED markers={mask} {end}"
            )
        result = json.loads(terminal.removeprefix(_TERMINAL_PREFIX))
        if (
            result.get("state") != "NO_GO"
            or result.get("failed_phase") != "ATTEST"
            or result.get("cleanup") != "INDETERMINATE"
            or result.get("commit_started") is not False
            or result.get("old_restored") is not False
            or result.get("controller_id") is not None
            or result.get("worker_id") is not None
        ):
            return f"BOCA_G18_INCIDENT_1251_READONLY_V1 state=NO_GO reason=TERMINAL_JOURNAL_CONTRADICTION markers={mask} {end}"
        return (
            "BOCA_G18_INCIDENT_1251_READONLY_V1 state=PRECOMMIT_TERMINAL_NO_GO "
            f"reason=CANONICAL_ATTEST_NO_GO markers={mask} terminal_sha256={digests['terminal']} {end}"
        )
    except (IncidentNoGo, OSError, ValueError, KeyError, TypeError, ImportError):
        return bad


def observe_private(observation_run: str) -> bytes:
    """Read-only host entry: a private bounded frame, no public raw output."""
    if _RUN.fullmatch(observation_run) is None or observation_run == INCIDENT:
        return _frame(
            {
                "run": observation_run[:20],
                "state": "UNKNOWN",
                "reason": "RUN_UNVERIFIED",
                "present": [],
                "sha256": {},
            }
        )
    try:
        snapshot = _read_snapshot()
        present = sorted(suffix for suffix, item in snapshot.items() if item is not None)
        digests = {
            suffix: hashlib.sha256(item[0]).hexdigest()
            for suffix, item in snapshot.items()
            if item is not None
        }
        if len(present) != len(_LIMITS):
            return _frame(
                {
                    "run": observation_run,
                    "state": "UNKNOWN",
                    "reason": "MISSING_MARKER",
                    "present": present,
                    "sha256": digests,
                }
            )
        values = {suffix: item[0] for suffix, item in snapshot.items() if item is not None}
        controller, worker = _check_markers(values)
        return _frame(
            {
                "run": observation_run,
                "state": "VERIFIED_MARKERS",
                "reason": "COMPLETE",
                "present": present,
                "sha256": digests,
                "controller_id": controller,
                "worker_id": worker,
            },
            values["terminal"],
        )
    except (IncidentNoGo, OSError, ValueError):
        return _frame(
            {
                "run": observation_run,
                "state": "NO_GO",
                "reason": "MARKER_UNVERIFIED",
                "present": [],
                "sha256": {},
            }
        )


def verify_private(raw: bytes, observation_run: str) -> str:
    """Full-checkout runner only: canonical CLI verification, redacted enum."""
    end = "observer_writes=0 recovery_authorized=false beta_deploy=NO_GO external_pair_correlation=PENDING_MANUAL_REVIEW"
    bad = f"BOCA_G17_INCIDENT_READONLY_V1 state=NO_GO reason=FRAME_UNVERIFIED {end}"
    try:
        metadata, terminal = _unframe(raw, observation_run, _MAGIC)
        state, reason, present, digests = (
            metadata.get("state"),
            metadata.get("reason"),
            metadata.get("present"),
            metadata.get("sha256"),
        )
        if (
            metadata.get("run") != observation_run
            or type(present) is not list
            or any(key not in _LIMITS for key in present)
            or present != sorted(set(present))
            or type(digests) is not dict
            or set(digests) != set(present)
            or any(not _cid(value) for value in digests.values())
        ):
            return bad
        mask = ",".join(present) if present else "NONE"
        if state == "UNKNOWN" and reason in ("MISSING_MARKER", "RUN_UNVERIFIED") and not terminal:
            return (
                f"BOCA_G17_INCIDENT_READONLY_V1 state=UNKNOWN reason={reason} markers={mask} {end}"
            )
        if state == "NO_GO" and reason == "MARKER_UNVERIFIED" and not terminal:
            return f"BOCA_G17_INCIDENT_READONLY_V1 state=NO_GO reason={reason} markers={mask} {end}"
        if (
            state != "VERIFIED_MARKERS"
            or reason != "COMPLETE"
            or present != sorted(_LIMITS)
            or not terminal
            or not _cid(metadata.get("controller_id"))
            or not _cid(metadata.get("worker_id"))
            or digests.get("terminal") != hashlib.sha256(terminal).hexdigest()
        ):
            return bad
        # Production CLI deliberately imports the effectful type graph here;
        # this function runs on the GitHub runner only, NEVER in the host ZIP.
        from boca_socios.host_boca_pair_upgrade_cli import verify_upgrade

        verify_upgrade(terminal, INCIDENT)
        result = json.loads(terminal.removeprefix(_TERMINAL_PREFIX))
        # All five files, including the irreversible commit marker and the
        # technical V2 proof, describe a POSTCOMMIT journal. A canonical
        # RECOVERED or precommit NO_GO terminal is individually well formed
        # but physically contradictory to these exact durable artifacts.
        if result["commit_started"] is not True or result["old_restored"] is not False:
            return (
                "BOCA_G17_INCIDENT_READONLY_V1 state=NO_GO "
                f"reason=TERMINAL_JOURNAL_CONTRADICTION markers={mask} {end}"
            )
        for key, proof_id in (
            ("controller_id", metadata["controller_id"]),
            ("worker_id", metadata["worker_id"]),
        ):
            if result[key] is not None and result[key] != proof_id:
                return bad
        if result["state"] == "ACCEPTED":
            result_state = "HISTORICAL_TERMINAL_ACCEPTED"
        elif result["state"] == "NO_GO":
            result_state = "HISTORICAL_TERMINAL_NO_GO"
        else:
            return (
                "BOCA_G17_INCIDENT_READONLY_V1 state=NO_GO "
                f"reason=TERMINAL_JOURNAL_CONTRADICTION markers={mask} {end}"
            )
        return (
            f"BOCA_G17_INCIDENT_READONLY_V1 state={result_state} reason=CANONICAL_TERMINAL "
            f"markers={mask} terminal_sha256={digests['terminal']} {end}"
        )
    except (IncidentNoGo, OSError, ValueError, KeyError, TypeError, ImportError):
        return bad


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) == 2 and arguments[0] == "host":
        frame = observe_private(arguments[1])
        sys.stdout.buffer.write(frame)
        return 0
    if len(arguments) == 2 and arguments[0] == "host-1251":
        sys.stdout.buffer.write(observe_private_1251(arguments[1]))
        return 0
    if len(arguments) == 2 and arguments[0] == "verify":
        result = verify_private(sys.stdin.buffer.read(_FRAME_LIMIT + 1), arguments[1])
        sys.stdout.write(result + "\n")
        return 0 if "state=HISTORICAL_TERMINAL_" in result else 3
    if len(arguments) == 2 and arguments[0] == "verify-1251":
        result = verify_private_1251(sys.stdin.buffer.read(_FRAME_LIMIT + 1), arguments[1])
        sys.stdout.write(result + "\n")
        return 0 if "state=PRECOMMIT_TERMINAL_NO_GO" in result else 3
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
