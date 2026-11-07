"""Single-process protected Boca install transaction (draft #323).

This module is currently CODE ONLY: no live workflow calls it. The transport
and strict negative selftest are published before any host effectful phase is
connected. A future protected entrypoint must hold one flock before staging,
complete success/failure cleanup in try/finally, and fail closed on lost SSH.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from typing import Literal, Protocol

from boca_socios.host_boca_attempt import (
    Result,
    begin,
    finalize_attempt,
    finish,
    intended,
)
from boca_socios.host_boca_cleanup import (
    ATTEMPT_ID,
    BocaJobLease,
    protected_boca_job_lease,
)

OPERATION = Literal["first-install", "beta-install"]
IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class Coordinates:
    """New-only install coordinates; never a legacy cutover or existing DB."""

    operation: OPERATION
    attempt_id: str
    image: str
    source_sha: str
    compose_sha: str
    origin: str = ""
    owner: str = ""


@dataclass(frozen=True)
class TransactionReceipt:
    attempt_id: str
    operation: OPERATION
    outcome: Literal["SUCCESS", "FAILURE"]
    cleanup: Literal["ACCEPT", "INDETERMINATE", "NO_GO"]
    stage_clean: bool
    controller_id: str | None

    @property
    def accepted(self) -> bool:
        return self.outcome == "SUCCESS" and self.cleanup == "ACCEPT" and self.stage_clean


class InstallBackend(Protocol):
    """Host-only effect boundary; CLI will construct only reviewed concrete backend."""

    def install(
        self, coordinates: Coordinates, base: bytes, overlay: bytes, lease: BocaJobLease
    ) -> None: ...

    def observe(self, coordinates: Coordinates, lease: BocaJobLease) -> tuple[str, bool] | None: ...

    def stop_exact(self, coordinates: Coordinates, ident: str, lease: BocaJobLease) -> None: ...

    def finish_stage(
        self,
        coordinates: Coordinates,
        *,
        installed: bool,
        cleanup_status: Literal["ACCEPT", "INDETERMINATE", "NO_GO"],
        lease: BocaJobLease,
    ) -> None: ...


def run_transaction(
    coordinates: Coordinates,
    base: bytes,
    *,
    backend: InstallBackend,
) -> TransactionReceipt:
    """One lease across install and unconditional cleanup, no false success.

    Every failure path is attempted once, without guessed IDs or broad delete.
    A hard host/SSH crash before an O_EXCL result produces no trustworthy
    final receipt: Actions must alert NO_GO rather than attempting cleanup.
    """
    if (
        coordinates.operation not in ("first-install", "beta-install")
        or not ATTEMPT_ID.fullmatch(coordinates.attempt_id)
        or not IMAGE.fullmatch(coordinates.image)
        or (coordinates.operation == "first-install" and (coordinates.origin or coordinates.owner))
        or (
            coordinates.operation == "beta-install"
            and (not coordinates.origin or not coordinates.owner)
        )
        or hashlib.sha256(base).hexdigest() != coordinates.compose_sha
    ):
        raise TransactionError("Boca install coordinates or bundled Compose untrusted")
    intent, overlay = intended(
        coordinates.operation,
        coordinates.attempt_id,
        coordinates.source_sha,
        coordinates.compose_sha,
        None,
    )
    with protected_boca_job_lease(coordinates.attempt_id) as lease:
        digest = begin(intent, lease=lease)  # Always BEFORE any Docker/staging effect.
        result: Result | None = None
        attempted_success = False
        final_status: Literal["ACCEPT", "INDETERMINATE", "NO_GO"] = "NO_GO"
        stage_clean = False
        controller_id: str | None = None
        try:
            try:
                backend.install(coordinates, base, overlay, lease)
                observed = backend.observe(coordinates, lease)
                if observed is None or not observed[1]:
                    raise TransactionError("Boca installed controller health not proven")
                controller_id = observed[0]
                result = Result(
                    coordinates.attempt_id, digest, "SUCCESS", controller_id, controller_id
                )
                finish(result, lease=lease)
                attempted_success = True
            except Exception:
                # The original phase failed. One exact observation and stop;
                # if identity is uncertain, preserve all resources and NO_GO.
                try:
                    observed = backend.observe(coordinates, lease)
                    if observed is not None:
                        controller_id, running = observed
                        if running:
                            backend.stop_exact(coordinates, controller_id, lease)
                    result = Result(coordinates.attempt_id, digest, "FAILURE", controller_id, None)
                    finish(result, lease=lease)
                except Exception:
                    # No immutable result -> no deletion authority whatsoever.
                    result = None
        finally:
            if result is not None:
                try:
                    final_status = finalize_attempt(
                        result,
                        lease=lease,
                        preserve_images=frozenset(),
                    ).status
                except Exception:
                    final_status = "NO_GO"
            try:
                backend.finish_stage(
                    coordinates,
                    installed=attempted_success,
                    cleanup_status=final_status,
                    lease=lease,
                )
                stage_clean = True
            except Exception:
                stage_clean = False
        return TransactionReceipt(
            coordinates.attempt_id,
            coordinates.operation,
            "SUCCESS" if attempted_success else "FAILURE",
            final_status,
            stage_clean,
            controller_id,
        )


class TransactionError(ValueError):
    """No install can be authorized until the entire host gate exists."""


def _bundled_reviewed_file(path: str) -> bytes:
    if path not in (
        "compose.yaml",
        "compose.beta.yaml",
        "compose.beta.browser.yaml",
        "docker/seccomp_profile.json",
    ):
        raise TransactionError("unreviewed Boca bundle file entry")
    # Source package is the already verified SHA-pinned memfd ZIP. Never
    # import a Compose file from host filesystem or a secondary SSH session.
    with zipfile.ZipFile(sys.argv[0], "r") as package:
        data = package.read(path)
    if not 0 < len(data) <= 32768:
        raise TransactionError("Boca bundled reviewed file size invalid")
    return data


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "bundle-cutover-selftest":
        try:
            from boca_socios.host_boca_cutover_backend import ReviewedCutoverSources

            reviewed = ReviewedCutoverSources.from_verified_zip()
            if any(not 0 < len(value) <= 32768 for value in reviewed.__dict__.values()):
                raise TransactionError("Cutover source payload absent")
        except (TransactionError, ValueError, TypeError, OSError, KeyError, zipfile.BadZipFile):
            print("BOCA_CUTOVER_MEMFD state=NO_GO reason=source_unverified")
            return 1
        print("BOCA_CUTOVER_MEMFD state=PASS host=untouched option_b=present")
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "cutover-a-dispatch-v3":
        from boca_socios.host_boca_cutover_cli import run_cli

        # The protected owner's single dispatch replaces the historical GO_B.
        # This is a byte/run binding, not independently granted approval.
        return run_cli(
            sys.argv[2],
            approved_go_binding_sha256=os.environ.get("BOCA_CUTOVER_A_DISPATCH_BINDING_SHA256", ""),
            dispatch_v3=True,
        )
    if len(sys.argv) == 3 and sys.argv[1] == "cutover-a-apply":
        from boca_socios.host_boca_cutover_cli import run_cli

        # Runner-side check_cutover_a_go must first authenticate three release
        # manifests, reviewed bundle bytes and the separate protected GitHub
        # Environment GO. Only its exact-run result may be sent over the
        # already authorized SSH transport to this one memfd process.
        return run_cli(
            sys.argv[2],
            approved_go_binding_sha256=os.environ.get(
                "BOCA_CUTOVER_A_APPROVED_GO_BINDING_SHA256", ""
            ),
        )
    if len(sys.argv) == 2 and sys.argv[1] == "bundle-selftest":
        try:
            assert hashlib.sha256(_bundled_reviewed_file("compose.yaml")).digest()
            assert hashlib.sha256(_bundled_reviewed_file("compose.beta.yaml")).digest()
            assert hashlib.sha256(_bundled_reviewed_file("compose.beta.browser.yaml")).digest()
            assert hashlib.sha256(_bundled_reviewed_file("docker/seccomp_profile.json")).digest()
        except (TransactionError, AssertionError, OSError, KeyError, zipfile.BadZipFile):
            print("BOCA_BUNDLE_SELFTEST state=NO_GO reason=source_unverified")
            return 1
        print("BOCA_BUNDLE_SELFTEST state=PASS host=untouched blackbox=excluded")
        return 0
    # P0 intentionally refuses effectful dispatch until source transaction,
    # runtime attestation, selective finalizer and YAML assertion are proven.
    print("BOCA_PROTECTED_INSTALL state=NO_GO reason=transaction_not_wired")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
