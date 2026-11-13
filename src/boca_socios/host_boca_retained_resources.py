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
from enum import Enum
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
_FAILURE_PREFIX = b"BOCA_RETAINED_RESOURCES_FAILURE "
_FAILURE_BOUND = 512
_STDERR_BOUND = 1024


class Phase(str, Enum):  # noqa: UP042 - protected host also supports Python 3.10
    """Closed public vocabulary, never derived from host exception text."""

    UNVERIFIED = "UNVERIFIED"
    INVENTORY = "INVENTORY"
    PAIR = "PAIR"
    IPC_IDENTITY = "IPC_IDENTITY"
    SITE_IDENTITY = "SITE_IDENTITY"
    EGRESS = "EGRESS"
    IMAGE_PROVENANCE = "IMAGE_PROVENANCE"
    CONTROL_IDENTITY = "CONTROL_IDENTITY"
    SNAPSHOT_VALIDATION = "SNAPSHOT_VALIDATION"
    DRIFT = "DRIFT"
    BUNDLE_UNVERIFIED = "BUNDLE_UNVERIFIED"
    TRANSPORT_UNVERIFIED = "TRANSPORT_UNVERIFIED"
    RECEIPT_UNVERIFIED = "RECEIPT_UNVERIFIED"


class ResourceNoGo(ValueError):
    """Only a fixed error category may cross the protected host boundary."""

    def __init__(self, phase: Phase = Phase.UNVERIFIED) -> None:
        self.phase = phase if isinstance(phase, Phase) else Phase.UNVERIFIED
        super().__init__("retained Boca resource evidence unverified")


def _fail(phase: Phase = Phase.UNVERIFIED) -> ResourceNoGo:
    return ResourceNoGo(phase)


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def control_identity_path(name: str) -> Path:
    """Return only a fixed Boca resource path or an exact attempt PARK path."""
    if name in _PATHS:
        return _PATHS[name]
    prefix = "parked_control_socket_directory:"
    if type(name) is not str or not name.startswith(prefix):
        raise _fail()
    attempt = name.removeprefix(prefix)
    if _RUN.fullmatch(attempt) is None:
        raise _fail()
    return Path(f"/home/boca-deploy/.boca-on-demand-parked-{attempt}/socket")


def _identity(name: str) -> str:
    """O_PATH/fstat only, no-follow at every ancestor; never open file data."""
    path = control_identity_path(name)
    try:
        root = json.loads(cleanup._docker("info", "--format", "{{json .DockerRootDir}}"))
    except (TypeError, ValueError):
        raise _fail() from None
    if root != str(_ROOT):
        raise _fail()
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
    phase = Phase.INVENTORY
    try:
        inventory = inventory_reader()  # Foreign presence fails before detailed reads.
        phase = Phase.PAIR
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
            phase = Phase.IPC_IDENTITY if name == _IPC else Phase.SITE_IDENTITY
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
        phase = Phase.EGRESS
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
        phase = Phase.IMAGE_PROVENANCE
        images = []
        for image in sorted(inventory.images, key=lambda i: i.ident):
            proven = image.source == cleanup.BOCA_SOURCE
            # Boca-like tags or historical unproven images are not promoted by name.
            refs = list(image.references) if proven else []
            if any(
                not (
                    _matches(cleanup.BOCA_PUBLIC_DIGEST, ref)
                    or _matches(cleanup.BOCA_PUBLIC_SHA_TAG, ref)
                )
                for ref in refs
            ):
                raise _fail()
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
        phase = Phase.CONTROL_IDENTITY
        control_identity = identity_reader("control_socket_directory")
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
            "control_socket_directory_inode_sha256": control_identity,
            "bind_mounts": "PAIR_VERIFIED_EXACT",
            "expected_resource_provenance": volumes[0]["creator_attempt"] == "42806447101"
            and volumes[1]["creator_attempt"] == installed.FAILED_ATTEMPT
            and egress["creator_attempt"] == installed.FAILED_ATTEMPT,
            "observer_writes": 0,
            "successor_apply_authorized": False,
        }
        phase = Phase.SNAPSHOT_VALIDATION
        _validate(result, run_id)
        return result
    except Exception:
        raise _fail(phase) from None


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
            raise _fail(Phase.DRIFT)
        raw = _PREFIX + _canonical(first) + b"\n"
        return verify(raw, run_id)
    except ResourceNoGo as exc:
        if exc.phase != Phase.UNVERIFIED:
            raise
        raise _fail(Phase.SNAPSHOT_VALIDATION) from None
    except Exception:
        raise _fail(Phase.SNAPSHOT_VALIDATION) from None


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


