"""Immutable, categorical evidence for one failed worker before compensation."""

from __future__ import annotations

import hashlib
import json
import os

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios.host_boca_cutover import CutoverPlan
from boca_socios.worker_start_capture import is_capture_result


def _payload(plan: CutoverPlan, intent: bytes, cid: object, observation: object) -> bytes:
    if (
        type(cid) is not str
        or not cleanup.HEX_ID.fullmatch(cid)
        or cid == plan.legacy_id
        or not is_capture_result(observation)
    ):
        raise terminal.TerminalReceiptError("cutover worker capture identity or category invalid")
    return json.dumps(
        {
            "version": "boca-cutover-a-worker-start-v1",
            "attempt_id": plan.attempt_id,
            "browser_image_ref": plan.browser_image,
            "target_source_sha": plan.target_sha,
            "intent_sha256": hashlib.sha256(intent).hexdigest(),
            "worker_id": cid,
            "worker_stderr_observation": observation,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def persist_before_cleanup(
    plan: CutoverPlan, lease: cleanup.BocaJobLease, worker_id: str, capture_result: str
) -> None:
    """Write once, under the live lease and original intent, before compensation."""
    cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
    intent = terminal._intent_bytes(plan)
    raw = _payload(plan, intent, worker_id, capture_result)
    folder = terminal._directory()
    try:
        terminal._read_exact(folder, terminal._name(plan.attempt_id, "intent"), intent)
        try:
            os.stat(terminal._name(plan.attempt_id), dir_fd=folder, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise terminal.TerminalReceiptError("cutover worker capture follows terminal result")
        terminal._create_once(folder, terminal._name(plan.attempt_id, "worker-start"), raw)
    finally:
        os.close(folder)


def _read_bound_marker(folder: int, plan: CutoverPlan, intent: bytes) -> tuple[str, str]:
    """Read from the same validated directory descriptor and exact prepared intent."""
    raw = terminal._read_marker(folder, terminal._name(plan.attempt_id, "worker-start"))
    try:
        data = json.loads(raw.decode("ascii"), object_pairs_hook=terminal._unique_fields)
    except (UnicodeError, ValueError, RecursionError):
        raise terminal.TerminalReceiptError("cutover worker capture marker malformed") from None
    if not isinstance(data, dict):
        raise terminal.TerminalReceiptError("cutover worker capture schema invalid")
    cid, result = data.get("worker_id"), data.get("worker_stderr_observation")
    if type(cid) is not str or type(result) is not str:
        raise terminal.TerminalReceiptError("cutover worker capture fields invalid")
    if _payload(plan, intent, cid, result) != raw:
        raise terminal.TerminalReceiptError("cutover worker capture conflicts with intent")
    return cid, result


def read_before_cleanup(plan: CutoverPlan) -> tuple[str, str]:
    """Read the bound CID/category even after a lost terminal; gives no runtime GO."""
    if os.geteuid() != cleanup.EXPECTED_UID or os.getegid() != cleanup.EXPECTED_UID:
        raise terminal.TerminalReceiptError("cutover worker capture reader identity invalid")
    intent = terminal._intent_bytes(plan)
    try:
        folder = terminal._directory()
        try:
            terminal._read_exact(folder, terminal._name(plan.attempt_id, "intent"), intent)
            return _read_bound_marker(folder, plan, intent)
        finally:
            os.close(folder)
    except OSError:
        raise terminal.TerminalReceiptError("cutover worker capture unavailable") from None
