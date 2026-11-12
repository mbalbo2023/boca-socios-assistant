"""Tiny host-side ZIP verifier; Python source passed as -c, ZIP on stdin.

No host filesystem writes, Docker calls or network access occur before the
expected package SHA256 and strict allowed-entry list are checked. The exact
verified payload is run via a non-CLOEXEC Linux memfd in a single process.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import sys
import zipfile

EXPECTED_ENTRIES = frozenset(
    {
        "__main__.py",
        "compose.yaml",
        "compose.beta.yaml",
        "compose.beta.browser.yaml",
        "docker/seccomp_profile.json",
        "boca_socios/__init__.py",
        "boca_socios/host_first_deploy.py",
        "boca_socios/host_rootless_setup.py",
        "boca_socios/host_boca_cleanup.py",
        "boca_socios/host_boca_attempt.py",
        "boca_socios/host_boca_transaction.py",
        "boca_socios/host_boca_cutover.py",
        "boca_socios/host_boca_cutover_backend.py",
        "boca_socios/host_boca_cutover_cli.py",
        "boca_socios/host_boca_cutover_receipt.py",
        "boca_socios/worker_start_capture.py",
        "boca_socios/worker_start_receipt.py",
        "boca_socios/host_cutover_capture_readback.py",
        "boca_socios/host_cutover_ipc_probe.py",
        "boca_socios/host_cutover_stage.py",
        "scripts/__init__.py",
        "scripts/host_cutover_postapply_reconcile.py",
        "scripts/host_cutover_stage_recovery.py",
        "scripts/host_cutover_904_recovery.py",
        "boca_socios/host_lifecycle_actions.py",
        "boca_socios/host_lifecycle_observe.py",
        "boca_socios/host_cutover_inventory_observe.py",
        "boca_socios/host_lifecycle_rootless_adapter.py",
        "boca_socios/host_boca_lifecycle.py",
        "boca_socios/host_on_demand_lifecycle.py",
        "boca_socios/host_on_demand_service.py",
        "boca_socios/host_on_demand_status.py",
        "boca_socios/panel/lifecycle_intents.py",
        "boca_socios/integration/engine_socket.py",
        "boca_socios/storage/__init__.py",
        "boca_socios/panel/__init__.py",
        "boca_socios/integration/__init__.py",
        "boca_socios/storage/migrations/__init__.py",
        "boca_socios/storage/migrations/0001_initial.sql",
        "boca_socios/storage/migrations/0002_notification_outbox.sql",
        "boca_socios/storage/migrations/0003_reservation_guard.sql",
        "boca_socios/storage/migrations/0004_credential_key_policy.sql",
        "boca_socios/storage/migrations/0005_simulation_outcomes.sql",
        "boca_socios/storage/migrations/0006_beta_commands.sql",
        "boca_socios/storage/migrations/0007_telegram_delivery.sql",
    }
)
OPTION_B_ENTRIES = frozenset(
    {
        "boca_socios/owner_session_disk_bootstrap.py",
        "boca_socios/panel/owner_session_sql/0001_owner_browser_session.sql",
    }
)
# A separate, much smaller transport for the one stopped preflight container.
# It cannot dispatch Cutover and does not include host_first_deploy or Compose.
RECOVERY_ENTRIES = frozenset(
    {
        "__main__.py",
        "docker/seccomp_profile.json",
        "boca_socios/__init__.py",
        "boca_socios/host_boca_cleanup.py",
        "scripts/__init__.py",
        "scripts/host_cutover_worker_inspect.py",
        "scripts/host_cutover_worker_recovery.py",
    }
)
# Strict independent observer program: no Cutover dispatcher, Compose,
# worker start/recovery program, or mutable host workflow source.
CENSUS_ENTRIES = frozenset(
    {
        "__main__.py",
        "boca_socios/__init__.py",
        "boca_socios/host_boca_cleanup.py",
        "boca_socios/host_boca_census.py",
    }
)
# Standalone R177 pair observer remains inert and has its own strict entry
# allowlist/digest; never interpreted as the census or broad Cutover bundle.
PAIR_ENTRIES = CENSUS_ENTRIES | {
    "boca_socios/host_cutover_inventory_observe.py",
    "boca_socios/host_boca_pair_observe.py",
}
POSTCOMMIT_ENTRIES = PAIR_ENTRIES | {"boca_socios/host_boca_pair_postcommit.py"}
# Seven-entry immutable R83 worker diagnostic, never a Cutover or recovery ZIP.
PREFLIGHT_ENTRIES = frozenset(
    {
        "__main__.py",
        "docker/seccomp_profile.json",
        "boca_socios/__init__.py",
        "boca_socios/host_first_deploy.py",
        "boca_socios/host_boca_cleanup.py",
        "scripts/__init__.py",
        "scripts/host_cutover_worker_preflight.py",
    }
)
W1_ENTRIES = frozenset(
    {"__main__.py", "boca_socios/panel/__init__.py", "boca_socios/integration/__init__.py"}
    | {
        source.removeprefix("src/")
        for source in (
            "src/boca_socios/__init__.py",
            "src/boca_socios/host_first_deploy.py",
            "src/boca_socios/host_boca_cleanup.py",
            "src/boca_socios/host_boca_lifecycle.py",
            "src/boca_socios/host_lifecycle_rootless_adapter.py",
            "src/boca_socios/host_on_demand_lifecycle.py",
            "src/boca_socios/host_on_demand_service.py",
            "src/boca_socios/host_cutover_ipc_probe.py",
            "src/boca_socios/worker_start_capture.py",
            "src/boca_socios/host_worker_w1.py",
            "src/boca_socios/panel/lifecycle_intents.py",
            "src/boca_socios/integration/engine_socket.py",
            "src/boca_socios/storage/__init__.py",
            "src/boca_socios/storage/migrations/__init__.py",
            *(
                f"src/boca_socios/storage/migrations/000{i}_{name}.sql"
                for i, name in (
                    (1, "initial"),
                    (2, "notification_outbox"),
                    (3, "reservation_guard"),
                    (4, "credential_key_policy"),
                    (5, "simulation_outcomes"),
                    (6, "beta_commands"),
                    (7, "telegram_delivery"),
                )
            ),
        )
    }
)
PHYSICAL_ENTRIES = (W1_ENTRIES - {"boca_socios/host_worker_w1.py"}) | {
    "boca_socios/host_worker_physical.py",
    "docker/seccomp_profile.json",
}
BINDING_ENTRIES = (
    (W1_ENTRIES - {"boca_socios/host_worker_w1.py"})
    | PAIR_ENTRIES
    | {
        "boca_socios/host_boca_binding_observe.py",
    }
)
# R179 requires *different* SHA-pinned transports: a read-only SQLite witness
# and a separately admitted transaction. Neither inherits browser code.
SQLITE_OBSERVE_ENTRIES = BINDING_ENTRIES | {
    "boca_socios/host_boca_sqlite_identity.py",
    "boca_socios/host_boca_pair_upgrade_cli.py",
}
PAIR_UPGRADE_ENTRIES = SQLITE_OBSERVE_ENTRIES | {
    "compose.beta.yaml",
    "compose.beta.browser.yaml",
    "docker/seccomp_profile.json",
    "boca_socios/host_cutover_stage.py",
    "boca_socios/host_boca_pair_upgrade_plan.py",
    "boca_socios/host_boca_pair_upgrade.py",
    "boca_socios/host_boca_cutover.py",
    "boca_socios/host_boca_cutover_backend.py",
    "boca_socios/host_boca_cutover_receipt.py",
    "boca_socios/host_boca_cutover_cli.py",
    "boca_socios/host_on_demand_replace.py",
    "boca_socios/host_boca_pair_stage.py",
    "boca_socios/host_boca_pair_upgrade_backend.py",
    "boca_socios/host_boca_pair_upgrade_reusable.py",
    "boca_socios/host_boca_upgrade_same_lease.py",
    "boca_socios/host_boca_upgrade_postflight.py",
    "boca_socios/host_boca_upgrade_postflight_runtime.py",
    "boca_socios/host_boca_upgrade_cleanup_runtime.py",
    "boca_socios/host_boca_upgrade_successor_runtime.py",
    "boca_socios/host_boca_cleanup_v2.py",
    "boca_socios/host_boca_pair_postcommit.py",
    "boca_socios/host_cutover_inventory_observe.py",
    "boca_socios/deploy_inputs.py",
    "boca_socios/host_boca_repeatable_journal.py",
    "boca_socios/host_boca_upgrade_adapters.py",
    "boca_socios/host_boca_upgrade_release_auth.py",
    "boca_socios/host_boca_upgrade_release_bridge.py",
    "boca_socios/host_boca_upgrade_observation_bridge.py",
    "boca_socios/host_boca_upgrade_retained_bridge.py",
    "boca_socios/host_boca_retained_resources.py",
    "boca_socios/release_manifest.py",
    "boca_socios/browser_release_manifest.py",
    "boca_socios/release_run.py",
    "release/boca-release-manifest.json",
    "release/boca-browser-release-manifest.json",
    "release/runner-proof.json",
    "release/boca-pair-observation.receipt",
    "release/observation-proof.json",
    "release/boca-retained-observation.receipt",
    "release/retained-proof.json",
}
POSTCOMMIT_FINALIZE_ENTRIES = SQLITE_OBSERVE_ENTRIES | {
    "boca_socios/host_boca_pair_postcommit.py",
    "boca_socios/host_boca_pair_postcommit_finalize.py",
    "boca_socios/host_on_demand_replace.py",
    "boca_socios/host_cutover_stage.py",
    "boca_socios/host_boca_pair_upgrade.py",
    "boca_socios/host_boca_pair_upgrade_plan.py",
}
MAX_ZIP = 512_000
RETAINED_ENTRIES = POSTCOMMIT_ENTRIES | {"boca_socios/host_boca_retained_resources.py"}
RETAINED_MAX_ZIP = 80_000
RETAINED_MAX_UNCOMPRESSED = 240_000
# R138 source bounds match the builder. Each variant checks its own entry set and digest.
MAX_UNCOMPRESSED = 1_158_144
RECOVERY_MAX_ZIP = 128_000
RECOVERY_MAX_UNCOMPRESSED = 256_000
CENSUS_MAX_ZIP = 64_000
CENSUS_MAX_UNCOMPRESSED = 160_000
PAIR_MAX_ZIP = 64_000
PAIR_MAX_UNCOMPRESSED = 192_000
POSTCOMMIT_MAX_ZIP = 72_000
POSTCOMMIT_MAX_UNCOMPRESSED = 208_000
BINDING_MAX_ZIP = 320_000
BINDING_MAX_UNCOMPRESSED = 900_000
SQLITE_OBSERVE_MAX_ZIP = 340_000
SQLITE_OBSERVE_MAX_UNCOMPRESSED = 950_000
PAIR_UPGRADE_MAX_ZIP = 480_000
PAIR_UPGRADE_MAX_UNCOMPRESSED = 1_300_000
POSTCOMMIT_FINALIZE_MAX_ZIP = 400_000
POSTCOMMIT_FINALIZE_MAX_UNCOMPRESSED = 1_100_000
PREFLIGHT_MAX_ZIP = 128_000
PREFLIGHT_MAX_UNCOMPRESSED = 520_000
W1_MAX_ZIP = 320_000
W1_MAX_UNCOMPRESSED = 900_000
PHYSICAL_MAX_ZIP = 320_000
PHYSICAL_MAX_UNCOMPRESSED = 900_000


def verify(
    raw: bytes,
    expected_sha: str,
    *,
    recovery: bool = False,
    worker_preflight: bool = False,
    worker_w1: bool = False,
    worker_physical: bool = False,
    census: bool = False,
    pair_observe: bool = False,
    postcommit_observe: bool = False,
    retained_observe: bool = False,
    binding_observe: bool = False,
    sqlite_observe: bool = False,
    pair_upgrade: bool = False,
    postcommit_finalize: bool = False,
) -> None:
    """Verify digest, exact transport variant, file types and separate bounds."""
    if (
        sum(
            (
                recovery,
                worker_preflight,
                worker_w1,
                worker_physical,
                census,
                pair_observe,
                postcommit_observe,
                retained_observe,
                binding_observe,
                sqlite_observe,
                pair_upgrade,
                postcommit_finalize,
            )
        )
        > 1
    ):
        raise ValueError("protected Boca bundle modes must be exclusive")
    max_zip = (
        RETAINED_MAX_ZIP
        if retained_observe
        else POSTCOMMIT_FINALIZE_MAX_ZIP
        if postcommit_finalize
        else PAIR_UPGRADE_MAX_ZIP
        if pair_upgrade
        else SQLITE_OBSERVE_MAX_ZIP
        if sqlite_observe
        else BINDING_MAX_ZIP
        if binding_observe
        else PAIR_MAX_ZIP
        if pair_observe
        else POSTCOMMIT_MAX_ZIP
        if postcommit_observe
        else CENSUS_MAX_ZIP
        if census
        else RECOVERY_MAX_ZIP
        if recovery
        else PREFLIGHT_MAX_ZIP
        if worker_preflight
        else W1_MAX_ZIP
        if worker_w1
        else PHYSICAL_MAX_ZIP
        if worker_physical
        else MAX_ZIP
    )
    max_uncompressed = (
        RETAINED_MAX_UNCOMPRESSED
        if retained_observe
        else POSTCOMMIT_FINALIZE_MAX_UNCOMPRESSED
        if postcommit_finalize
        else PAIR_UPGRADE_MAX_UNCOMPRESSED
        if pair_upgrade
        else SQLITE_OBSERVE_MAX_UNCOMPRESSED
        if sqlite_observe
        else BINDING_MAX_UNCOMPRESSED
        if binding_observe
        else PAIR_MAX_UNCOMPRESSED
        if pair_observe
        else POSTCOMMIT_MAX_UNCOMPRESSED
        if postcommit_observe
        else CENSUS_MAX_UNCOMPRESSED
        if census
        else RECOVERY_MAX_UNCOMPRESSED
        if recovery
        else PREFLIGHT_MAX_UNCOMPRESSED
        if worker_preflight
        else W1_MAX_UNCOMPRESSED
        if worker_w1
        else PHYSICAL_MAX_UNCOMPRESSED
        if worker_physical
        else MAX_UNCOMPRESSED
    )
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("protected Boca bundle expected digest invalid")
    if not raw or len(raw) > max_zip or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("protected Boca bundle SHA/size mismatch")
    with zipfile.ZipFile(io.BytesIO(raw), "r") as package:
        entries = package.infolist()
        names = [entry.filename for entry in entries]
        allowlisted = (
            (RETAINED_ENTRIES,)
            if retained_observe
            else (POSTCOMMIT_FINALIZE_ENTRIES,)
            if postcommit_finalize
            else (PAIR_UPGRADE_ENTRIES,)
            if pair_upgrade
            else (SQLITE_OBSERVE_ENTRIES,)
            if sqlite_observe
            else (BINDING_ENTRIES,)
            if binding_observe
            else (PAIR_ENTRIES,)
            if pair_observe
            else (POSTCOMMIT_ENTRIES,)
            if postcommit_observe
            else (CENSUS_ENTRIES,)
            if census
            else (RECOVERY_ENTRIES,)
            if recovery
            else (PREFLIGHT_ENTRIES,)
            if worker_preflight
            else (W1_ENTRIES,)
            if worker_w1
            else (PHYSICAL_ENTRIES,)
            if worker_physical
            else (EXPECTED_ENTRIES, EXPECTED_ENTRIES | OPTION_B_ENTRIES)
        )
        if (
            frozenset(names) not in allowlisted
            or len(names) != len(set(names))
            or any(entry.is_dir() for entry in entries)
            or sum(entry.file_size for entry in entries) > max_uncompressed
        ):
            raise ValueError("protected Boca bundle entry allowlist mismatch")
        for entry in entries:
            if entry.file_size == 0 or entry.file_size > max_uncompressed:
                raise ValueError("protected Boca bundle entry size invalid")
            # The ZIP is a code bundle, never a deployed filesystem tree.
            # Refuse symlink/special entries to avoid importing from outside.
            mode = (entry.external_attr >> 16) & 0o170000
            if mode != 0o100000:
                raise ValueError("protected Boca bundle entry mode invalid")


def main() -> int:
    if len(sys.argv) < 3:
        print("BOCA_BUNDLE state=NO_GO reason=arguments", file=sys.stderr)
        return 2
    try:
        recovery = sys.argv[2] in {
            "cutover-worker-recover",
            "cutover-worker-807-recover",
            "cutover-worker-819-recover",
            "cutover-worker-827-recover",
            "cutover-worker-834-recover",
        }
        worker_preflight = sys.argv[2] == "cutover-worker-preflight"
        worker_w1 = sys.argv[2] == "worker-diagnose-once"
        worker_physical = sys.argv[2] == "worker-physical-once"
        census = sys.argv[2] == "cutover-a-census"
        pair_observe = sys.argv[2] == "boca-pair-observe"
        postcommit_observe = sys.argv[2] == "boca-postcommit-observe"
        retained_observe = sys.argv[2] == "boca-retained-resource-observe"
        binding_observe = sys.argv[2] == "boca-binding-observe"
        sqlite_observe = sys.argv[2] == "boca-sqlite-inode-observe"
        pair_upgrade = sys.argv[2] == "boca-pair-upgrade-apply"
        postcommit_finalize = sys.argv[2] == "boca-postcommit-finalize"
        if (
            sys.argv[2] in ("cutover-stage-recover-904", "cutover-image-plan-916")
            and len(sys.argv) != 8
        ):
            raise ValueError("incident operation requires five exact coordinates")
        if sys.argv[2] == "cutover-image-finish-916" and len(sys.argv) != 10:
            raise ValueError("image finish requires the observed run and plan digest")
        if recovery and len(sys.argv) != 3:
            raise ValueError("stopped worker recovery accepts no user coordinates")
        if worker_preflight and len(sys.argv) != 10:
            raise ValueError("worker preflight requires exact reviewed coordinates")
        if worker_w1 and len(sys.argv) != 4:
            raise ValueError("W1 requires one GitHub run ID only")
        if worker_physical and len(sys.argv) != 4:
            raise ValueError("Physical Boca probe requires one GitHub run ID only")
        if census and len(sys.argv) != 4:
            raise ValueError("Boca census requires one GitHub run ID only")
        if pair_observe and len(sys.argv) != 4:
            raise ValueError("Boca pair observer requires one GitHub run ID only")
        if postcommit_observe and len(sys.argv) != 4:
            raise ValueError("Boca postcommit observer requires one GitHub run ID only")
        if retained_observe and len(sys.argv) != 4:
            raise ValueError("Boca retained observer requires one GitHub run ID only")
        if binding_observe and len(sys.argv) != 4:
            raise ValueError("Boca binding observer requires one GitHub run ID only")
        if sqlite_observe and len(sys.argv) != 4:
            raise ValueError("Boca SQLite witness requires one GitHub run ID only")
        if pair_upgrade and len(sys.argv) != 10:
            raise ValueError(
                "Boca pair upgrade requires run and six reviewed release/observation pins"
            )
        if postcommit_finalize and len(sys.argv) != 4:
            raise ValueError("postcommit finalizer requires only fresh authenticated run ID")
        bound = (
            RETAINED_MAX_ZIP
            if retained_observe
            else POSTCOMMIT_FINALIZE_MAX_ZIP
            if postcommit_finalize
            else PAIR_UPGRADE_MAX_ZIP
            if pair_upgrade
            else SQLITE_OBSERVE_MAX_ZIP
            if sqlite_observe
            else BINDING_MAX_ZIP
            if binding_observe
            else PAIR_MAX_ZIP
            if pair_observe
            else POSTCOMMIT_MAX_ZIP
            if postcommit_observe
            else CENSUS_MAX_ZIP
            if census
            else RECOVERY_MAX_ZIP
            if recovery
            else PREFLIGHT_MAX_ZIP
            if worker_preflight
            else W1_MAX_ZIP
            if worker_w1
            else PHYSICAL_MAX_ZIP
            if worker_physical
            else MAX_ZIP
        )
        raw = sys.stdin.buffer.read(bound + 1)
        verify(
            raw,
            sys.argv[1],
            recovery=recovery,
            worker_preflight=worker_preflight,
            worker_w1=worker_w1,
            worker_physical=worker_physical,
            census=census,
            pair_observe=pair_observe,
            postcommit_observe=postcommit_observe,
            retained_observe=retained_observe,
            binding_observe=binding_observe,
            sqlite_observe=sqlite_observe,
            pair_upgrade=pair_upgrade,
            postcommit_finalize=postcommit_finalize,
        )
        # The memfd is passed to the *same* process via exec. No temporary
        # container, host file or broader Docker resource is ever created.
        fd = os.memfd_create("boca-protected-transaction", flags=0)
        try:
            written = os.write(fd, raw)
            if written != len(raw):
                raise OSError("short protected Boca memfd write")
            os.lseek(fd, 0, os.SEEK_SET)
            os.execv(  # noqa: S606 - exact Python binary/verified memfd, no shell
                sys.executable, (sys.executable, f"/proc/self/fd/{fd}", *sys.argv[2:])
            )
        finally:
            os.close(fd)
    except (OSError, ValueError, zipfile.BadZipFile):
        # Never print raw ZIP contents or exception text from a remote host.
        print("BOCA_BUNDLE state=NO_GO reason=hash_or_host_runtime", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
