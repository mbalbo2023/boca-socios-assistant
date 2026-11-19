"""One-shot G18 Boca-only inventory and reversible rootless shutdown.

Only GitHub Actions may deliver this source. This module reuses the reviewed
binding, Docker census, rootless custody, and lease; no generic Docker MCP,
host prune, database query, backup deletion, or other-project endpoint exists.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_on_demand_service as service
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

INSTALL_SOURCE = "afb0ac0acadbd67e6ccfb7875be4927aaeb43eb8"
CONTROLLER = "cc058236f6f9e5372661c80355ae9454ddc643ed705fcb93c54e3d0741b7c167"
WORKER = "0e0b0c8f1f82f965900bfa462665cfdfb42b8d47e8f089c0d9170d0dc9790548"
PREFIX_INVENTORY = "BOCA_G18_INVENTORY "
PREFIX_STOP = "BOCA_G18_STOP "
MAX_RECEIPT = 24576
MAX_SCAN = 4096
MAX_DEPTH = 5
BACKUP_EXTENSIONS = (
    ".bak",
    ".backup",
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".xz",
    ".sql",
    ".sql.gz",
    ".dump",
    ".snapshot",
)
SAFE_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")


class NoGo(ValueError):
    pass


def _require(value: bool, reason: str = "BOCA_G18_UNVERIFIED") -> None:
    if not value:
        raise NoGo(reason)


def _canonical(prefix: str, value: dict[str, object]) -> str:
    return (
        prefix + json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )


def _attested_pair(run_id: str, lease: cleanup.BocaJobLease) -> tuple[OnDemandInstallation, bytes]:
    installed = service.read_installed_binding(lease)
    observed = pair.observe(run_id)
    binding._attest(run_id, observed, installed)
    _require(
        installed.source_sha == INSTALL_SOURCE
        and installed.controller_id == CONTROLLER
        and installed.worker_id == WORKER
        and installed.installation_run_id == installed.pair.original_browser_attempt
        and not installed.pair.sender_id,
        "INSTALLATION_NOT_G18",
    )
    return installed, observed


def _du_bounded(base: Path) -> dict[str, object]:
    """Metadata only, no follows or reads, under the Boca-owned stage root."""
    result: dict[str, Any] = {
        "state": "ABSENT",
        "files": 0,
        "logical_bytes": 0,
        "allocated_bytes": 0,
        "backups": 0,
        "backup_bytes": 0,
        "logs": 0,
        "log_bytes": 0,
        "symlinks_skipped": 0,
    }
    try:
        first = base.lstat()
    except FileNotFoundError:
        return result
    if not stat.S_ISDIR(first.st_mode) or first.st_uid != cleanup.EXPECTED_UID:
        result["state"] = "UNVERIFIED"
        return result
    result["state"] = "COMPLETE"
    todo = [(base, 0)]
    entries = 0
    while todo:
        directory, depth = todo.pop()
        try:
            with os.scandir(directory) as scan:
                children = list(scan)
        except (PermissionError, OSError):
            result["state"] = "PARTIAL"
            continue
        for entry in children:
            entries += 1
            if entries > MAX_SCAN:
                result["state"] = "PARTIAL_LIMIT"
                return result
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                result["state"] = "PARTIAL"
                continue
            if stat.S_ISLNK(info.st_mode):
                result["symlinks_skipped"] += 1
            elif stat.S_ISDIR(info.st_mode):
                if depth < MAX_DEPTH and info.st_uid == cleanup.EXPECTED_UID:
                    todo.append((Path(entry.path), depth + 1))
                else:
                    result["state"] = "PARTIAL_DEPTH"
            elif stat.S_ISREG(info.st_mode):
                result["files"] += 1
                result["logical_bytes"] += info.st_size
                result["allocated_bytes"] += info.st_blocks * 512
                name = entry.name.lower()
                if name.endswith(BACKUP_EXTENSIONS) or "backup" in name or "snapshot" in name:
                    result["backups"] += 1
                    result["backup_bytes"] += info.st_size
                elif name.endswith(".log") or name.endswith(".log.1"):
                    result["logs"] += 1
                    result["log_bytes"] += info.st_size
    return result


# Read-only metadata in the exact G18 controller. No SQLite connection, SQL,
# database file read, passkey read, HTTP request, or private filename emission.
DB_METADATA = """import json, os, stat
result = {}
for name in ('boca.sqlite3', 'boca.sqlite3-wal', 'boca.sqlite3-shm'):
    try:
        item = os.stat('/data/' + name, follow_symlinks=False)
        result[name] = {'bytes':item.st_size, 'allocated_bytes':item.st_blocks * 512} if stat.S_ISREG(item.st_mode) else None
    except OSError:
        result[name] = None
