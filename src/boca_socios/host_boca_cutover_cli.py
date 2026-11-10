"""Host-only Cutover protocol: historical v1/v2 and owner-dispatch V3.

V3 has a separate explicit entrypoint and byte/run binding, not independent
GO_B approval. All versions fail closed without their injected binding and
verified memfd ZIP. V3 always requires detailed terminal cleanup evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from boca_socios import host_boca_cutover_backend as backend
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios.host_boca_cutover import (
    CUTOVER_FAILURE_PHASES,
    WORKER_COMPENSATION_STATES,
    WORKER_PRIMARY_PHASES,
    CutoverPlan,
    CutoverReceipt,
    valid_worker_exit_evidence,
    valid_worker_exit_signature,
)
from boca_socios.worker_start_capture import is_capture_result

VERSION = "boca-cutover-a-host-invocation-v1"
VERSION_PREPARED = "boca-cutover-a-host-invocation-v2"
VERSION_DISPATCH = "boca-cutover-a-host-invocation-v3"
MAX_INVOCATION_BYTES = 4096
MAX_BUNDLE_BYTES = 512_000
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,5462}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PREPARE_ID = re.compile(r"[1-9][0-9]{0,19}\Z")


class CutoverCliError(ValueError):
    """Host request is not bound to an authentic, exact GO and memfd ZIP."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CutoverCliError("duplicate Cutover A CLI field")
        result[key] = value
    return result


@dataclass(frozen=True)
class CutoverInvocation:
    plan: CutoverPlan
    bundle_sha256: str
    go_binding_sha256: str
    prepare_run_id: str | None = None
    dispatch_v3: bool = False

    @classmethod
    def decode(cls, encoded: str) -> CutoverInvocation:
        """Decode one canonical public-coordinate record (no secrets/cookies)."""
        if _TOKEN.fullmatch(encoded) is None:
            raise CutoverCliError("cutover invocation URL-safe token malformed")
        try:
            padded = encoded + "=" * ((-len(encoded)) % 4)
            raw = base64.urlsafe_b64decode(padded)
            if (
                not 0 < len(raw) <= MAX_INVOCATION_BYTES
                or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != encoded
            ):
                raise CutoverCliError("cutover invocation noncanonical base64")
            payload = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise CutoverCliError("cutover invocation invalid encoding/JSON") from exc
        version = payload.get("version") if isinstance(payload, dict) else None
        expected = {"version", "plan", "bundle_sha256", "go_binding_sha256"}
        if version == VERSION_PREPARED:
            expected.add("prepare_run_id")
        if (
            not isinstance(payload, dict)
            or version not in (VERSION, VERSION_PREPARED, VERSION_DISPATCH)
            or set(payload) != expected
            or not isinstance(payload["plan"], dict)
            or set(payload["plan"]) != set(CutoverPlan.__dataclass_fields__)
            or any(type(value) is not str for value in payload["plan"].values())
            or type(payload["bundle_sha256"]) is not str
            or type(payload["go_binding_sha256"]) is not str
            or _DIGEST.fullmatch(payload["bundle_sha256"]) is None
            or _DIGEST.fullmatch(payload["go_binding_sha256"]) is None
            or (
                version == VERSION_PREPARED
                and (
                    type(payload["prepare_run_id"]) is not str
                    or _PREPARE_ID.fullmatch(payload["prepare_run_id"]) is None
                    or payload["prepare_run_id"] == payload["plan"]["attempt_id"]
                )
            )
            or json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii") != raw
        ):
            raise CutoverCliError("cutover invocation immutable fields invalid")
        try:
            plan = CutoverPlan(**payload["plan"])
            plan.validate()
        except (ValueError, TypeError) as exc:
            raise CutoverCliError("cutover host coordinates untrusted") from exc
        return cls(
            plan,
            payload["bundle_sha256"],
            payload["go_binding_sha256"],
            payload.get("prepare_run_id"),
            version == VERSION_DISPATCH,
        )


IDLE_RECEIPT = (
    "BOCA_BOT_INSTALL state=IDLE_INSTALLED panel=HEALTHY engine=STOPPED "
    "worker=CREATED pid=0 controller_restart=VERIFIED runtime_start=UNVERIFIED"
)


