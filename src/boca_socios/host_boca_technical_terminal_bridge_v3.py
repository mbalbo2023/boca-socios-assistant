"""R257 inert same-lease technical SUCCESS/FAILURE terminal correlation.

This is NOT a host entrypoint, APPLY gate or owner-passkey acceptance. A future
reviewed protected backend must call ``attest_technical_success`` after its
genuine one-shot SUCCESS V2 cleanup and before returning ACCEPT to the engine.
The unchanged engine then invokes this object as its terminal sink while the
*same* Boca lease is held. A failure goes to the existing FAILURE V2 sink.

No new lease, Docker, browser or network operation is introduced here. In
particular the original R186 deployment must never be replayed. A technical
ACCEPTED journal still reports BETA NO_GO until independent owner evidence.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from typing import Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_durable_technical_postflight_v2 as durable
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_cli as cli
from boca_socios import host_boca_postflight_volume_attestor_v2 as volume
from boca_socios import host_boca_success_bridge_v2 as successful
from boca_socios import host_boca_successor_assembly_v3 as assembly
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_cutover_stage as stage


class TechnicalTerminalNoGo(ValueError):
    """One fixed redacted NO_GO; ambiguous effects are never retried."""


def _fail() -> TechnicalTerminalNoGo:
    return TechnicalTerminalNoGo("BOCA_TECHNICAL_TERMINAL_V3 NO_GO/INDETERMINATE")


@dataclass(frozen=True, slots=True)
class TechnicalTerminalEvidence:
    """Persisted engine technical terminal, explicitly NOT BETA acceptance."""

    attempt_id: str
    filename: str
    raw: bytes
    sha256: str
    technical_postflight_sha256: str
    final_cleanup_sha256: str

    @property
    def terminal_state(self) -> Literal["TECHNICAL_ACCEPTED_OWNER_PENDING"]:
        return "TECHNICAL_ACCEPTED_OWNER_PENDING"

    @property
    def passkey_attested(self) -> Literal[False]:
        return False

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def beta_deploy(self) -> Literal["NO_GO"]:
        return "NO_GO"


class OneShotTechnicalTerminalBridge:
    """One exact journal, plan, held lease, SUCCESS and FAILURE actors.

    Constructed only from the R253 inert graph; even a successful synthetic
    invocation cannot lift the engine's type-level APPLY interlock. The
    success phase is one-way BEFORE production snapshot or O_EXCL write.
    """

    def __init__(self, actors: assembly.InertSameLeaseAssembly) -> None:
        if type(actors) is not assembly.InertSameLeaseAssembly:
            raise _fail()
        try:
            actors.__post_init__()
        except Exception:
            raise _fail() from None
        self._actors = actors
        self._success_started = False
        self._terminal_started = False
        self._success_lease: cleanup.BocaJobLease | None = None
        self._success_expected: postflight.PostflightExpected | None = None
        self._success_proof: durable.DurableTechnicalPostflightReceipt | None = None
        self._technical_terminal: TechnicalTerminalEvidence | None = None

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def terminal_accept_authorized(self) -> Literal[False]:
        # No technical certificate substitutes the owner Chrome/passkey.
        return False

    @property
    def technical_terminal(self) -> TechnicalTerminalEvidence | None:
        return self._technical_terminal

    def _guard(self, lease: cleanup.BocaJobLease) -> None:
        graph = self._actors
        graph.__post_init__()  # Do not trust a graph silently rebound after construction.
        if type(lease) is not cleanup.BocaJobLease:
            raise _fail()
        cleanup.verify_protected_boca_job_lease(lease, graph.plan.attempt_id)
        graph.journal.attest_active_intent(graph.plan, lease)
        if graph.journal._lease is not lease or type(graph.journal._intent) is not bytes:
            raise _fail()
        # A technical ACCEPTED requires the *durable* irreversible marker,
        # not merely a caller's boolean `commit_started`.
        marker = hashlib.sha256(graph.journal._intent).hexdigest().encode("ascii")
        name = f".boca-pair-upgrade-{graph.plan.attempt_id}.commit"
        fd = stage._root_fd()
        try:
            saved, _ = stage._read_file(fd, name, hashlib.sha256(marker).hexdigest(), limit=1024)
            if saved != marker:
                raise _fail()
        finally:
            os.close(fd)
        cleanup.verify_protected_boca_job_lease(lease, graph.plan.attempt_id)

    def attest_technical_success(
        self,
        expected: postflight.PostflightExpected,
        volume_attestor: volume.ProductionBocaVolumeAttestor,
        lease: cleanup.BocaJobLease,
    ) -> None:
        """Consume actual SUCCESS V2 then persist exact R253 technical proof.

        Call only after final cleanup, on the backend's original held lease.
        On any uncertainty, the attempt is consumed and the terminal sink
        refuses ACCEPTED; never run cleanup, snapshot or postflight again.
        """
        if self._success_started or self._terminal_started:
            raise _fail()
        self._success_started = True
        try:
            graph = self._actors
            if (
                type(expected) is not postflight.PostflightExpected
                or expected.plan is not graph.plan
                or expected.release is not graph.preflight.inputs.release
                or expected.retained != graph.preflight.inputs.custody.resources
                or type(volume_attestor) is not volume.ProductionBocaVolumeAttestor
                or volume_attestor.expected is not expected
                or volume_attestor.lease is not lease
            ):
                raise _fail()
            self._guard(lease)
            produced = durable.OneShotDurableTechnicalPostflightV2(
                graph.plan,
                expected,
                lease,
                graph.success.final_cleanup,
                volume_attestor=volume_attestor,
            ).persist()
            if (
                type(produced) is not durable.DurableTechnicalPostflightReceipt
                or produced.attempt_id != graph.plan.attempt_id
                or produced.version != durable.TECHNICAL_VERSION
                or produced.filename
                != f".boca-pair-upgrade-{graph.plan.attempt_id}.technical-postflight-v2"
                or type(produced.raw) is not bytes
                or type(produced.inode_dev) is not int
                or type(produced.inode_ino) is not int
                or produced.inode_dev <= 0
                or produced.inode_ino <= 0
                or produced.completion.plan is not graph.plan
                or produced.completion.cleanup_receipt
                is not graph.success.final_cleanup.completed_final_cleanup(graph.plan, lease)
                or produced.beta_deploy != "NO_GO"
                or produced.terminal_accept_authorized is not False
                or produced.sha256 != hashlib.sha256(produced.raw).hexdigest()
            ):
                raise _fail()
            self._guard(lease)
            self._success_lease = lease
            self._success_expected = expected
            self._success_proof = produced
        except Exception:
            raise _fail() from None

    def __call__(
        self,
        plan: transaction.PairCoordinates,
        receipt: transaction.PairUpgradeReceipt,
        lease: cleanup.BocaJobLease,
    ) -> None:
        """Terminal callback: exact technical SUCCESS or existing FAILURE V2.

        ACCEPTED is only the engine's *technical installed-pair outcome* and
        cannot authorize BETA or assert owner login. No second lease or retry.
        """
        if self._terminal_started:
            raise _fail()
        self._terminal_started = True
        try:
            graph = self._actors
            if (
                type(plan) is not transaction.PairCoordinates
                or plan is not graph.plan
                or type(receipt) is not transaction.PairUpgradeReceipt
                or receipt.attempt_id != plan.attempt_id
            ):
                raise _fail()
            if receipt.state != "ACCEPTED":
                if self._success_started:
                    # A postcommit NO_GO is a truthful durable red terminal;
                    # the existing FAILURE sink writes ONLY that journal and
                    # performs NO rollback/FAILURE cleanup past the marker.
                    if (
                        receipt.state != "NO_GO"
                        or receipt.commit_started is not True
                        or receipt.old_restored is not False
                        or receipt.cleanup == "ACCEPT"
                    ):
                        raise _fail()
                    self._guard(lease)
                graph.failure(plan, receipt, lease)
                return
            expected = self._success_expected
            proof = self._success_proof
            if (
                not self._success_started
                or self._success_lease is not lease
                or type(expected) is not postflight.PostflightExpected
                or type(proof) is not durable.DurableTechnicalPostflightReceipt
                or receipt.cleanup != "ACCEPT"
                or receipt.commit_started is not True
                or receipt.old_restored is not False
                or receipt.failed_phase != "NONE"
                or receipt.controller_id != expected.controller_id
                or receipt.worker_id != expected.worker_id
                or proof.completion.plan is not plan
                or proof.version != durable.TECHNICAL_VERSION
                or proof.filename != f".boca-pair-upgrade-{plan.attempt_id}.technical-postflight-v2"
                or proof.beta_deploy != "NO_GO"
                or proof.terminal_accept_authorized is not False
            ):
                raise _fail()
            self._guard(lease)
            postflight.verify_technical_postflight(proof.raw, expected)
            completed = successful.verify_technical_completion(
                plan, lease, graph.success.final_cleanup, expected, proof.raw
            )
            if (
                completed.cleanup_receipt is not proof.completion.cleanup_receipt
                or completed.technical_sha256 != proof.sha256
                or proof.sha256 != hashlib.sha256(proof.raw).hexdigest()
            ):
                raise _fail()
            fd = stage._root_fd()
            try:
                readback, inode = stage._read_file(
                    fd, proof.filename, proof.sha256, limit=postflight._BOUND
                )
                named = os.stat(proof.filename, dir_fd=fd, follow_symlinks=False)
                if (
                    readback != proof.raw
                    or (inode.st_dev, inode.st_ino) != (proof.inode_dev, proof.inode_ino)
                    or (named.st_dev, named.st_ino) != (proof.inode_dev, proof.inode_ino)
                    or not stat.S_ISREG(named.st_mode)
                ):
                    raise _fail()
            finally:
                os.close(fd)
            self._guard(lease)
            graph.journal.terminal(plan, receipt, lease)
            encoded = cli.encode_upgrade(receipt)
            name = f".boca-pair-upgrade-{plan.attempt_id}.terminal"
            fd = stage._root_fd()
            try:
                saved, _ = stage._read_file(
                    fd, name, hashlib.sha256(encoded).hexdigest(), limit=1024
                )
                if saved != encoded:
                    raise _fail()
            finally:
                os.close(fd)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            self._technical_terminal = TechnicalTerminalEvidence(
                plan.attempt_id,
                name,
                saved,
                hashlib.sha256(saved).hexdigest(),
                proof.sha256,
                completed.cleanup_receipt.sha256,
            )
        except Exception:
            raise _fail() from None
