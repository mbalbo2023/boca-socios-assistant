"""Read-only, non-authorizing resource witness for the finalized R183 pair.

Container installation attempts are not resource creation attempts. Observe
the retained IPC/SITE volumes and egress without adopting, relabeling or
removing anything. Never read Env, SQLite bytes, SITE_URL or credentials.
The observer is intentionally NOT wired to an effectful upgrade entrypoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_postcommit as installed

_IPC = "boca-socios_boca_browser_ipc"
_SITE = "boca-socios_boca_site_config"
_EGRESS = "boca-socios_boca_browser_egress"
_ATTEMPT = "boca.socios.browser-ipc-attempt"
_ROOT = Path("/home/boca-deploy/.local/share/docker")
_PATHS = {
    _IPC: _ROOT / "volumes" / _IPC / "_data",
    _SITE: _ROOT / "volumes" / _SITE / "_data",
    "control_socket_directory": Path("/home/boca-deploy/.boca-on-demand/socket"),
}
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_PREFIX = b"BOCA_RETAINED_RESOURCES "
_BOUND = 48_000


class ResourceNoGo(ValueError):
    """Only a fixed error category may cross the protected host boundary."""


def _fail() -> ResourceNoGo:
    return ResourceNoGo("retained Boca resource evidence unverified")


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _identity(name: str) -> str:
    """O_PATH/fstat only, no-follow at every ancestor; never open file data."""
    if name not in _PATHS or cleanup._docker("info", "--format", "{{.DockerRootDir}}") != str(
        _ROOT
    ):
        raise _fail()
    path = _PATHS[name]
    if name in (_IPC, _SITE):
        metadata = json.loads(
            cleanup._docker(
                "volume",
                "inspect",
                "--format",
                '{"name":{{json .Name}},"driver":{{json .Driver}},"scope":{{json .Scope}},'
                '"options":{{json .Options}},"mountpoint":{{json .Mountpoint}}}',
                name,
            )
        )
        if metadata not in (
            {
                "name": name,
                "driver": "local",
                "scope": "local",
                "options": None,
                "mountpoint": str(path),
            },
            {
                "name": name,
                "driver": "local",
                "scope": "local",
                "options": {},
                "mountpoint": str(path),
            },
        ):
            raise _fail()
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        item = os.fstat(fd)
        if not stat.S_ISDIR(item.st_mode) or item.st_ino <= 0:
            raise _fail()
        # Equality witness only; raw host inode, UID and paths stay private.
        return hashlib.sha256(
            _canonical(
                [
                    item.st_dev,
                    item.st_ino,
                    item.st_uid,
                    item.st_gid,
                    stat.S_IMODE(item.st_mode),
                    item.st_nlink,
                ]
            )
        ).hexdigest()
    finally:
        os.close(fd)


def _creator(labels: tuple[tuple[str, str], ...], role_key: str, role: str) -> str:
    value = dict(labels)
    attempt = value.get(_ATTEMPT)
    if (
        len(value) != len(labels)
        or value.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
        or value.get(role_key) != role
        or not _matches(_RUN, attempt)
    ):
        raise _fail()
    return str(attempt)


def _revision(image: str) -> str | None:
    return cleanup._inspect_image_public_oci_label(image, "org.opencontainers.image.revision")


def snapshot(
    run_id: str,
    *,
    inventory_reader: Callable[[], cleanup.Inventory] = cleanup.capture_inventory,
    pair_reader: Callable[[str], bytes] = pair.observe,
    identity_reader: Callable[[str], str] = _identity,
    revision_reader: Callable[[str], str | None] = _revision,
) -> dict[str, object]:
    """Capture only a positively identified fixed Boca pair and retained graph."""
    if not _matches(_RUN, run_id):
        raise _fail()
    try:
        inventory = inventory_reader()  # Foreign presence fails before detailed reads.
        raw = pair_reader(run_id)
        pair.verify(raw, run_id)
        observed = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
        services = observed["services"]
        if (
            observed["source_sha"] != installed.SOURCE_SHA
            or observed["attempt_id"] != installed.FAILED_ATTEMPT
            or [s["container_id"] for s in services]
            != [installed.CONTROLLER_ID, installed.WORKER_ID]
            or [s["image_ref"] for s in services]
            != [installed.CONTROLLER_IMAGE, installed.WORKER_IMAGE]
            or services[0]["health"] != "healthy"
            or services[0]["running"] is not True
            or services[1]["status"] != "created"
            or services[1]["pid"] != 0
            or services[1]["exit_code"] != 0
            or len(inventory.containers) != 2
            or {c.ident for c in inventory.containers}
            != {installed.CONTROLLER_ID, installed.WORKER_ID}
            or any(
                c.image_id != next(s["image_id"] for s in services if s["container_id"] == c.ident)
                for c in inventory.containers
            )
        ):
            raise _fail()
        volumes = []
        for name, role in ((_IPC, "boca_browser_ipc"), (_SITE, "boca_site_config")):
            selected = [v for v in inventory.volumes if v.name == name]
            if len(selected) != 1:
                raise _fail()
            volumes.append(
                {
                    "name": name,
                    "creator_attempt": _creator(
                        selected[0].labels, "com.docker.compose.volume", role
                    ),
                    "inode_sha256": identity_reader(name),
                    "container_references": sum(name in c.volumes for c in inventory.containers),
                }
            )
        networks = [n for n in inventory.networks if n.name == _EGRESS]
        if len(networks) != 1 or networks[0].attached_ids:
            raise _fail()
        network = networks[0]
        if services[1]["network_id"] not in ("UNATTACHED", network.ident):
            raise _fail()
        egress = {
            "name": _EGRESS,
            "id": network.ident,
            "peer_ids": [],
            "creator_attempt": _creator(
                network.labels, "com.docker.compose.network", "boca_browser_egress"
            ),
        }
        images = []
        for image in sorted(inventory.images, key=lambda i: i.ident):
            proven = image.source == cleanup.BOCA_SOURCE
            # Boca-like tags or historical unproven images are not promoted by name.
            refs = list(image.references) if proven else []
            revision = revision_reader(image.ident) if proven else None
            active = [s for s in services if s["image_id"] == image.ident]
            if active and (
                not proven
                or revision != installed.SOURCE_SHA
                or any(s["image_ref"] not in refs for s in active)
            ):
                raise _fail()
            images.append(
                {
                    "id": image.ident,
                    "references": refs,
                    "revision": revision if revision is not None else "UNKNOWN",
                    "source_verified": proven,
                    "container_references": sum(
                        c.image_id == image.ident for c in inventory.containers
                    ),
                }
            )
        result: dict[str, object] = {
            "schema": 1,
            "state": "READ_ONLY",
            "observation_run_id": run_id,
            "installation_attempt": installed.FAILED_ATTEMPT,
            "source_sha": installed.SOURCE_SHA,
            "volumes": volumes,
            "egress": egress,
            "images": images,
            "unclassified_image_count": len(
                inventory.global_image_ids - {i.ident for i in inventory.images}
            ),
            "control_socket_directory_inode_sha256": identity_reader("control_socket_directory"),
            "bind_mounts": "PAIR_VERIFIED_EXACT",
            "expected_resource_provenance": volumes[0]["creator_attempt"] == "42806447101"
            and volumes[1]["creator_attempt"] == installed.FAILED_ATTEMPT
            and egress["creator_attempt"] == installed.FAILED_ATTEMPT,
            "observer_writes": 0,
            "successor_apply_authorized": False,
        }
        _validate(result, run_id)
        return result
    except Exception:
        raise _fail() from None


def _validate(value: object, run_id: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "state",
        "observation_run_id",
        "installation_attempt",
        "source_sha",
        "volumes",
        "egress",
        "images",
        "unclassified_image_count",
        "control_socket_directory_inode_sha256",
        "bind_mounts",
        "expected_resource_provenance",
        "observer_writes",
        "successor_apply_authorized",
    }:
        raise _fail()
    if (
        type(value["schema"]) is not int
        or value["schema"] != 1
        or value["state"] != "READ_ONLY"
        or value["observation_run_id"] != run_id
        or value["installation_attempt"] != installed.FAILED_ATTEMPT
        or value["source_sha"] != installed.SOURCE_SHA
        or value["bind_mounts"] != "PAIR_VERIFIED_EXACT"
        or type(value["observer_writes"]) is not int
        or value["observer_writes"] != 0
        or value["successor_apply_authorized"] is not False
        or not _matches(_HEX, value["control_socket_directory_inode_sha256"])
        or type(value["unclassified_image_count"]) is not int
        or not 0 <= value["unclassified_image_count"] <= cleanup.MAX_OBJECTS
    ):
        raise _fail()
    volumes, network, images = value["volumes"], value["egress"], value["images"]
    if not isinstance(volumes, list) or len(volumes) != 2:
        raise _fail()
    for volume, name in zip(volumes, (_IPC, _SITE), strict=True):
        if (
            not isinstance(volume, dict)
            or set(volume) != {"name", "creator_attempt", "inode_sha256", "container_references"}
            or volume["name"] != name
            or not _matches(_RUN, volume["creator_attempt"])
            or not _matches(_HEX, volume["inode_sha256"])
            or type(volume["container_references"]) is not int
            or volume["container_references"] != 2
        ):
            raise _fail()
    if (
        not isinstance(network, dict)
        or set(network) != {"name", "id", "peer_ids", "creator_attempt"}
        or network["name"] != _EGRESS
        or not _matches(_HEX, network["id"])
        or network["peer_ids"] != []
        or not _matches(_RUN, network["creator_attempt"])
    ):
        raise _fail()
    expected = (
        volumes[0]["creator_attempt"] == "42806447101"
        and volumes[1]["creator_attempt"] == installed.FAILED_ATTEMPT
        and network["creator_attempt"] == installed.FAILED_ATTEMPT
    )
    if value["expected_resource_provenance"] is not expected:
        raise _fail()
    if not isinstance(images, list) or not 2 <= len(images) <= cleanup.MAX_OBJECTS:
        raise _fail()
    ids = []
    for image in images:
        if (
            not isinstance(image, dict)
            or set(image)
            != {"id", "references", "revision", "source_verified", "container_references"}
            or not _matches(_IMAGE, image["id"])
            or type(image["source_verified"]) is not bool
            or type(image["container_references"]) is not int
            or not 0 <= image["container_references"] <= 2
            or not isinstance(image["references"], list)
            or len(image["references"]) > 32
            or any(
                not (
                    _matches(cleanup.BOCA_PUBLIC_DIGEST, ref)
                    or _matches(cleanup.BOCA_PUBLIC_SHA_TAG, ref)
                )
                for ref in image["references"]
            )
            or image["references"] != sorted(set(image["references"]))
            or not (image["revision"] == "UNKNOWN" or _matches(_SHA, image["revision"]))
            or (
                not image["source_verified"]
                and (image["references"] or image["revision"] != "UNKNOWN")
            )
        ):
            raise _fail()
        ids.append(image["id"])
    if ids != sorted(set(ids)) or sum(i["container_references"] for i in images) != 2:
        raise _fail()
    for reference in (installed.CONTROLLER_IMAGE, installed.WORKER_IMAGE):
        matches = [image for image in images if reference in image["references"]]
        if (
            len(matches) != 1
            or matches[0]["container_references"] != 1
            or matches[0]["source_verified"] is not True
            or matches[0]["revision"] != installed.SOURCE_SHA
        ):
            raise _fail()


def observe(
    run_id: str, *, snapshot_reader: Callable[[str], dict[str, object]] = snapshot
) -> bytes:
    """Two stable full captures; no lease, marker, Docker exec or mutation."""
    if not _matches(_RUN, run_id):
        raise _fail()
    try:
        first, second = snapshot_reader(run_id), snapshot_reader(run_id)
        _validate(first, run_id)
        _validate(second, run_id)
        if first != second:
            raise _fail()
        raw = _PREFIX + _canonical(first) + b"\n"
        return verify(raw, run_id)
    except Exception:
        raise _fail() from None


def verify(raw: bytes, run_id: str) -> bytes:
    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise _fail()
            value[key] = item
        return value

    try:
        if (
            not _matches(_RUN, run_id)
            or type(raw) is not bytes
            or not 0 < len(raw) <= _BOUND
            or not raw.startswith(_PREFIX)
            or not raw.endswith(b"\n")
            or raw.count(b"\n") != 1
        ):
            raise _fail()
        value = json.loads(raw[len(_PREFIX) : -1], object_pairs_hook=unique)
        _validate(value, run_id)
        if raw != _PREFIX + _canonical(value) + b"\n":
            raise _fail()
        return raw
    except Exception:
        raise _fail() from None


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("host", "verify"):
        return 3
    try:
        raw = (
            observe(sys.argv[2])
            if sys.argv[1] == "host"
            else verify(sys.stdin.buffer.read(_BOUND + 1), sys.argv[2])
        )
    except Exception:
        print("BOCA_RETAINED_RESOURCES state=NO_GO reason=UNVERIFIED observer_writes=0")
        return 3
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":  # pragma: no cover - protected host transport
    raise SystemExit(main())