def encode_invocation(
    plan: CutoverPlan,
    *,
    bundle_sha256: str,
    go_binding_sha256: str,
    prepare_run_id: str | None = None,
    dispatch_v3: bool = False,
) -> str:
    """Make the one bounded, canonical, public-coordinate host argument."""
    plan.validate()
    if type(dispatch_v3) is not bool or (dispatch_v3 and prepare_run_id is not None):
        raise CutoverCliError("V3 dispatch cannot consume a legacy PREPARE")
    if _DIGEST.fullmatch(bundle_sha256) is None or _DIGEST.fullmatch(go_binding_sha256) is None:
        raise CutoverCliError("Cutover host invocation digest malformed")
    if prepare_run_id is not None and (
        type(prepare_run_id) is not str
        or _PREPARE_ID.fullmatch(prepare_run_id) is None
        or prepare_run_id == plan.attempt_id
    ):
        raise CutoverCliError("Cutover PREPARE identity invalid")
    public = {
        "version": VERSION_DISPATCH
        if dispatch_v3
        else VERSION_PREPARED
        if prepare_run_id is not None
        else VERSION,
        "plan": asdict(plan),
        "bundle_sha256": bundle_sha256,
        "go_binding_sha256": go_binding_sha256,
    }
    if prepare_run_id is not None:
        public["prepare_run_id"] = prepare_run_id
    raw = json.dumps(
        public,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    if not 0 < len(raw) <= MAX_INVOCATION_BYTES:
        raise CutoverCliError("Cutover host invocation payload unbounded")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if CutoverInvocation.decode(encoded) != CutoverInvocation(
        plan, bundle_sha256, go_binding_sha256, prepare_run_id, dispatch_v3
    ):
        raise CutoverCliError("Cutover host invocation roundtrip mismatch")
    return encoded


def _bundle_digest() -> str:
    """Bound the authenticated memfd ZIP bytes to the reviewed invocation."""
    location = sys.argv[0]
    if re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", location) is None:
        raise CutoverCliError("cutover CLI requires verified memfd process")
    try:
        with open(location, "rb") as stream:
            data = stream.read(MAX_BUNDLE_BYTES + 1)
    except OSError as exc:
        raise CutoverCliError("cutover CLI cannot inspect source memfd") from exc
    if not 0 < len(data) <= MAX_BUNDLE_BYTES:
        raise CutoverCliError("cutover CLI source ZIP unbounded")
    return hashlib.sha256(data).hexdigest()


def run_cli(
    encoded: str,
    *,
    approved_go_binding_sha256: str = "",
    dispatch_v3: bool = False,
    execute: Callable[[CutoverPlan], CutoverReceipt] | None = None,
    execute_prepared: Callable[[CutoverPlan, str], CutoverReceipt] | None = None,
    reconcile: Callable[[CutoverPlan, CutoverReceipt], None] | None = None,
) -> int:
    """Fail closed unless the authorized entrypoint injects its exact binding.

    Historical GO_B and V3 dispatch are distinct protocol paths. Fakes are
    injectable only for offline protocol tests, not host dispatch.
    """
    try:
        invocation = CutoverInvocation.decode(encoded)
        if invocation.dispatch_v3 != dispatch_v3:
            raise CutoverCliError("Cutover host protocol differs from authorized entrypoint")
        if invocation.bundle_sha256 != _bundle_digest():
            raise CutoverCliError("cutover invocation source ZIP hash differs")
        if (
            _DIGEST.fullmatch(approved_go_binding_sha256) is None
            or approved_go_binding_sha256 != invocation.go_binding_sha256
        ):
            raise CutoverCliError("cutover independent exact-run GO absent")
        if invocation.prepare_run_id is None:
            if execute_prepared is not None:
                raise CutoverCliError("prepared executor cannot run legacy token")
            if execute is None and invocation.dispatch_v3:
                receipt = backend.execute_reviewed_cutover(invocation.plan, dispatch_v3=True)
            else:
                receipt = (execute or backend.execute_reviewed_cutover)(invocation.plan)
        else:
            if execute is not None:
                raise CutoverCliError("legacy executor cannot consume a PREPARE token")
            if execute_prepared is None:
                receipt = backend.execute_reviewed_cutover(
                    invocation.plan, prepare_run_id=invocation.prepare_run_id
                )
            else:
                receipt = execute_prepared(invocation.plan, invocation.prepare_run_id)
        (reconcile or terminal.verify_persisted_exact)(invocation.plan, receipt)
        postflight = ""
        if invocation.prepare_run_id is not None or invocation.dispatch_v3:
            detail = receipt.cleanup_receipt
            if detail is None:
                if receipt.accepted:
                    raise CutoverCliError("Cutover A prepared host cleanup evidence incomplete")
            elif detail.attempt_id != invocation.plan.attempt_id:
                raise CutoverCliError("Cutover A postflight belongs to another attempt")
            else:
                # Failures with positively observed cleanup still expose the
                # bounded receipt for RCA. Ambiguous effects remain NO_GO.
                postflight = detail.redacted_json()
                if receipt.accepted and (detail.outcome != "SUCCESS" or detail.status != "ACCEPT"):
                    raise CutoverCliError("Cutover A accepted cleanup result mismatched")
        if not receipt.accepted:
            if postflight:
                print("BOCA_CUTOVER_A_POSTFLIGHT " + postflight)
            if (
                receipt.failed_phase == "PREPARE_WORKER"
                and receipt.worker_primary_phase in WORKER_PRIMARY_PHASES
                and receipt.worker_compensation in WORKER_COMPENSATION_STATES
            ):
                line = (
                    "BOCA_CUTOVER_A_WORKER_FAILURE primary="
                    + receipt.worker_primary_phase
                    + " compensation="
                    + receipt.worker_compensation
                )
                if receipt.worker_exit_code is not None or receipt.worker_oom_killed is not None:
                    if not valid_worker_exit_evidence(
                        receipt.worker_primary_phase,
                        receipt.worker_exit_code,
                        receipt.worker_oom_killed,
                    ):
                        raise CutoverCliError("Cutover A worker exit metadata invalid")
                    exit_code = receipt.worker_exit_code
                    oom = receipt.worker_oom_killed
                    line += (
                        f" exit_code={exit_code}"
                        + " oom="
                        + ("YES" if oom is True else "NO" if oom is False else "UNKNOWN")
                    )
                if receipt.worker_exit_signature is not None:
                    if not valid_worker_exit_evidence(
                        receipt.worker_primary_phase,
                        receipt.worker_exit_code,
                        receipt.worker_oom_killed,
                    ) or not valid_worker_exit_signature(receipt.worker_exit_signature):
                        raise CutoverCliError("Cutover A worker exit v4 metadata invalid")
                    line += " signature=" + receipt.worker_exit_signature
                if receipt.worker_stderr_observation is not None:
                    if not valid_worker_exit_signature(
                        receipt.worker_exit_signature
                    ) or not is_capture_result(receipt.worker_stderr_observation):
                        raise CutoverCliError("Cutover A worker capture invalid")
                    line += (
                        f" stderr_observation={receipt.worker_stderr_observation}"
                        f" run={invocation.plan.attempt_id} sha={invocation.plan.target_sha}"
                    )
                print(line)
            # A bounded phase hint only; never an authenticated result.
            if receipt.failed_phase in CUTOVER_FAILURE_PHASES:
                print("BOCA_CUTOVER_A_FAILURE_PHASE phase=" + receipt.failed_phase)
            print("BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED")
            return 3
    except Exception:
        # No raw argv, owner identity, source bytes or remote exception text.
        # Also covers unexpected Docker/terminal errors without false success.
        # Hard cancellation is not turned into a synthetic terminal receipt.
        print("BOCA_CUTOVER_A_HOST state=NO_GO receipt=UNVERIFIED runtime=UNVERIFIED")
        return 3
    print(
        f"BOCA_CUTOVER_A_HOST state=ACCEPTED attempt={invocation.plan.attempt_id} "
        f"target_sha={invocation.plan.target_sha} cleanup=ACCEPT "
        "receipt=RECORDED runtime=UNVERIFIED"
    )
    if receipt.idle_installed:
        print(IDLE_RECEIPT)
    if postflight:
        # V2-only strict companion line; the original v1 ACK stays byte-identical.
        # The runner verifies both in one bounded, approved SSH host receipt.
        print("BOCA_CUTOVER_A_POSTFLIGHT " + postflight)
    return 0
