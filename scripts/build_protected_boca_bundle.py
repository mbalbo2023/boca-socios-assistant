"""Build deterministic, minimal Boca-only host transaction ZIP (code-only).

The archive is never executed by this builder; the protected GitHub job must
hash its exact bytes and its host-side bootstrap must compare that digest
before executing anything. BLACKBOX and other project files are excluded.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import stat
import tokenize
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
    "scripts/host_cutover_904_recovery.py",
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
# Independent zero-effect live Boca inventory census. Never inherit Compose,
# host Cutover transaction, browser BLACKBOX, leases or recovery entrypoints.
CENSUS_SOURCES = (
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_boca_cleanup.py",
    "src/boca_socios/host_boca_census.py",
)
CENSUS_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'cutover-a-census':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_census import main as census\n"
    "raise SystemExit(census(['host',sys.argv[2]]))\n"
).encode("ascii")
# R177 installed dual-service inventory: extend ONLY the inert census closure,
# never inherit the broad Cutover dispatcher, Compose or browser runtime.
PAIR_SOURCES = (
    *CENSUS_SOURCES,
    "src/boca_socios/host_cutover_inventory_observe.py",
    "src/boca_socios/host_boca_pair_observe.py",
)
PAIR_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'boca-pair-observe':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_pair_observe import main as pair\n"
    "raise SystemExit(pair(['host',sys.argv[2]]))\n"
).encode("ascii")
POSTCOMMIT_SOURCES = (*PAIR_SOURCES, "src/boca_socios/host_boca_pair_postcommit.py")
RETAINED_SOURCES = (*POSTCOMMIT_SOURCES, "src/boca_socios/host_boca_retained_resources.py")
RETAINED_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'boca-retained-resource-observe':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_retained_resources import main\n"
    "sys.argv[1] = 'host'\n"
    "raise SystemExit(main())\n"
).encode("ascii")
POSTCOMMIT_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'boca-postcommit-observe':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_pair_postcommit import main as observe\n"
    "raise SystemExit(observe(['host',sys.argv[2]]))\n"
).encode("ascii")
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
# W1 has its OWN limited executable, not the enormous Cutover dispatcher or
# unrelated recovery/notification/Compose payloads. All imports are stdlib or
# existing, explicitly selected host attestors; never include BLACKBOX files.
W1_SOURCES = (
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
    *tuple(
        source for source in SOURCES if source.startswith("src/boca_socios/storage/migrations/000")
    ),
)
PHYSICAL_SOURCES = tuple(
    source for source in W1_SOURCES if source != "src/boca_socios/host_worker_w1.py"
) + (
    "src/boca_socios/host_worker_physical.py",
    "docker/seccomp_profile.json",
)
PHYSICAL_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'worker-physical-once':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_worker_physical import main as physical\n"
    "raise SystemExit(physical(['host',sys.argv[2]]))\n"
).encode("ascii")
W1_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'worker-diagnose-once':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_worker_w1 import main as w1\n"
    "raise SystemExit(w1(['host',sys.argv[2]]))\n"
).encode("ascii")
BINDING_SOURCES = tuple(
    dict.fromkeys(
        (
            *(name for name in W1_SOURCES if name != "src/boca_socios/host_worker_w1.py"),
            *PAIR_SOURCES,
            "src/boca_socios/host_boca_binding_observe.py",
        )
    )
)
BINDING_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'boca-binding-observe':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_binding_observe import main as binding\n"
    "raise SystemExit(binding(['host',sys.argv[2]]))\n"
).encode("ascii")
# R179: separate no-effect SQLite witness and effectful two-CID upgrade.
# Neither is permitted to reinterpret an R178 bundle or execute browser code.
SQLITE_OBSERVE_SOURCES = tuple(
    dict.fromkeys(
        (
            *BINDING_SOURCES,
            "src/boca_socios/host_boca_sqlite_identity.py",
            "src/boca_socios/host_boca_pair_upgrade_cli.py",
        )
    )
)
SQLITE_OBSERVE_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'boca-sqlite-inode-observe':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_pair_upgrade_cli import main as cli\n"
    "raise SystemExit(cli(['observe-sqlite',sys.argv[2]]))\n"
).encode("ascii")
PAIR_UPGRADE_SOURCES = tuple(
    dict.fromkeys(
        (
            *SQLITE_OBSERVE_SOURCES,
            "compose.beta.yaml",
            "compose.beta.browser.yaml",
            "docker/seccomp_profile.json",
            "src/boca_socios/host_cutover_stage.py",
            "src/boca_socios/host_boca_pair_upgrade_plan.py",
            "src/boca_socios/host_boca_pair_upgrade.py",
            "src/boca_socios/host_boca_cutover.py",
            "src/boca_socios/host_boca_cutover_backend.py",
            "src/boca_socios/host_boca_cutover_receipt.py",
            "src/boca_socios/host_boca_cutover_cli.py",
            "src/boca_socios/host_on_demand_replace.py",
            "src/boca_socios/host_boca_pair_stage.py",
            "src/boca_socios/host_boca_pair_upgrade_backend.py",
            "src/boca_socios/host_boca_pair_upgrade_reusable.py",
            "src/boca_socios/host_boca_upgrade_same_lease.py",
            "src/boca_socios/host_boca_upgrade_postflight.py",
            "src/boca_socios/host_boca_upgrade_postflight_runtime.py",
            "src/boca_socios/host_boca_postflight_sources_v2.py",
            "src/boca_socios/host_boca_success_bridge_v2.py",
            "src/boca_socios/host_boca_upgrade_cleanup_runtime.py",
            "src/boca_socios/host_boca_upgrade_successor_runtime.py",
            "src/boca_socios/host_boca_upgrade_failure_cleanup_v2.py",
            "src/boca_socios/host_boca_successor_physical_v2.py",
            "src/boca_socios/host_boca_cleanup_v2.py",
            "src/boca_socios/host_boca_pair_postcommit.py",
            "src/boca_socios/host_cutover_inventory_observe.py",
            "src/boca_socios/deploy_inputs.py",
            "src/boca_socios/host_boca_repeatable_journal.py",
            "src/boca_socios/host_boca_upgrade_adapters.py",
            "src/boca_socios/host_boca_upgrade_release_auth.py",
            "src/boca_socios/host_boca_upgrade_release_bridge.py",
            "src/boca_socios/host_boca_upgrade_observation_bridge.py",
            "src/boca_socios/host_boca_upgrade_retained_bridge.py",
            "src/boca_socios/host_boca_current_pair_v2.py",
            "src/boca_socios/host_boca_successor_integrations.py",
            "src/boca_socios/host_boca_retained_resources.py",
            "src/boca_socios/release_manifest.py",
            "src/boca_socios/browser_release_manifest.py",
            "src/boca_socios/release_run.py",
        )
    )
)
PAIR_UPGRADE_RELEASE_NAMES = (
    "boca-release-manifest.json",
    "boca-browser-release-manifest.json",
    "runner-proof.json",
    "boca-pair-observation.receipt",
    "observation-proof.json",
    "boca-retained-observation.receipt",
    "retained-proof.json",
    "current-pair-v2.receipt",
)
PAIR_UPGRADE_RELEASE_PLACEHOLDER = b'{"state":"NO_GO"}\n'
PAIR_UPGRADE_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 9 or sys.argv[1] != 'boca-pair-upgrade-apply':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_pair_upgrade_cli import main as cli\n"
    "raise SystemExit(cli(['apply',*sys.argv[2:]]))\n"
).encode("ascii")
POSTCOMMIT_FINALIZE_SOURCES = tuple(
    dict.fromkeys(
        (
            *SQLITE_OBSERVE_SOURCES,
            "src/boca_socios/host_boca_pair_postcommit.py",
            "src/boca_socios/host_boca_pair_postcommit_finalize.py",
            "src/boca_socios/host_on_demand_replace.py",
            "src/boca_socios/host_cutover_stage.py",
            "src/boca_socios/host_boca_pair_upgrade.py",
            "src/boca_socios/host_boca_pair_upgrade_plan.py",
        )
    )
)
POSTCOMMIT_FINALIZE_MAIN = (
    "import sys\n"
    "if len(sys.argv) != 3 or sys.argv[1] != 'boca-postcommit-finalize':\n"
    "    raise SystemExit(3)\n"
    "from boca_socios.host_boca_pair_postcommit_finalize import main as finalize\n"
    "raise SystemExit(finalize(['host',sys.argv[2]]))\n"
).encode("ascii")
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
    "if len(sys.argv) > 1 and sys.argv[1] in ('cutover-image-plan-916', 'cutover-image-finish-916'):\n"
    "    from scripts import host_cutover_904_recovery as recovery904\n"
    "    mode = 'observe-916' if sys.argv[1] == 'cutover-image-plan-916' else 'finish-916'\n"
    "    raise SystemExit(recovery904.main([mode, *sys.argv[2:]]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] == 'cutover-stage-recover-904':\n"
    "    from scripts import host_cutover_904_recovery as recovery904\n"
    "    raise SystemExit(recovery904.main(['host', *sys.argv[2:]]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] == 'cutover-stage-recover-v3':\n"
    "    from scripts import host_cutover_stage_recovery as recovery\n"
    "    raise SystemExit(recovery.main(['host-v3', *sys.argv[2:]]))\n"
    "if len(sys.argv) > 1 and sys.argv[1] == 'cutover-stage-recover':\n"
    "    from scripts import host_cutover_stage_recovery as recovery\n"
    "    raise SystemExit(recovery.main(['host', *sys.argv[2:]]))\n"
    "if len(sys.argv) == 6 and sys.argv[1] == 'on-demand-status':\n"
    "    from boca_socios.host_on_demand_status import main as status\n"
    "    raise SystemExit(status(['host', *sys.argv[2:]]))\n"
    "if len(sys.argv) == 6 and sys.argv[1] == 'on-demand-egress':\n"
    "    from boca_socios.host_on_demand_status import main as status\n"
    "    raise SystemExit(status(['host-egress', *sys.argv[2:]]))\n"
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
# The R138 full bundle includes the #916 observer and receipt verifier.
# Bound the full payload separately from the two reduced worker archives.
# R178 adds only the source-pinned, run-bound Boca worker egress attestor.
# +4 KiB preserves independent smaller bundles and the exact file allowlist.
# R244 protected same-lease cleanup API adds 2,767 source bytes. The already
# reviewed full-Cutover comment-token compaction now yields 1,157,003 bytes;
# this 1,158,144 cap leaves only 1,141 bytes' headroom. Other mode limits and
# each entry allowlist remain unchanged (no new host capability or import).
MAX_SOURCE_BYTES = 1_158_144
MAX_ARCHIVE_BYTES = 512_000
RECOVERY_MAX_SOURCE_BYTES = 256_000
RECOVERY_MAX_ARCHIVE_BYTES = 128_000
CENSUS_MAX_SOURCE_BYTES = 160_000
CENSUS_MAX_ARCHIVE_BYTES = 64_000
PAIR_MAX_SOURCE_BYTES = 192_000
PAIR_MAX_ARCHIVE_BYTES = 64_000
POSTCOMMIT_MAX_SOURCE_BYTES = 208_000
POSTCOMMIT_MAX_ARCHIVE_BYTES = 72_000
BINDING_MAX_SOURCE_BYTES = 900_000
BINDING_MAX_ARCHIVE_BYTES = 320_000
SQLITE_OBSERVE_MAX_SOURCE_BYTES = 950_000
SQLITE_OBSERVE_MAX_ARCHIVE_BYTES = 340_000
# R252's reviewed genuine V2 postflight reader extends the SAME fixed ZIP
# closure, without executable rewriting or a second host transport. Bound
# both builder and memfd verifier to 1.4 MB; keep compressed cap unchanged.
PAIR_UPGRADE_MAX_SOURCE_BYTES = 1_400_000
PAIR_UPGRADE_MAX_ARCHIVE_BYTES = 480_000
POSTCOMMIT_FINALIZE_MAX_SOURCE_BYTES = 1_100_000
POSTCOMMIT_FINALIZE_MAX_ARCHIVE_BYTES = 400_000
PREFLIGHT_MAX_SOURCE_BYTES = 520_000
PREFLIGHT_MAX_ARCHIVE_BYTES = 128_000
W1_MAX_SOURCE_BYTES = 900_000
W1_MAX_ARCHIVE_BYTES = 320_000
PHYSICAL_MAX_SOURCE_BYTES = 900_000
PHYSICAL_MAX_ARCHIVE_BYTES = 320_000
_FULL_ONLY_COMPACT_SOURCE = "src/boca_socios/host_first_deploy.py"


def _compact_comment_tokens(source: bytes, *, filename: str = _FULL_ONLY_COMPACT_SOURCE) -> bytes:
    """Keep executable Python bytes/line numbers, omit only comment tokens.

    The full Cutover and an oversized successor pair can use this identical
    transport-only transform. The repository retains the original comments;
    the SHA-pinned ZIP changes only after checked code-object equivalence.
    """
    decoded = source.decode("utf-8")
    lines = decoded.splitlines(keepends=True)
    for token in tokenize.generate_tokens(io.StringIO(decoded).readline):
        if token.type != tokenize.COMMENT:
            continue
        line_index, column = token.start[0] - 1, token.start[1]
        line = lines[line_index]
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        prefix = line[:column]
        lines[line_index] = (prefix if prefix.strip() else "") + ending
    compacted = "".join(lines).encode("utf-8")
    if (
        decoded.count("\n") != compacted.count(b"\n")
        or ast.dump(ast.parse(source)) != ast.dump(ast.parse(compacted))
        or compile(source, filename, "exec") != compile(compacted, filename, "exec")
    ):
        raise ValueError("Boca protected source compaction changed executable Python")
    return compacted


def build(
    root: Path,
    target: Path,
    *,
    worker_recovery: bool = False,
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
    pair_upgrade_release_dir: Path | None = None,
    postcommit_finalize: bool = False,
) -> str:
    """Write one deterministic, explicitly allowlisted runner-only archive."""
    if (
        sum(
            (
                worker_recovery,
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
        or pair_upgrade_release_dir is not None
        and not pair_upgrade
    ):
        raise ValueError("Boca protected bundle modes must be exclusive")
    # Mode branches assign these exactly once at runtime; a single annotation
    # avoids mypy no-redef errors from annotations repeated in each branch.
    files: dict[str, bytes]
    sources: tuple[str, ...]
    if postcommit_finalize:
        files = {"__main__.py": POSTCOMMIT_FINALIZE_MAIN, **HOST_ONLY_INIT}
        sources = POSTCOMMIT_FINALIZE_SOURCES
        max_source = POSTCOMMIT_FINALIZE_MAX_SOURCE_BYTES
        max_archive = POSTCOMMIT_FINALIZE_MAX_ARCHIVE_BYTES
    elif pair_upgrade:
        files = {"__main__.py": PAIR_UPGRADE_MAIN, **HOST_ONLY_INIT}
        if pair_upgrade_release_dir is None:
            # Offline/backward-compatible builds remain *ineligible*. They
            # include no Github-authenticated artifact or transport proof.
            release_files = {
                name: PAIR_UPGRADE_RELEASE_PLACEHOLDER for name in PAIR_UPGRADE_RELEASE_NAMES
            }
        else:
            from boca_socios import host_boca_current_pair_v2 as current
            from boca_socios import host_boca_upgrade_adapters as adapters
            from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease
            from boca_socios.host_boca_upgrade_observation_bridge import (
                _runner_input as observation_input,
            )
            from boca_socios.host_boca_upgrade_observation_bridge import (
                verify_bundled_observation,
            )
            from boca_socios.host_boca_upgrade_release_bridge import (
                _runner_input,
                verify_bundled_release,
            )

            folder = pair_upgrade_release_dir
            if folder.is_symlink() or set(item.name for item in folder.iterdir()) != set(
                PAIR_UPGRADE_RELEASE_NAMES
            ):
                raise ValueError("Boca release evidence directory is not exact")
            try:
                release_files = {
                    name: (
                        observation_input(
                            str(folder / name),
                            limit=48_000 if name == "boca-retained-observation.receipt" else 4096,
                        )
                        if name
                        in (
                            "boca-pair-observation.receipt",
                            "observation-proof.json",
                            "boca-retained-observation.receipt",
                            "retained-proof.json",
                            "current-pair-v2.receipt",
                        )
                        else _runner_input(str(folder / name))
                    )
                    for name in PAIR_UPGRADE_RELEASE_NAMES
                }
            except Exception:
                raise ValueError("Boca runner release files are not safe") from None
            # The builder never upgrades a bare, form-derived digest to a
            # privileged proof: this checks only local source-to-proof bytes.
            # The runner's prior R242 REST authentication is mandatory.
            try:
                coordinates = json.loads(release_files["runner-proof.json"])
                candidate = CandidateRelease(
                    coordinates["source_sha"],
                    coordinates["release_run_id"],
                    coordinates["controller_ref"],
                    coordinates["worker_ref"],
                )
                verify_bundled_release(
                    release_files["runner-proof.json"],
                    release_files["boca-release-manifest.json"],
                    release_files["boca-browser-release-manifest.json"],
                    candidate,
                )
                observation = json.loads(release_files["observation-proof.json"])
                verify_bundled_observation(
                    release_files["observation-proof.json"],
                    release_files["boca-pair-observation.receipt"],
                    candidate.source_sha,
                    observation["observer_run_id"],
                    observation["apply_attempt_id"],
                    candidate.release_run_id,
                )
                # R188 V1 is an immutable *creator* observation, not a live
                # source/attempt proof after B→C. V2 was GH-authenticated by
                # the runner and remains read-only, never same-lease GO.
                if release_files["retained-proof.json"] != PAIR_UPGRADE_RELEASE_PLACEHOLDER:
                    raise ValueError("Boca legacy retained proof must remain NO_GO")
                v2 = current.verify_current_pair_v2(release_files["current-pair-v2.receipt"])
                history = v2["historical_resource_custody"]
                if not isinstance(history, dict):
                    raise ValueError("Boca missing historical resources")
                custody = adapters.parse_custody_integrity(
                    release_files["boca-retained-observation.receipt"],
                    observation_run_id=history["original_observation_run"],
                )
                if (
                    history != current._history(custody)
                    or v2["observed_pair_sha256"]
                    != hashlib.sha256(release_files["boca-pair-observation.receipt"]).hexdigest()
                    or v2["observation_proof_sha256"]
                    != hashlib.sha256(release_files["observation-proof.json"]).hexdigest()
                    or v2["target_main_sha"] != candidate.source_sha
                    or v2["target_release_run"] != candidate.release_run_id
                    or v2["observation_run"] != observation["observer_run_id"]
                    or v2["apply_attempt"] != observation["apply_attempt_id"]
                    or any(
                        v2[stored] != observation[observed]
                        for stored, observed in (
                            ("previous_pair_source_sha", "old_source_sha"),
                            ("previous_pair_attempt", "old_attempt_id"),
                            ("previous_controller_id", "controller_id"),
                            ("previous_worker_id", "worker_id"),
                            ("previous_controller_image_id", "controller_image_id"),
                            ("previous_worker_image_id", "worker_image_id"),
                            ("previous_controller_ref", "controller_ref"),
                            ("previous_worker_ref", "worker_ref"),
                        )
                    )
                ):
                    raise ValueError("Boca current-pair source/creator mismatch")
            except Exception:
                raise ValueError("Boca runner release evidence mismatch") from None
        files.update({f"release/{name}": data for name, data in release_files.items()})
        sources = PAIR_UPGRADE_SOURCES
        max_source = PAIR_UPGRADE_MAX_SOURCE_BYTES
        max_archive = PAIR_UPGRADE_MAX_ARCHIVE_BYTES
    elif sqlite_observe:
        files = {"__main__.py": SQLITE_OBSERVE_MAIN, **HOST_ONLY_INIT}
        sources = SQLITE_OBSERVE_SOURCES
        max_source = SQLITE_OBSERVE_MAX_SOURCE_BYTES
        max_archive = SQLITE_OBSERVE_MAX_ARCHIVE_BYTES
    elif binding_observe:
        files = {"__main__.py": BINDING_MAIN, **HOST_ONLY_INIT}
        sources = BINDING_SOURCES
        max_source = BINDING_MAX_SOURCE_BYTES
        max_archive = BINDING_MAX_ARCHIVE_BYTES
    elif retained_observe:
        files = {"__main__.py": RETAINED_MAIN}
        sources = RETAINED_SOURCES
        max_source = 240_000
        max_archive = 80_000
    elif postcommit_observe:
        files = {"__main__.py": POSTCOMMIT_MAIN}
        sources = POSTCOMMIT_SOURCES
        max_source = POSTCOMMIT_MAX_SOURCE_BYTES
        max_archive = POSTCOMMIT_MAX_ARCHIVE_BYTES
    elif pair_observe:
        files = {"__main__.py": PAIR_MAIN}
        sources = PAIR_SOURCES
        max_source = PAIR_MAX_SOURCE_BYTES
        max_archive = PAIR_MAX_ARCHIVE_BYTES
    elif census:
        files = {"__main__.py": CENSUS_MAIN}
        sources = CENSUS_SOURCES
        max_source = CENSUS_MAX_SOURCE_BYTES
        max_archive = CENSUS_MAX_ARCHIVE_BYTES
    elif worker_recovery:
        files = {"__main__.py": RECOVERY_MAIN}
        sources = RECOVERY_SOURCES
        max_source = RECOVERY_MAX_SOURCE_BYTES
        max_archive = RECOVERY_MAX_ARCHIVE_BYTES
    elif worker_preflight:
        files = {"__main__.py": PREFLIGHT_MAIN}
        sources = PREFLIGHT_SOURCES
        max_source = PREFLIGHT_MAX_SOURCE_BYTES
        max_archive = PREFLIGHT_MAX_ARCHIVE_BYTES
    elif worker_w1:
        files = {"__main__.py": W1_MAIN, **HOST_ONLY_INIT}
        sources = W1_SOURCES
        max_source = W1_MAX_SOURCE_BYTES
        max_archive = W1_MAX_ARCHIVE_BYTES
    elif worker_physical:
        files = {"__main__.py": PHYSICAL_MAIN, **HOST_ONLY_INIT}
        sources = PHYSICAL_SOURCES
        max_source = PHYSICAL_MAX_SOURCE_BYTES
        max_archive = PHYSICAL_MAX_ARCHIVE_BYTES
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
    full_cutover = not any(
        (
            worker_recovery,
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
    # Preserve exact test-fixture bytes and future small source sets. Compact
    # only when a reviewed complete source set actually exceeds its bounded
    # total; never raise that cap to compensate for unused comment bytes.
    if full_cutover and sum(map(len, files.values())) > max_source:
        host_entry = _FULL_ONLY_COMPACT_SOURCE.removeprefix("src/")
        files[host_entry] = _compact_comment_tokens(files[host_entry])
    if pair_upgrade and sum(map(len, files.values())) > max_source:
        # Compact the *whole* reviewed pair source closure, not just enough
        # files to scrape beneath the ceiling for one fixture: genuine
        # authenticated observation receipts vary in size between attempts.
        # The AST/compiled-bytecode/line checks reject semantic changes.
        for rel in PAIR_UPGRADE_SOURCES:
            if rel.endswith(".py"):
                bundle_name = rel.removeprefix("src/")
                files[bundle_name] = _compact_comment_tokens(files[bundle_name], filename=rel)
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
    variant.add_argument("--worker-w1", action="store_true")
    variant.add_argument("--worker-physical", action="store_true")
    variant.add_argument("--census", action="store_true")
    variant.add_argument("--pair-observe", action="store_true")
    variant.add_argument("--postcommit-observe", action="store_true")
    variant.add_argument("--retained-observe", action="store_true")
    variant.add_argument("--binding-observe", action="store_true")
    variant.add_argument("--sqlite-observe", action="store_true")
    variant.add_argument("--pair-upgrade", action="store_true")
    parser.add_argument("--pair-upgrade-release-dir", type=Path)
    variant.add_argument("--postcommit-finalize", action="store_true")
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("runner_target", type=Path)
    args = parser.parse_args()
    print(
        "BOCA_PROTECTED_BUNDLE sha256="
        f"{build(args.repository_root, args.runner_target, worker_recovery=args.worker_recovery, worker_preflight=args.worker_preflight, worker_w1=args.worker_w1, worker_physical=args.worker_physical, census=args.census, pair_observe=args.pair_observe, postcommit_observe=args.postcommit_observe, retained_observe=args.retained_observe, binding_observe=args.binding_observe, sqlite_observe=args.sqlite_observe, pair_upgrade=args.pair_upgrade, pair_upgrade_release_dir=args.pair_upgrade_release_dir, postcommit_finalize=args.postcommit_finalize)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