print(json.dumps(result, sort_keys=True, separators=(',',':')))
"""


def _database_sizes() -> dict[str, object]:
    try:
        raw = cleanup._docker(
            "exec",
            "--user",
            "10001:10001",
            CONTROLLER,
            "/app/.venv/bin/python",
            "-I",
            "-B",
            "-c",
            DB_METADATA,
        )
        result = json.loads(raw)
        _require(
            isinstance(result, dict)
            and set(result) == {"boca.sqlite3", "boca.sqlite3-wal", "boca.sqlite3-shm"},
            "DB_METADATA_INVALID",
        )
        for value in result.values():
            _require(
                value is None
                or (
                    type(value) is dict
                    and set(value) == {"bytes", "allocated_bytes"}
                    and all(type(x) is int and 0 <= x <= 2**48 for x in value.values())
                ),
                "DB_METADATA_INVALID",
            )
        return {"state": "OBSERVED", "files": result}
    except (ValueError, OSError, cleanup.CleanupError):
        return {"state": "UNAVAILABLE", "files": {}}


def _collect(run_id: str, installed: OnDemandInstallation) -> dict[str, object]:
    inventory = cleanup.capture_inventory()
    _require(
        len(inventory.containers) == 2
        and {item.ident for item in inventory.containers} == {CONTROLLER, WORKER}
        and len(inventory.volumes) <= 24
        and len(inventory.images) <= 128,
        "BOCA_RESOURCES_UNVERIFIED",
    )
    by_id = {item.ident: item for item in inventory.containers}
    _require(by_id[CONTROLLER].running and not by_id[WORKER].running, "G18_NOT_IDLE")
    used_images = {item.image_id for item in inventory.containers}
    images = []
    candidates = []
    for item in inventory.images:
        proven = (
            item.source == cleanup.BOCA_SOURCE
            and len(item.references) > 0
            and all(
                any(ref.startswith(prefix) for prefix in cleanup.BOCA_IMAGE_PREFIXES)
                for ref in item.references
            )
        )
        size = None
        if proven:
            try:
                observed_size = cleanup._inspect_field("image", item.ident, "Size")
                if type(observed_size) is int and 0 <= observed_size <= 16 * 1024**3:
                    size = observed_size
            except cleanup.CleanupError:
                pass
        used = item.ident in used_images
        if proven and not used:
            candidates.append({"image_id": item.ident, "logical_bytes": size})
        images.append(
            {
                "image_id": item.ident if proven else "UNCLASSIFIED",
                "used": used,
                "proven_boca": proven,
                "logical_bytes": size,
            }
        )
    volumes = []
    for volume in inventory.volumes:
        labels = cleanup._labels(volume.labels)
        _require(labels.get("com.docker.compose.project") == cleanup.BOCA_PROJECT, "FOREIGN_VOLUME")
        volumes.append(
            {
                "name": volume.name,
                "protected": volume.name in cleanup.PROTECTED_VOLUMES,
                "attached": any(
                    volume.name in container.volumes for container in inventory.containers
                ),
                "logical_bytes": None,
            }
        )
    disk = inventory.disk
    _require(
        all(
            type(x) is int and x >= 0
            for x in (
                disk.bytes_free,
                disk.inodes_free,
                disk.docker_bytes_free,
                disk.docker_inodes_free,
            )
        ),
        "DISK_METADATA_UNVERIFIED",
    )
    accounting = cleanup._read_rootless_storage_usage()
    return {
        "schema": 1,
        "state": "OBSERVED",
        "run_id": run_id,
        "installed_source": installed.source_sha,
        "installation_run": installed.installation_run_id,
        "controller_id": CONTROLLER,
        "worker_id": WORKER,
        "containers": {"total": 2, "running": 1, "created_or_exited": 1},
        "networks": len(inventory.networks),
        "volumes": volumes,
        "image_count": len(inventory.global_image_ids),
        "classified_images": images,
        "unclassified_image_count": len(
            inventory.global_image_ids - {item.ident for item in inventory.images}
        ),
        "reclaimable_image_candidates": candidates,
        "disk": {
            "stage_free_bytes": disk.bytes_free,
            "stage_free_inodes": disk.inodes_free,
            "docker_free_bytes": disk.docker_bytes_free,
            "docker_free_inodes": disk.docker_inodes_free,
        },
        "docker_accounting": accounting,
        "stage_files": _du_bounded(Path("/srv/boca-socios")),
        "database": _database_sizes(),
        "effects": {
            "deleted_images": 0,
            "deleted_volumes": 0,
            "deleted_backups": 0,
            "deleted_databases": 0,
        },
    }


def _unit(name: str) -> dict[str, str]:
    raw = service._systemctl(
        Path("/home/boca-deploy"),
        "show",
        "--all",
        "--property=LoadState,ActiveState,UnitFileState",
        name,
    )
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, mark, value = line.partition("=")
        _require(mark == "=" and key not in fields, "UNIT_METADATA_INVALID")
        fields[key] = value
    _require(
        set(fields) == {"LoadState", "ActiveState", "UnitFileState"}
        and fields["LoadState"] in {"loaded", "not-found"}
        and fields["ActiveState"] in {"active", "inactive", "failed"}
        and fields["UnitFileState"] in {"enabled", "disabled", "static", "masked", ""},
        "UNIT_METADATA_INVALID",
    )
    return fields


def _quiet_unit(name: str, *, optional: bool = False) -> None:
    state = _unit(name)
    if state["LoadState"] == "not-found":
        _require(optional and state["ActiveState"] == "inactive", "UNIT_MISSING")
        return
    _require(state["UnitFileState"] != "masked", "UNIT_MASKED")
    if state["ActiveState"] != "inactive":
        service._systemctl(Path("/home/boca-deploy"), "stop", name)
    if state["UnitFileState"] == "enabled":
        service._systemctl(Path("/home/boca-deploy"), "disable", name)
    after = _unit(name)
    _require(
        after["ActiveState"] == "inactive" and after["UnitFileState"] in {"disabled", "static"},
        "UNIT_STILL_ACTIVE",
    )


def _stop(
    run_id: str, installed: OnDemandInstallation, before: dict[str, object], lease: cleanup.BocaJobLease
) -> dict[str, object]:
    # Last full re-attestation within the same Boca-only lock.
    second, _ = _attested_pair(run_id, lease)
    _require(second == installed, "G18_BINDING_CHANGED")
    final_pre = cleanup.capture_inventory()
    _require(
        {c.ident for c in final_pre.containers} == {CONTROLLER, WORKER}
        and sum(bool(c.running) for c in final_pre.containers) == 1
        and next(c for c in final_pre.containers if c.ident == CONTROLLER).running,
        "PAIR_DRIFTED",
    )
    _require(_unit("docker.service")["LoadState"] == "loaded", "BOCA_DOCKER_UNIT_MISSING")
    _require(
        _unit("boca-bot-control.socket")["LoadState"] == "loaded", "BOCA_ACTIVATION_UNIT_MISSING"
    )
    _quiet_unit("boca-bot-control.socket")
    # Worker is already CREATED/PID0. Stop only the installed controller CID.
    response = cleanup._docker("stop", "--time", "15", CONTROLLER)
    _require(response.strip() == CONTROLLER, "STOP_ACK_MISSING")
    _require(
        cleanup._inspect_field("container", CONTROLLER, "State.Running") is False
        and cleanup._inspect_field("container", WORKER, "State.Running") is False,
        "CONTAINERS_NOT_STOPPED",
    )
    # After explicit per-CID stop, disable only this UID's rootless daemon/socket.
    _quiet_unit("docker.socket", optional=True)
    _quiet_unit("docker.service")
    return {
        "schema": 1,
        "state": "STOPPED",
        "run_id": run_id,
        "installed_source": INSTALL_SOURCE,
        "controller_id": CONTROLLER,
        "worker_id": WORKER,
        "boca_containers": "STOPPED",
        "boca_activation": "INACTIVE_DISABLED",
        "rootless_docker": "INACTIVE_DISABLED",
        "foreign_resources_touched": 0,
        "data_deleted": False,
        "volume_deletions": 0,
        "image_deletions": 0,
        "backup_deletions": 0,
        "restart_allowed": False,
        "inventory_sha256": __import__("hashlib")
        .sha256(_canonical(PREFIX_INVENTORY, before).encode("ascii"))
        .hexdigest(),
    }


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in output, "DUPLICATE_FIELD")
        output[key] = value
    return output


def _verify_inventory_shape(value: dict[str, Any]) -> None:
    _require(
        set(value)
        == {
            "schema",
            "state",
            "run_id",
            "installed_source",
            "installation_run",
            "controller_id",
            "worker_id",
            "containers",
            "networks",
            "volumes",
            "image_count",
            "classified_images",
            "unclassified_image_count",
            "reclaimable_image_candidates",
            "disk",
            "docker_accounting",
            "stage_files",
            "database",
            "effects",
        },
        "INVENTORY_FIELDS",
    )
    containers = value["containers"]
    _require(
        containers == {"total": 2, "running": 1, "created_or_exited": 1}, "INVENTORY_CONTAINERS"
    )
    for name in ("networks", "image_count", "unclassified_image_count"):
        _require(type(value[name]) is int and 0 <= value[name] <= 256, "INVENTORY_COUNTS")
    disk = value["disk"]
    _require(
        type(disk) is dict
        and set(disk)
        == {"stage_free_bytes", "stage_free_inodes", "docker_free_bytes", "docker_free_inodes"}
        and all(type(v) is int and 0 <= v <= 2**60 for v in disk.values()),
        "INVENTORY_DISK",
    )
    cleanup._validate_rootless_disk_accounting(value["docker_accounting"])
    stage = value["stage_files"]
    _require(
        type(stage) is dict
        and set(stage)
        == {
            "state",
            "files",
            "logical_bytes",
            "allocated_bytes",
            "backups",
            "backup_bytes",
            "logs",
            "log_bytes",
            "symlinks_skipped",
        }
        and stage["state"]
        in {"ABSENT", "UNVERIFIED", "COMPLETE", "PARTIAL", "PARTIAL_LIMIT", "PARTIAL_DEPTH"}
        and all(type(v) is int and 0 <= v <= 2**60 for k, v in stage.items() if k != "state"),
        "INVENTORY_STAGE",
    )
    database = value["database"]
    _require(
        type(database) is dict
        and set(database) == {"state", "files"}
        and database["state"] in {"OBSERVED", "UNAVAILABLE"}
        and type(database["files"]) is dict,
        "INVENTORY_DB",
    )
    if database["state"] == "OBSERVED":
        _require(
            set(database["files"]) == {"boca.sqlite3", "boca.sqlite3-wal", "boca.sqlite3-shm"},
            "INVENTORY_DB",
        )
        for item in database["files"].values():
            _require(
                item is None
                or (
                    type(item) is dict
                    and set(item) == {"bytes", "allocated_bytes"}
                    and all(type(x) is int and 0 <= x <= 2**48 for x in item.values())
                ),
                "INVENTORY_DB",
            )
    else:
        _require(database["files"] == {}, "INVENTORY_DB")
    volumes = value["volumes"]
    _require(type(volumes) is list and len(volumes) <= 24, "INVENTORY_VOLUME")
    names = set()
    for item in volumes:
        _require(
            type(item) is dict
            and set(item) == {"name", "protected", "attached", "logical_bytes"}
            and type(item["name"]) is str
            and item["name"].startswith("boca-socios_")
            and cleanup.DOCKER_NAME.fullmatch(item["name"]) is not None
            and type(item["protected"]) is bool
            and type(item["attached"]) is bool
            and item["logical_bytes"] is None
            and item["protected"] == (item["name"] in cleanup.PROTECTED_VOLUMES)
            and item["name"] not in names,
            "INVENTORY_VOLUME",
        )
        names.add(item["name"])
    images = value["classified_images"]
    candidates = value["reclaimable_image_candidates"]
    _require(
        type(images) is list
        and len(images) <= 128
        and type(candidates) is list
        and len(candidates) <= 128,
        "INVENTORY_IMAGES",
    )
    eligible = set()
    for item in images:
        _require(
            type(item) is dict
            and set(item) == {"image_id", "used", "proven_boca", "logical_bytes"}
            and type(item["used"]) is bool
            and type(item["proven_boca"]) is bool
            and (
                item["image_id"] == "UNCLASSIFIED"
                if not item["proven_boca"]
                else cleanup.HEX_ID.fullmatch(item["image_id"]) is not None
            )
            and (
                item["logical_bytes"] is None
                or type(item["logical_bytes"]) is int
                and 0 <= item["logical_bytes"] <= 16 * 1024**3
            ),
            "INVENTORY_IMAGES",
        )
        if item["proven_boca"] and not item["used"]:
            eligible.add((item["image_id"], item["logical_bytes"]))
    seen = set()
    for item in candidates:
        _require(
            type(item) is dict
            and set(item) == {"image_id", "logical_bytes"}
            and (item["image_id"], item["logical_bytes"]) in eligible
            and item["image_id"] not in seen,
            "INVENTORY_CANDIDATES",
        )
        seen.add(item["image_id"])


def verify(raw: bytes, run_id: str) -> dict[str, object]:
    _require(
        type(raw) is bytes and 0 < len(raw) <= MAX_RECEIPT and raw.endswith(b"\n"),
        "INVALID_RECEIPT",
    )
    lines = raw.decode("ascii").splitlines(keepends=True)
    _require(
        len(lines) == 2
        and lines[0].startswith(PREFIX_INVENTORY)
        and lines[1].startswith(PREFIX_STOP),
        "INVALID_RECEIPT",
    )
    inventory = json.loads(lines[0][len(PREFIX_INVENTORY) :], object_pairs_hook=_unique)
    stopped = json.loads(lines[1][len(PREFIX_STOP) :], object_pairs_hook=_unique)
    _require(
        type(inventory) is dict
        and type(stopped) is dict
        and inventory.get("schema") == 1
        and inventory.get("state") == "OBSERVED"
        and stopped.get("schema") == 1
        and stopped.get("state") == "STOPPED"
        and inventory.get("run_id") == stopped.get("run_id") == run_id
        and inventory.get("installed_source") == stopped.get("installed_source") == INSTALL_SOURCE
        and inventory.get("controller_id") == stopped.get("controller_id") == CONTROLLER
        and inventory.get("worker_id") == stopped.get("worker_id") == WORKER
        and inventory.get("effects")
        == {"deleted_images": 0, "deleted_volumes": 0, "deleted_backups": 0, "deleted_databases": 0}
        and stopped.get("rootless_docker") == "INACTIVE_DISABLED"
        and stopped.get("boca_containers") == "STOPPED"
        and stopped.get("data_deleted") is False
        and stopped.get("foreign_resources_touched") == 0
        and stopped.get("volume_deletions") == 0
        and stopped.get("image_deletions") == 0
        and stopped.get("backup_deletions") == 0
        and stopped.get("restart_allowed") is False
        and stopped.get("inventory_sha256")
        == __import__("hashlib").sha256(lines[0].encode("ascii")).hexdigest()
        and lines[0] == _canonical(PREFIX_INVENTORY, inventory)
        and lines[1] == _canonical(PREFIX_STOP, stopped),
        "INVALID_RECEIPT",
    )
    _verify_inventory_shape(inventory)
    return {"inventory": inventory, "stop": stopped}


def main(args: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if args is None else args)
    try:
        _require(
            len(argv) == 3
            and argv[0] in ("host", "verify")
            and SAFE_RUN.fullmatch(argv[1]) is not None
            and re.fullmatch(r"[a-f0-9]{40}", argv[2]) is not None
        )
        run_id, workflow_sha = argv[1:]
        _require(workflow_sha != INSTALL_SOURCE, "WORKFLOW_CODE_NOT_NEW")
        if argv[0] == "verify":
            verify(sys.stdin.buffer.read(MAX_RECEIPT + 1), run_id)
            print(
                "BOCA_G18_VERIFY state=PASS scope=BOCA_UID10001_ONLY "
                "inventory=VERIFIED rootless_docker=STOPPED data_preserved=true"
            )
            return 0
        _require(
            (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) == (cleanup.EXPECTED_UID,) * 4,
            "UID_NOT_BOCA",
        )
        with cleanup.protected_boca_job_lease(run_id) as lease:
            installed, _ = _attested_pair(run_id, lease)
            before = _collect(run_id, installed)
            sys.stdout.write(_canonical(PREFIX_INVENTORY, before))
            sys.stdout.flush()
            stop = _stop(run_id, installed, before, lease)
            sys.stdout.write(_canonical(PREFIX_STOP, stop))
            sys.stdout.flush()
        return 0
    except Exception:
        # Never forward Docker, SQL, host paths, credentials or subprocess stderr.
        if argv and argv[0] == "host":
            sys.stdout.write(
                "BOCA_G18_STOP state=NO_GO physical_state=UNVERIFIED no_automatic_retry=true\n"
            )
        else:
            sys.stdout.write("BOCA_G18_VERIFY state=NO_GO\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
