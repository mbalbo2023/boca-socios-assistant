"""Build deterministic, minimal Boca-only host transaction ZIP (code-only).

The archive is never executed by this builder; the protected GitHub job must
hash its exact bytes and its host-side bootstrap must compare that digest
before executing anything. BLACKBOX and other project files are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import zipfile
from pathlib import Path

SOURCES = (
    "compose.yaml",
    "compose.beta.yaml",
    "compose.beta.browser.yaml",
    "docker/seccomp_profile.json",
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_first_deploy.py",
    "src/boca_socios/host_rootless_setup.py",
    "src/boca_socios/host_boca_cleanup.py",
    "src/boca_socios/host_boca_attempt.py",
    "src/boca_socios/host_boca_transaction.py",
    "src/boca_socios/host_boca_cutover.py",
    "src/boca_socios/host_boca_cutover_backend.py",
    "src/boca_socios/host_boca_cutover_cli.py",
    "src/boca_socios/host_boca_cutover_receipt.py",
    "src/boca_socios/worker_start_capture.py",
    "src/boca_socios/worker_start_receipt.py",
    "src/boca_socios/host_cutover_capture_readback.py",
    "src/boca_socios/host_cutover_ipc_probe.py",
    "src/boca_socios/host_cutover_stage.py",
    # One-incident post-failure stage recovery uses the same immutable memfd
    # transport as Cutover A; never install these scripts onto the droplet.
    "scripts/__init__.py",
    "scripts/host_cutover_postapply_reconcile.py",
    "scripts/host_cutover_stage_recovery.py",
    # Host-only lifecycle bridge and bounded stdlib dependency closure.
    "src/boca_socios/host_lifecycle_actions.py",
    "src/boca_socios/host_lifecycle_observe.py",
    "src/boca_socios/host_cutover_inventory_observe.py",
    "src/boca_socios/host_lifecycle_rootless_adapter.py",
    "src/boca_socios/host_boca_lifecycle.py",
    "src/boca_socios/host_on_demand_lifecycle.py",
    "src/boca_socios/host_on_demand_service.py",
    "src/boca_socios/host_on_demand_status.py",
    "src/boca_socios/panel/lifecycle_intents.py",
    "src/boca_socios/integration/engine_socket.py",
    "src/boca_socios/storage/__init__.py",
    "src/boca_socios/storage/migrations/__init__.py",
    "src/boca_socios/storage/migrations/0001_initial.sql",
    "src/boca_socios/storage/migrations/0002_notification_outbox.sql",
    "src/boca_socios/storage/migrations/0003_reservation_guard.sql",
    "src/boca_socios/storage/migrations/0004_credential_key_policy.sql",
    "src/boca_socios/storage/migrations/0005_simulation_outcomes.sql",
    "src/boca_socios/storage/migrations/0006_beta_commands.sql",
    "src/boca_socios/storage/migrations/0007_telegram_delivery.sql",
)
# The controller's normal panel/integration package initializers eagerly import
# application modules. In the HOST-ONLY memfd package, only the reviewed
# lifecycle receipt submodules may be imported; never BLACKBOX/navigation.
HOST_ONLY_INIT = {
    "boca_socios/panel/__init__.py": b'"""Protected host ledger-only namespace."""\n',
    "boca_socios/integration/__init__.py": b'"""Protected host engine-wire-only namespace."""\n',
}
# Source-owned by #321, merged only after that PR passes its own QA.  The
# standalone #320 bundle has the core profile; after integration it gains
# BOTH exact Option B files. One present without the other is always NO_GO.
OPTION_B_SOURCES = (
    "src/boca_socios/panel/owner_session_disk_bootstrap.py",
    "src/boca_socios/panel/owner_session_sql/0001_owner_browser_session.sql",
)
OPTION_B_STDLIB_BUNDLE_NAME = "boca_socios/owner_session_disk_bootstrap.py"
# Dedicated fixed-target recovery payload (#795/#807/#819/#827/#834). Full Cutover is at
# its 860k source ceiling and must never inherit these extra files.
RECOVERY_SOURCES = (
    "docker/seccomp_profile.json",
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_boca_cleanup.py",
    "scripts/__init__.py",
    "scripts/host_cutover_worker_inspect.py",
    "scripts/host_cutover_worker_recovery.py",
)
# R83: preflight must never inherit the broader Cutover/Option B sources.
# The SHA-checked independent memfd variant retains only its stdlib closure.
PREFLIGHT_SOURCES = (
    "docker/seccomp_profile.json",
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_first_deploy.py",
    "src/boca_socios/host_boca_cleanup.py",
    "scripts/__init__.py",
    "scripts/host_cutover_worker_preflight.py",
)
PREFLIGHT_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 9 or sys.argv[1] != 'cutover-worker-preflight':\n"
    "    raise SystemExit(3)\n"
    "from scripts import host_cutover_worker_preflight as preflight\n"
    "raise SystemExit(preflight.main(['host', *sys.argv[2:]]))\n"
).encode("ascii")
RECOVERY_MAIN = (
    "import sys\n"
    "modes = {'cutover-worker-recover': 'host', "
    "'cutover-worker-807-recover': 'host-807', "
    "'cutover-worker-819-recover': 'host-819', "
    "'cutover-worker-827-recover': 'host-827', "
    "'cutover-worker-834-recover': 'host-834'}\n"
    "if len(sys.argv) != 2 or sys.argv[1] not in modes:\n"
    "    raise SystemExit(3)\n"
    "from scripts import host_cutover_worker_recovery as recovery\n"
    "raise SystemExit(recovery.main([modes[sys.argv[1]]]))\n"
).encode("ascii")
MAIN = (
    "import sys\n"
    "if len(sys.argv) > 1 and sys.argv[1] == 'cutover-a-capture-readback-v3':\n"
    "    if len(sys.argv) != 3: raise SystemExit(3)\n"
    "    import os\n"
    "    from boca_socios.host_cutover_capture_readback import run_host\n"
    "    binding = os.environ.get('BOCA_CUTOVER_A_DISPATCH_BINDING_SHA256', '')\n"
    "    raise SystemExit(run_host(sys.argv[2], approved_go_binding_sha256=binding))\n"
    "if len(sys.argv) > 1 and sys.argv[1] == 'cutover-stage-recover-v3':\n"
    "    from scripts import host_cutover_stage_recovery as recovery\n"
    "    raise SystemExit(recovery.main(['host-v3', *sys.argv[2:]]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] == 'cutover-stage-recover':\n"
    "    from scripts import host_cutover_stage_recovery as recovery\n"
    "    raise SystemExit(recovery.main(['host', *sys.argv[2:]]))\n"
    "if len(sys.argv) == 6 and sys.argv[1] == 'on-demand-status':\n"
    "    from boca_socios.host_on_demand_status import main as status\n"
    "    raise SystemExit(status(['host', *sys.argv[2:]]))\n"
    "if len(sys.argv) == 3 and sys.argv[1] == 'on-demand-serve':\n"
    "    from boca_socios.host_on_demand_service import socket_main\n"
    "    raise SystemExit(socket_main(sys.argv[2]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] in ('lifecycle-apply', 'lifecycle-bridge-selftest'):\n"
    "    from boca_socios import host_lifecycle_actions as bridge\n"
    "    if sys.argv[1] == 'lifecycle-bridge-selftest':\n"
    "        raise SystemExit(bridge.selftest_main())\n"
    "    raise SystemExit(bridge.main(sys.argv[2:]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] in ('lifecycle-observe', 'lifecycle-observe-selftest'):\n"
    "    from boca_socios import host_lifecycle_observe as observe\n"
    "    if sys.argv[1] == 'lifecycle-observe-selftest':\n"
    "        raise SystemExit(observe.selftest_main())\n"
    "    raise SystemExit(observe.main(sys.argv[2:]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] in ('cutover-inventory-observe', 'cutover-inventory-selftest'):\n"
    "    from boca_socios import host_cutover_inventory_observe as cutover_inventory\n"
    "    if sys.argv[1] == 'cutover-inventory-selftest':\n"
    "        raise SystemExit(cutover_inventory.selftest_main())\n"
    "    raise SystemExit(cutover_inventory.main(sys.argv[2:]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] in ('official-inventory-observe', 'official-inventory-selftest'):\n"
    "    from boca_socios import host_cutover_inventory_observe as official_inventory\n"
    "    if sys.argv[1] == 'official-inventory-selftest':\n"
    "        raise SystemExit(official_inventory.official_selftest_main())\n"
    "    raise SystemExit(official_inventory.official_main(sys.argv[2:]))\n"
    "from boca_socios.host_boca_transaction import main\n"
    "raise SystemExit(main())\n"
).encode("ascii")
# The complete R135 archive adds the installed control, lifecycle and readback.
# The separate worker preflight carries the updated host adapter. Each reviewed
# entry set retains its own compressed transport bound.
MAX_SOURCE_BYTES = 1_040_000
MAX_ARCHIVE_BYTES = 512_000
RECOVERY_MAX_SOURCE_BYTES = 256_000
RECOVERY_MAX_ARCHIVE_BYTES = 128_000
PREFLIGHT_MAX_SOURCE_BYTES = 500_000
PREFLIGHT_MAX_ARCHIVE_BYTES = 128_000


def build(
    root: Path, target: Path, *, worker_recovery: bool = False, worker_preflight: bool = False
) -> str:
    """Write one deterministic, explicitly allowlisted runner-only archive."""
    if worker_recovery and worker_preflight:
        raise ValueError("Boca protected bundle modes must be exclusive")
    if worker_recovery:
        files: dict[str, bytes] = {"__main__.py": RECOVERY_MAIN}
        sources: tuple[str, ...] = RECOVERY_SOURCES
        max_source = RECOVERY_MAX_SOURCE_BYTES
        max_archive = RECOVERY_MAX_ARCHIVE_BYTES
    elif worker_preflight:
        files = {"__main__.py": PREFLIGHT_MAIN}
        sources = PREFLIGHT_SOURCES
        max_source = PREFLIGHT_MAX_SOURCE_BYTES
        max_archive = PREFLIGHT_MAX_ARCHIVE_BYTES
    else:
        files = {"__main__.py": MAIN, **HOST_ONLY_INIT}
        b_sources = tuple(root / rel for rel in OPTION_B_SOURCES)
        if any(source.exists() or source.is_symlink() for source in b_sources):
            if not all(source.is_file() and not source.is_symlink() for source in b_sources):
                raise ValueError("Boca Option B requires both reviewed session source and SQL")
            sources = (*SOURCES, *OPTION_B_SOURCES)
        else:
            sources = SOURCES
        max_source = MAX_SOURCE_BYTES
        max_archive = MAX_ARCHIVE_BYTES
    for rel in sources:
        source = root / rel
        if source.is_symlink():
            raise ValueError("Boca protected package source may not be a symlink")
        item = source.lstat()
        if not stat.S_ISREG(item.st_mode) or not 0 < item.st_size <= max_source:
            raise ValueError("Boca protected package source missing/oversized")
        data = source.read_bytes()
        if len(data) != item.st_size:
            raise ValueError("Boca protected package source changed while reading")
        # The full Boca `panel/__init__.py` has UI imports. The standalone
        # stdlib-only disk attestor is shipped under a private ZIP import name
        # instead of importing any unreviewed panel or BLACKBOX dependency.
        name = (
            OPTION_B_STDLIB_BUNDLE_NAME if rel == OPTION_B_SOURCES[0] else rel.removeprefix("src/")
        )
        files[name] = data
    if not 0 < sum(len(item) for item in files.values()) <= max_source:
        raise ValueError("Boca protected package total exceeds bounded contract")
    if target.is_symlink() or target.exists():
        raise ValueError("Boca protected package target must be a fresh artifact")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for name in sorted(files):
                    entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.create_system = 3
                    entry.external_attr = 0o100644 << 16
                    bundle.writestr(entry, files[name])
            stream.flush()
            os.fsync(stream.fileno())
        raw = target.read_bytes()
        if not 0 < len(raw) <= max_archive:
            raise ValueError("Boca protected package ZIP exceeds bounded contract")
        return hashlib.sha256(raw).hexdigest()
    except Exception:
        # Target was freshly created by us and never shared with other jobs.
        # Preserve partial evidence for investigation; never broad-delete.
        raise


def build_worker_recovery(root: Path, target: Path) -> str:
    """Build only the small stopped-worker recovery transport, never Cutover."""
    return build(root, target, worker_recovery=True)


def build_worker_preflight(root: Path, target: Path) -> str:
    """Build the seven-entry preflight-only transport, never full Cutover."""
    return build(root, target, worker_preflight=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca-only deterministic host code bundle")
    variant = parser.add_mutually_exclusive_group()
    variant.add_argument("--worker-recovery", action="store_true")
    variant.add_argument("--worker-preflight", action="store_true")
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("runner_target", type=Path)
    args = parser.parse_args()
    print(
        "BOCA_PROTECTED_BUNDLE sha256="
        f"{build(args.repository_root, args.runner_target, worker_recovery=args.worker_recovery, worker_preflight=args.worker_preflight)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