def _failure(run_id: str, phase: Phase) -> bytes:
    if not _matches(_RUN, run_id) or not isinstance(phase, Phase):
        raise _fail()
    return (
        _FAILURE_PREFIX
        + _canonical(
            {
                "schema": 1,
                "state": "NO_GO",
                "observation_run_id": run_id,
                "phase": phase.value,
                "observer_writes": 0,
                "successor_apply_authorized": False,
            }
        )
        + b"\n"
    )


def _verify_failure(raw: bytes, run_id: str) -> bytes:
    """Exact canonical frame rejects duplicates, extensions and free-form errors."""
    try:
        if not 0 < len(raw) <= _FAILURE_BOUND or not raw.startswith(_FAILURE_PREFIX):
            raise _fail()
        value = json.loads(raw[len(_FAILURE_PREFIX) :])
        expected = _failure(run_id, Phase(value["phase"]))
        if raw != expected:
            raise _fail()
        return expected
    except Exception:
        raise _fail() from None


def report(run_id: str, remote_rc: int, stdout: bytes, stderr: bytes) -> tuple[bytes, int]:
    """Runner-only classifier: a remote failure can never authorize success."""
    if not _matches(_RUN, run_id):
        raise _fail()
    if remote_rc == 0:
        try:
            if stderr:
                raise _fail()
            return verify(stdout, run_id), 0
        except Exception:
            return _failure(run_id, Phase.RECEIPT_UNVERIFIED), 1
    if remote_rc == 3 and not stderr:
        try:
            return _verify_failure(stdout, run_id), 1
        except ResourceNoGo:
            pass
    if (
        remote_rc == 1
        and not stdout
        and stderr == b"BOCA_BUNDLE state=NO_GO reason=hash_or_host_runtime\n"
    ):
        return _failure(run_id, Phase.BUNDLE_UNVERIFIED), 1
    return _failure(run_id, Phase.TRANSPORT_UNVERIFIED), 1


def main() -> int:
    if len(sys.argv) == 6 and sys.argv[1] == "report":
        try:
            # Runner-private files only. Never read more than the public bounds.
            with Path(sys.argv[4]).open("rb") as receipt, Path(sys.argv[5]).open("rb") as error:
                raw, status = report(
                    sys.argv[2],
                    int(sys.argv[3]),
                    receipt.read(_BOUND + 1),
                    error.read(_STDERR_BOUND + 1),
                )
        except Exception:
            if not _matches(_RUN, sys.argv[2]):
                return 3
            raw, status = _failure(sys.argv[2], Phase.TRANSPORT_UNVERIFIED), 1
        sys.stdout.buffer.write(raw)
        return status
    if (
        len(sys.argv) != 3
        or sys.argv[1] not in ("host", "verify")
        or not _matches(_RUN, sys.argv[2])
    ):
        return 3
    try:
        raw = (
            observe(sys.argv[2])
            if sys.argv[1] == "host"
            else verify(sys.stdin.buffer.read(_BOUND + 1), sys.argv[2])
        )
    except ResourceNoGo as exc:
        sys.stdout.buffer.write(_failure(sys.argv[2], exc.phase))
        return 3
    except Exception:
        sys.stdout.buffer.write(_failure(sys.argv[2], Phase.UNVERIFIED))
        return 3
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":  # pragma: no cover - protected host transport
    raise SystemExit(main())
