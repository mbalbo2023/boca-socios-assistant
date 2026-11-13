"""Boca-only R247 postflight source assembly, intentionally not a GO switch.

This adapter binds the existing R245/R246 read-side mechanisms to one exact
protected lease and one *durable, on-disk* final cleanup V2 receipt. It makes
no Docker mutation, HTTP request, browser login, token collection or SQLite
content query. The real Boca rootless host and exact CIDs are reattested by
the underlying R177 pair/binding witness at observation time.

Missing independent owner passkey and truly mutation-free authenticated
monitor producers stay None, so the legacy login-required postflight
refuses the snapshot. Explicit R252 technical capture may use genuine
local GET /healthz (not LOGIN_HTTP_200), while making NO claim about an
authenticated monitor or live tokens. No fabricated owner or authenticated
monitor results are admissible here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as counted
from boca_socios import host_boca_rootless_mapped_custody as mapped
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_postflight_runtime as runtime

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_STRUCTURAL_FILES = (
    ("boca-socios_boca_data", "boca.sqlite3"),
    ("boca-socios_boca_data", "boca_owner_session.sqlite3"),
)
_KEY_FILE = ("boca-socios_boca_key", "boca_master_key")


class PostflightSourcesNoGo(ValueError):
    """Static failure without a path, bearer, host stdout or private data."""


def _fail() -> PostflightSourcesNoGo:
    return PostflightSourcesNoGo("BOCA_POSTFLIGHT_SOURCES_V2 NO_GO")


def _structural_file_inode_sha256(
    root: Path,
    volume: str,
    name: str,
    owner: mapped.MappedOwner,
    *,
    strict_key: bool = False,
) -> str:
    """Hash stable inode custody, not SQLite/session content or write times.

    Descriptor-relative O_PATH/O_NOFOLLOW is used for every ancestor and the
    file. This is intentionally a different v2 hash domain from R245's
    size/mtime-sensitive snapshot. A reviewer must use V2 for BOTH before and
    after references; never compare an old v1 digest as if it were V2.
    """
    directory_fd = -1
    try:
        directory_fd = os.open("/", runtime._DIR_FLAGS)
        root_parts = root.parts[1:]
        for index, part in enumerate((*root_parts, "volumes", volume, "_data")):
            next_fd = os.open(part, runtime._DIR_FLAGS, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
            directory = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(directory.st_mode)
                or index >= len(root_parts)
                and stat.S_IMODE(directory.st_mode) & 0o022
            ):
                raise _fail()
        file_fd = os.open(name, runtime._FILE_FLAGS, dir_fd=directory_fd)
        try:
            opened = os.fstat(file_fd)
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        finally:
            os.close(file_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != named.st_dev
            or opened.st_ino != named.st_ino
            or opened.st_mode != named.st_mode
            or opened.st_uid != named.st_uid
            or opened.st_gid != named.st_gid
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) not in (0o400, 0o600)
            or opened.st_uid != owner.uid
            or opened.st_gid != owner.gid
            or opened.st_dev < 0
            or opened.st_ino <= 0
        ):
            raise _fail()
        identity: tuple[object, ...] = (
            opened.st_dev,
            opened.st_ino,
            opened.st_uid,
            opened.st_gid,
            stat.S_IMODE(opened.st_mode),
            opened.st_nlink,
        )
        if strict_key:
            identity += (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        else:
            identity = (volume, name, *identity)
        return hashlib.sha256(
            (
                b"BOCA_POSTFLIGHT_STORAGE_V1\0"
                if strict_key
                else b"BOCA_POSTFLIGHT_INODE_STRUCTURE_V2\0"
            )
            + json.dumps(identity, separators=(",", ":")).encode("ascii")
        ).hexdigest()
    except Exception:
        raise _fail() from None
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def capture_structural_storage_fingerprints(
    rootless_docker_root: Path = runtime._ROOT,
    *,
    trusted_root: Path = runtime._ROOT,
    mapped_owner: mapped.MappedOwner | None = None,
) -> postflight.PostflightStorage:
    """Stable SQLite/session inode identities and strict key metadata custody.

    Normal SQLite transactions may change file size and mtime/ctime without
    changing the underlying inode. Keep inode, device, owner, mode, hardlink
    count and no-follow mount identity pinned. The master key should not be
    rewritten by routine SQLite activity and retains R245's stronger
    size/mtime-sensitive metadata fingerprint.
    """
    try:
        if (
            not isinstance(rootless_docker_root, Path)
            or not isinstance(trusted_root, Path)
            or not rootless_docker_root.is_absolute()
            or rootless_docker_root != trusted_root
            or rootless_docker_root == Path("/")
            or mapped_owner is None
            and rootless_docker_root == runtime._ROOT
        ):
            raise _fail()
        if mapped_owner is None:
            # Scratch fixtures can explicitly bind their own trusted root;
            # production never infers a remapped owner from host geteuid().
            mapped_owner = mapped.MappedOwner(os.geteuid(), os.getegid())
        if type(mapped_owner) is not mapped.MappedOwner:
            raise _fail()
        data_volume, data_name = _STRUCTURAL_FILES[0]
        session_volume, session_name = _STRUCTURAL_FILES[1]
        key_volume, key_name = _KEY_FILE
        result = postflight.PostflightStorage(
            _structural_file_inode_sha256(
                rootless_docker_root, data_volume, data_name, mapped_owner
            ),
            _structural_file_inode_sha256(
                rootless_docker_root, key_volume, key_name, mapped_owner, strict_key=True
            ),
            _structural_file_inode_sha256(
                rootless_docker_root, session_volume, session_name, mapped_owner
            ),
        )
        result.validate()
        return result
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class ProductionStructuralStorageReader:
    """Lease and exact rootless attested V2 structural storage producer."""

    expected: postflight.PostflightExpected
    lease: cleanup.BocaJobLease
    volume_attestor: Callable[[], None]

    def __call__(self) -> postflight.PostflightStorage:
        try:
            if not callable(self.volume_attestor):
                raise _fail()
            runtime._attest_live_pair(self.expected, self.lease)
            if runtime._read_rootless_identity() != (
                cleanup.EXPECTED_UID,
                cleanup.EXPECTED_GID,
            ):
                raise _fail()
            self.volume_attestor()
            first_owner = mapped.read_controller_mapped_owner(self.expected, self.lease)
            captured = capture_structural_storage_fingerprints(mapped_owner=first_owner)
            self.volume_attestor()
            if mapped.read_controller_mapped_owner(self.expected, self.lease) != first_owner:
                raise _fail()
            runtime._attest_live_pair(self.expected, self.lease)
            return captured
        except Exception:
            raise _fail() from None


def _validated_source_inputs(
    expected: postflight.PostflightExpected,
    lease: cleanup.BocaJobLease,
    receipt: cleanup_runtime.DurableFinalCleanupReceipt,
    receipt_directory: Path,
) -> None:
    postflight._validate_expected(expected)
    if (
        type(lease) is not cleanup.BocaJobLease
        or type(receipt) is not cleanup_runtime.DurableFinalCleanupReceipt
        or receipt.attempt_id != expected.plan.attempt_id
        or receipt.status != "ACCEPT"
        or receipt.apply_authorized is not False
        or type(receipt.raw) is not bytes
        or receipt.raw != expected.cleanup_receipt
        or type(receipt.sha256) is not str
        or receipt.sha256 != hashlib.sha256(receipt.raw).hexdigest()
        or type(receipt.intent_sha256) is not str
        or _DIGEST.fullmatch(receipt.intent_sha256) is None
        or not isinstance(receipt_directory, Path)
        or not receipt_directory.is_absolute()
        or not receipt_directory.name
        or receipt_directory == Path("/")
    ):
        raise _fail()


def build_protected_postflight_sources(
    expected: postflight.PostflightExpected,
    lease: cleanup.BocaJobLease,
    cleanup_receipt: cleanup_runtime.DurableFinalCleanupReceipt,
    *,
    receipt_directory: Path,
    volume_attestor: Callable[[], None] | None = None,
    owner_acceptance: Callable[[], str] | None = None,
    monitor_metadata: Callable[[], bytes] | None = None,
) -> runtime.PostflightReadSources:
    """Bind real Boca-only *readers* for the one ongoing protected attempt.

    The caller must obtain `receipt_directory` from the attested same-lease
    cleanup coordinates and supply its pre-reviewed Boca data/key/owner volume
    + mount attestor. The function itself does not touch the host; invocation
    of the returned callbacks rechecks the exact pair, rootless identity,
    lease, saved SITE_URL, cold worker entrypoint, and durable cleanup receipt.

    No available code can authenticate an owner's actual Chrome/passkey login
    merely by visiting /healthz. Likewise, no read-only production monitor
    source exists that avoids the owner-session renewal. Until independently
    reviewed producers exist, non-None callbacks for these two sources are
    rejected instead of interpreted as optimistic status strings.
    """
    try:
        _validated_source_inputs(expected, lease, cleanup_receipt, receipt_directory)
        if owner_acceptance is not None or monitor_metadata is not None:
            raise _fail()
        if volume_attestor is not None and not callable(volume_attestor):
            raise _fail()

        def durable_cleanup_readback() -> bytes:
            directory_fd = -1
            try:
                runtime._attest_live_pair(expected, lease)
                if runtime._read_rootless_identity() != (
                    cleanup.EXPECTED_UID,
                    cleanup.EXPECTED_GID,
                ):
                    raise _fail()
                cleanup.verify_protected_boca_job_lease(lease, expected.plan.attempt_id)
                directory_fd, identity = cleanup_runtime._private_directory(receipt_directory)
                _, receipt_name = cleanup_runtime.final_cleanup_filenames(expected.plan.attempt_id)
                raw = cleanup_runtime._read_private(
                    directory_fd,
                    receipt_name,
                    bound=counted.MAX_RECEIPT_BYTES,
                )
                cleanup_runtime._directory_unchanged(directory_fd, receipt_directory, identity)
                if (
                    raw != cleanup_receipt.raw
                    or hashlib.sha256(raw).hexdigest() != cleanup_receipt.sha256
                ):
                    raise _fail()
                cleanup.verify_protected_boca_job_lease(lease, expected.plan.attempt_id)
                runtime._attest_live_pair(expected, lease)
                return raw
            except Exception:
                raise _fail() from None
            finally:
                if directory_fd >= 0:
                    os.close(directory_fd)

        site = runtime.ProductionSiteUrlWitness(expected, lease)
        storage: Callable[[], postflight.PostflightStorage] | None = None
        if volume_attestor is not None:
            storage = ProductionStructuralStorageReader(expected, lease, volume_attestor)
        return runtime.PostflightReadSources(
            storage_reader=storage,
            site_saved_reader=site.saved_fingerprint,
            site_mirror_reader=site.mirror_fingerprint,
            worker_startup_reader=site.worker_startup,
            panel_health_reader=runtime.ProductionPrivatePanelHealthWitness(expected, lease),
            # A closed worker and healthy /healthz do NOT prove owner passkey.
            panel_login_reader=None,
            # An in-memory monitor with no genuine owner source is not proof.
            monitor_reader=None,
            cleanup_readback=durable_cleanup_readback,
        )
    except Exception:
        raise _fail() from None
