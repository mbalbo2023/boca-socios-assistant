"""Build a separate bounded Boca Telegram host ZIP.

The Cutover A ZIP has a deliberately tight, independent 768 KiB source cap.
Telegram's owner/lease dependency closure must NEVER be appended to that
transaction. The default historical archive remains an inert import self-test.
The explicit installed mode dispatches only the current binding backend, under
the protected workflow's release proof and one real rootless Boca lease.
Building or importing either mode confers no host authority.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import stat
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from .build_protected_boca_bundle import _compact_comment_tokens
else:
    from build_protected_boca_bundle import _compact_comment_tokens

SOURCES = (
    "src/boca_socios/__init__.py",
    "src/boca_socios/host_boca_cleanup.py",
    "src/boca_socios/host_boca_lifecycle.py",
    "src/boca_socios/host_lifecycle_rootless_adapter.py",
    "src/boca_socios/host_on_demand_service.py",
    "src/boca_socios/host_telegram_active_helper_topology.py",
    "src/boca_socios/host_telegram_egress_helper.py",
    "src/boca_socios/host_telegram_owner_stage.py",
    "src/boca_socios/host_telegram_postcutover.py",
    "src/boca_socios/host_telegram_production_reader.py",
    "src/boca_socios/host_telegram_protected_custody_caller.py",
    "src/boca_socios/host_telegram_protected_readonly_caller.py",
    "src/boca_socios/telegram_bootstrap.py",
    "src/boca_socios/telegram_host_readonly_session.py",
    "src/boca_socios/telegram_owner_webauthn.py",
    "src/boca_socios/telegram_pairing_bootstrap.py",
    "src/boca_socios/telegram_pairing_cutover.py",
    "src/boca_socios/telegram_pairing_install.py",
    "src/boca_socios/telegram_pairing_issuer.py",
    "src/boca_socios/telegram_pairing_resolver.py",
    "src/boca_socios/telegram_private_chat_discovery.py",
    "src/boca_socios/telegram_same_lease_stage.py",
    "src/boca_socios/telegram_pairing_storage.py",
    "src/boca_socios/integration/engine_socket.py",
    "src/boca_socios/panel/lifecycle_intents.py",
    "src/boca_socios/panel/passkey.py",
    "src/boca_socios/panel/owner_sessions.py",
    "src/boca_socios/panel/owner_session_store.py",
    "src/boca_socios/panel/telegram_pairing_staging.py",
    "src/boca_socios/owner_origin.py",
    "src/boca_socios/storage/database.py",
    "src/boca_socios/domain/policy.py",
    "src/boca_socios/security/credential_vault.py",
)

# The host package never imports the application/panel/integration package
# initializers; those import additional runtime routes and could drift into
# BLACKBOX. The reviewed leaf modules above are imported explicitly instead.
PRIVATE_INITIALIZERS = {
    "boca_socios/panel/__init__.py": b'"""Host Telegram reviewed panel leaf namespace."""\n',
    "boca_socios/integration/__init__.py": b'"""Host Telegram reviewed engine leaf namespace."""\n',
    "boca_socios/storage/__init__.py": b'"""Host Telegram reviewed storage leaf namespace."""\n',
    "boca_socios/domain/__init__.py": b'"""Host Telegram reviewed policy leaf namespace."""\n',
    "boca_socios/security/__init__.py": b'"""Host Telegram reviewed custody leaf namespace."""\n',
}

MAIN = (
    "import sys\n"
    "if sys.argv[1:] != ['selftest']:\n"
    "    print('BOCA_TELEGRAM_HOST state=NO_GO reason=protected_activation_not_wired sender=OFF')\n"
    "    raise SystemExit(2)\n"
    "from boca_socios import host_telegram_protected_custody_caller as custody\n"
    "from boca_socios import host_telegram_owner_stage as owner\n"
    "from boca_socios import host_telegram_egress_helper as helper\n"
    "from boca_socios import telegram_pairing_issuer as issuer\n"
    "assert callable(custody.run_bound_telegram_staged_custody)\n"
    "assert callable(owner.observe_owner_stage_under_same_lease)\n"
    "assert callable(helper.protected_ephemeral_get_session)\n"
    "assert callable(issuer.issue_owner_pairing_receipt)\n"
    "print('BOCA_TELEGRAM_HOST state=CODE_ONLY_CLOSURE_READY host=untouched sender=OFF')\n"
).encode("ascii")
MAX_SOURCE_BYTES = 450_000
MAX_INSTALLED_SOURCE_BYTES = 512_000
MAX_ARCHIVE_BYTES = 300_000
NETWORK_PROJECTION_NAME = "boca_socios/host_first_deploy.py"
CLEANUP_PROJECTION_NAME = "boca_socios/host_boca_cleanup.py"
INSTALLATION_PROJECTION_NAME = "boca_socios/host_on_demand_lifecycle.py"
OWNER_PROJECTION_NAME = "boca_socios/host_telegram_owner_stage.py"
SERVICE_PROJECTION_NAME = "boca_socios/host_on_demand_service.py"
STAGE_PROJECTION_NAME = "boca_socios/telegram_same_lease_stage.py"

INSTALLED_SOURCES = tuple(
    source
    for source in SOURCES
    if source
    not in {
        "src/boca_socios/host_telegram_protected_readonly_caller.py",
        "src/boca_socios/telegram_host_readonly_session.py",
    }
) + (
    "src/boca_socios/host_telegram_cli.py",
    "src/boca_socios/host_telegram_backend.py",
    "src/boca_socios/host_telegram_installed_context.py",
    "src/boca_socios/host_telegram_maintenance.py",
    "src/boca_socios/host_telegram_sender.py",
    "src/boca_socios/host_telegram_status.py",
    "src/boca_socios/host_on_demand_sender_update.py",
    "src/boca_socios/telegram_maintenance_contract.py",
)
INSTALLED_MAIN = (
    "from boca_socios.host_telegram_cli import main\nraise SystemExit(main())\n"
).encode("ascii")
CLEANUP_ROOTS = frozenset(
    {
        "BocaJobLease",
        "verify_protected_boca_job_lease",
        "protected_boca_job_lease",
        "capture_inventory",
        "_inspect_field",
        "_docker",
        "CleanupError",
        "Inventory",
        "Container",
        "Image",
        "Network",
        "Volume",
        "DiskInodes",
        "DOCKER_SOCKET",
        "EXPECTED_UID",
        "EXPECTED_GID",
        "PERSISTENT_VOLUMES",
        "PROTECTED_VOLUMES",
        "HEX_ID",
        "ATTEMPT_ID",
    }
)
INSTALLED_DEPLOY_ROOTS = frozenset(
    {
        "_browser_worker_egress_network",
        "_telegram_container",
        "_telegram_egress",
        "_telegram_test_container",
        "_telegram_worker_container",
        "_telegram_worker_inspect",
        "_telegram_worker_ready",
        "_telegram_test_finished",
        "_telegram_test_environment",
        "_telegram_sender_hash",
        "_telegram_volume",
        "_json_object",
        "_run",
        "ROOTLESS_SOCKET",
        "TELEGRAM_NETWORK",
        "PROJECT",
        "TELEGRAM_VOLUME",
        "DATA_VOLUME",
    }
)
INSTALLED_SERVICE_ROOTS = frozenset(
    {
        "control_directory",
        "ControlRefused",
        "_ARCHIVE",
        "_BINDING",
        "_MAX_PLAN",
        "_MAX_ZIP",
        "_NEXT",
        "_REMOVING",
        "_ROOT",
        "_SOCKET",
        "_SOCKET_NAME",
        "_UPDATING",
        "_check_attempt",
        "_decode",
        "_directory",
        "_enabled",
        "_home",
        "_inspect",
        "_known",
        "_new",
        "_owned",
        "_plan",
        "_present",
        "_read",
        "_refuse",
        "_sha",
        "_state",
        "_sync",
        "_systemctl",
        "_unit_dir",
        "_units",
        "_verified_installation",
        "_verify_lease",
        "adopt_sender_binding",
        "read_installed_binding",
    }
)
INSTALLED_STAGE_ROOTS = frozenset(
    {
        "EncryptedPairingStage",
        "SameLeasePairingError",
        "read_encrypted_telegram_stage",
        "execute_staged_pairing_under_lease",
        "consume_telegram_owner_nonce",
    }
)


def _canonical_projection(root: Path, name: str, roots: frozenset[str]) -> bytes:
    """Select canonical declarations and their static dependencies verbatim.

    This removes unrelated dispatchers, not guards inside selected functions.
    Imports/annotations/decorators are part of the dependency graph. Unknown
    roots, duplicate definitions or changed ASTs fail the runner build.
    """
    path = root / "src" / name
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= 1_400_000
    ):
        raise ValueError("Telegram projection source unavailable")
    raw = path.read_bytes()
    if len(raw) != metadata.st_size:
        raise ValueError("Telegram projection source changed")
    source = raw.decode("utf-8")
    tree = ast.parse(source)
    declarations: dict[str, ast.stmt] = {}
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.asname or alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [
                item.id
                for target in targets
                for item in ast.walk(target)
                if isinstance(item, ast.Name)
            ]
        for name_key in names:
            if name_key in declarations:
                raise ValueError("Telegram projection duplicate declaration")
            declarations[name_key] = node
    if not roots <= declarations.keys():
        raise ValueError("Telegram projection missing reviewed root")
    selected: set[ast.stmt] = set()
    pending = list(roots)
    while pending:
        node = declarations[pending.pop()]
        if node in selected:
            continue
        selected.add(node)
        pending.extend(
            item.id
            for item in ast.walk(node)
            if isinstance(item, ast.Name)
            and isinstance(item.ctx, ast.Load)
            and item.id in declarations
            and declarations[item.id] not in selected
        )
    selected.update(
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    )
    lines = source.splitlines(keepends=True)
    ordered = [node for node in tree.body if node in selected]
    segments = []
    for node in ordered:
        decorators = getattr(node, "decorator_list", [])
        first = min([node.lineno, *(decorator.lineno for decorator in decorators)])
        segments.append("".join(lines[first - 1 : node.end_lineno]))
    projected = "\n".join(segments).encode("utf-8")
    if [ast.dump(node) for node in ast.parse(projected).body] != [
        ast.dump(node) for node in ordered
    ]:
        raise ValueError("Telegram projection changed executable nodes")
    return projected


def _network_projection(root: Path) -> bytes:
    """Ship the canonical read-only network predicate, not a deploy dispatcher.

    The standalone deploy source remains unchanged. Select its existing AST
    nodes without rewriting or maintaining a second implementation. Missing or
    duplicated definitions fail the build instead of creating a guessed helper.
    """
    path = root / "src" / NETWORK_PROJECTION_NAME
    if path.is_symlink():
        raise ValueError("Telegram network source is a symlink")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_SOURCE_BYTES:
        raise ValueError("Telegram network source missing or oversized")
    source = path.read_bytes()
    if len(source) != metadata.st_size:
        raise ValueError("Telegram network source changed during reading")
    decoded = source.decode("utf-8")
    nodes: dict[str, ast.stmt] = {}
    expected = {
        "ipaddress",
        "BROWSER_EGRESS_BRIDGE",
        "PreflightError",
        "_browser_worker_egress_network",
    }
    for node in ast.parse(source).body:
        name: str | None = None
        if isinstance(node, ast.Import) and len(node.names) == 1:
            name = node.names[0].name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            name = target.id if isinstance(target, ast.Name) else None
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        if name in expected:
            if name in nodes:
                raise ValueError("Telegram network source has duplicate definitions")
            nodes[name] = node
    if set(nodes) != expected:
        raise ValueError("Telegram network source closure incomplete")
    segments = [ast.get_source_segment(decoded, node) for node in nodes.values()]
    if any(segment is None for segment in segments):
        raise ValueError("Telegram network source selection unavailable")
    projected = (
        "\n\n".join(segment for segment in segments if segment is not None) + "\n"
    ).encode()
    if [ast.dump(node) for node in ast.parse(projected).body] != [
        ast.dump(node) for node in nodes.values()
    ]:
        raise ValueError("Telegram network source selection changed executable nodes")
    return projected


def build(root: Path, target: Path, *, installed: bool = False) -> str:
    """Create an immutable deterministic ZIP under runner-only destination."""
    files: dict[str, bytes] = {
        "__main__.py": INSTALLED_MAIN if installed else MAIN,
        **PRIVATE_INITIALIZERS,
    }
    for source_name in INSTALLED_SOURCES if installed else SOURCES:
        source = root / source_name
        if source.is_symlink():
            raise ValueError("reviewed Boca Telegram source is a symlink")
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_SOURCE_BYTES:
            raise ValueError("reviewed Boca Telegram source missing or oversized")
        content = source.read_bytes()
        if len(content) != metadata.st_size:
            raise ValueError("reviewed Boca Telegram source changed during reading")
        bundle_name = source_name.removeprefix("src/")
        if bundle_name in files:
            raise ValueError("duplicate Boca Telegram archive entry")
        files[bundle_name] = (
            _canonical_projection(root, CLEANUP_PROJECTION_NAME, CLEANUP_ROOTS)
            if bundle_name == CLEANUP_PROJECTION_NAME
            else _canonical_projection(
                root, OWNER_PROJECTION_NAME, frozenset({"_controller_owner_subject"})
            )
            if installed and bundle_name == OWNER_PROJECTION_NAME
            else _canonical_projection(root, SERVICE_PROJECTION_NAME, INSTALLED_SERVICE_ROOTS)
            if installed and bundle_name == SERVICE_PROJECTION_NAME
            else _canonical_projection(root, STAGE_PROJECTION_NAME, INSTALLED_STAGE_ROOTS)
            if installed and bundle_name == STAGE_PROJECTION_NAME
            else content
        )
    if NETWORK_PROJECTION_NAME in files:
        raise ValueError("duplicate Telegram network projection")
    files[NETWORK_PROJECTION_NAME] = (
        _canonical_projection(root, NETWORK_PROJECTION_NAME, INSTALLED_DEPLOY_ROOTS)
        if installed
        else _network_projection(root)
    )
    if installed:
        files[INSTALLATION_PROJECTION_NAME] = _canonical_projection(
            root, INSTALLATION_PROJECTION_NAME, frozenset({"OnDemandInstallation"})
        )
    if sum(map(len, files.values())) > MAX_SOURCE_BYTES:
        # Reuse the existing AST/bytecode/line-preserving transform at the same
        # threshold; repository comments remain in the canonical source.
        files = {
            name: _compact_comment_tokens(content, filename=name)
            if name.endswith(".py")
            else content
            for name, content in files.items()
        }
    source_bound = MAX_INSTALLED_SOURCE_BYTES if installed else MAX_SOURCE_BYTES
    if not 0 < sum(len(data) for data in files.values()) <= source_bound:
        raise ValueError("Boca Telegram reviewed source closure exceeds bound")
    if target.is_symlink() or target.exists():
        raise ValueError("Boca Telegram bundle target must be fresh")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as output:
            with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in sorted(files):
                    item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    item.compress_type = zipfile.ZIP_DEFLATED
                    item.create_system = 3
                    item.external_attr = 0o100644 << 16
                    archive.writestr(item, files[name])
            output.flush()
            os.fsync(output.fileno())
        packed = target.read_bytes()
        if not 0 < len(packed) <= MAX_ARCHIVE_BYTES:
            raise ValueError("Boca Telegram compressed closure exceeds bound")
        return hashlib.sha256(packed).hexdigest()
    except Exception:
        # Preserve partially written, now untrusted evidence on failure.
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca-only offline Telegram host archive")
    parser.add_argument("repository_root", type=Path)
    parser.add_argument("runner_target", type=Path)
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    print(
        f"BOCA_TELEGRAM_BUNDLE sha256={build(args.repository_root, args.runner_target, installed=args.installed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
