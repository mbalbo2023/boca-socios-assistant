"""Strict Boca-only read-side adapter for a successor's post-cleanup receipt.

This module never promotes a synthetically built snapshot to physical proof.
All missing host producers remain NO_GO. No secret, database, browser process,
or third-party endpoint is opened; file custody uses O_PATH metadata only.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_same_lease as same_lease
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_upgrade_postflight import PostflightStorage
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

_ROOT = Path("/home/boca-deploy/.local/share/docker")
_DIR_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
_FILES = (
    ("boca-socios_boca_data", "boca.sqlite3"),
    ("boca-socios_boca_key", "boca_master_key"),
    ("boca-socios_boca_owner", "boca_owner_session.sqlite3"),
)
_SITE_FRAME = re.compile(r"BOCA_SITE_URL_SHA256 ([a-f0-9]{64})\n\Z")
_SAVED_URL_PROBE = (
    "from pathlib import Path;"
    "from boca_socios.panel.site_url_settings import SiteUrlSettingsStore;"
    "from boca_socios.browser.site_url_runtime import site_url_fingerprint;"
    "url=SiteUrlSettingsStore.for_database(Path('/data/boca.sqlite3')).read();"
    "print('BOCA_SITE_URL_SHA256 '+site_url_fingerprint(url) "
    "if url is not None else 'BOCA_SITE_URL_UNVERIFIED')"
)
_MIRRORED_URL_PROBE = (
    "from boca_socios.browser.site_url_runtime import read_site_url,site_url_fingerprint;"
    "print('BOCA_SITE_URL_SHA256 '+site_url_fingerprint(read_site_url()))"
)
_WORKER_COMMAND = ["python", "-m", "boca_socios.browser.ipc_server"]


class PostflightRuntimeNoGo(ValueError):
    """Static refusal without filesystem path, secret, Docker or host data."""


def _fail() -> PostflightRuntimeNoGo:
    return PostflightRuntimeNoGo("Boca postflight physical evidence unverified")


def _attest_live_pair(expected: postflight.PostflightExpected, lease: cleanup.BocaJobLease) -> None:
    postflight._validate_expected(expected)
    plan = expected.plan
    cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
    raw = pair.observe(plan.attempt_id)
    postflight._pair_payload(expected, raw)
    installed = service.read_installed_binding(lease)
    binding._attest(plan.attempt_id, raw, installed)


@dataclass(frozen=True, slots=True)
class ProductionSiteUrlWitness:
    """Read the real controller's saved URL and worker mirror as digests only.

    Rootless volume files may be owned by remapped subuids and are not safe to
    infer from the host user's filesystem. After fresh pair/binding attestation
    we run two fixed, bounded, **read-only** commands as the controller's
    already-configured UID10001. Neither the URL nor credentials cross Docker
    stdout; any extra output or changed digest refuses the witness. No worker
    START, browser, Internet or ticket operation occurs. This is still not a
    physical passkey login or proof the CREATED worker has run the URL.
    """

    expected: postflight.PostflightExpected
    lease: cleanup.BocaJobLease

    def _pair(self) -> None:
        _attest_live_pair(self.expected, self.lease)

    def _fingerprint(self, script: str) -> str:
        try:
            self._pair()
            observed = cleanup._docker(
                "exec",
                "--user",
                "10001:10001",
                self.expected.controller_id,
                "/app/.venv/bin/python",
                "-I",
                "-B",
                "-c",
                script,
            )
            match = _SITE_FRAME.fullmatch(observed)
            if match is None or match.group(1) != self.expected.site_url_fingerprint:
                raise _fail()
            cleanup.verify_protected_boca_job_lease(self.lease, self.expected.plan.attempt_id)
            return match.group(1)
        except Exception:
            raise _fail() from None

    def saved_fingerprint(self) -> str:
        return self._fingerprint(_SAVED_URL_PROBE)

    def mirror_fingerprint(self) -> str:
        return self._fingerprint(_MIRRORED_URL_PROBE)

    def worker_startup(self) -> str:
        """Verify cold worker's reviewed IPC entrypoint; do not start it."""
        try:
            self._pair()
            raw = cleanup._docker(
                "inspect", "--format", "{{json .Config.Cmd}}", self.expected.worker_id
            )
            command = json.loads(raw)
            if (
                type(command) is not list
                or command != _WORKER_COMMAND
                or not all(type(value) is str for value in command)
            ):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(self.lease, self.expected.plan.attempt_id)
            # Code+image provenance is checked separately by the authenticated
            # release and R177; this says only what the next START will invoke.
            return "READ_FRESH_FILE_AT_NEXT_START"
        except Exception:
            raise _fail() from None


@dataclass(frozen=True, slots=True)
class ProductionPrivatePanelHealthWitness:
    """Bounded 8443 GET-only HEALTH, never a fabricated passkey login.

    `/healthz` verifies the running controller, the synthetic SQLite event
    and owner-session schema. `/ingresar` creates an owner challenge, so this
    read-only probe deliberately never opens that path and cannot satisfy
    `PostflightSnapshot.panel_loopback_probe=LOGIN_HTTP_200`. Actual owner
    passkey acceptance must be recorded by a separate authenticated action.
    """

    expected: postflight.PostflightExpected
    lease: cleanup.BocaJobLease

    def __call__(self) -> str:
        connection: http.client.HTTPConnection | None = None
        try:
            _attest_live_pair(self.expected, self.lease)
            connection = http.client.HTTPConnection("127.0.0.1", 8443, timeout=2.0)
            connection.request(
                "GET", "/healthz", headers={"Host": "localhost:8443", "Connection": "close"}
            )
            response = connection.getresponse()
            if (
                type(response.status) is not int
                or response.status != 200
                or response.getheader("Content-Length") != "15"
                or response.getheader("Content-Type") != "text/plain; charset=utf-8"
                or response.read(65) != b"BOCA_BETA_READY"
            ):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(self.lease, self.expected.plan.attempt_id)
            return "HEALTH_HTTP_200"
        except Exception:
            raise _fail() from None
        finally:
            if connection is not None:
                connection.close()


def _file_inode_sha256(root: Path, volume: str, name: str) -> str:
    """Hash metadata of one exact Docker volume file using no-follow dirfds."""
    directory_fd = -1
    try:
        directory_fd = os.open("/", _DIR_FLAGS)
        root_parts = root.parts[1:]
        path_parts = (*root_parts, "volumes", volume, "_data")
        for index, part in enumerate(path_parts):
            child_fd = os.open(part, _DIR_FLAGS, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
            folder = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(folder.st_mode)
                or index >= len(root_parts)
                and stat.S_IMODE(folder.st_mode) & 0o022
            ):
                raise _fail()
        file_fd = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
        try:
            item = os.fstat(file_fd)
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        finally:
            os.close(file_fd)
        if (
            not stat.S_ISREG(item.st_mode)
            or item.st_dev != named.st_dev
            or item.st_ino != named.st_ino
            or item.st_mode != named.st_mode
            or item.st_uid != named.st_uid
            or item.st_gid != named.st_gid
            or item.st_nlink != 1
            or stat.S_IMODE(item.st_mode) not in (0o400, 0o600)
            or item.st_uid != os.geteuid()
            or item.st_gid != os.getegid()
            or item.st_dev < 0
            or item.st_ino <= 0
        ):
            raise _fail()
        value = (
            item.st_dev,
            item.st_ino,
            item.st_uid,
            item.st_gid,
            stat.S_IMODE(item.st_mode),
            item.st_nlink,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        return hashlib.sha256(
            b"BOCA_POSTFLIGHT_STORAGE_V1\0" + json.dumps(value, separators=(",", ":")).encode()
        ).hexdigest()
    except (OSError, OverflowError, ValueError, TypeError):
        raise _fail() from None
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def capture_storage_fingerprints(
    rootless_docker_root: Path = _ROOT, *, trusted_root: Path = _ROOT
) -> PostflightStorage:
    """Read only three exact file inodes; never inspect DB/key/session bytes.

    The protected host caller MUST first attest Boca-only rootless DockerRootDir,
    each named volume label/mount, and controller-only data/key/owner mounts.
    Production default refuses any alternative root. Tests may inject a private
    scratch trusted root to exercise no-follow OS behavior without Docker.
    """
    try:
        if (
            not isinstance(rootless_docker_root, Path)
            or not isinstance(trusted_root, Path)
            or not rootless_docker_root.is_absolute()
            or rootless_docker_root != trusted_root
            or rootless_docker_root == Path("/")
        ):
            raise _fail()
        values = [_file_inode_sha256(rootless_docker_root, v, f) for v, f in _FILES]
        result = PostflightStorage(*values)
        result.validate()
        return result
    except Exception:
        raise _fail() from None


def _read_rootless_identity() -> tuple[int, int]:
    return os.geteuid(), os.getegid()


@dataclass(frozen=True, slots=True)
class ProductionPrivateStorageReader:
    """Keep the existing Boca volume attestor injected, not duplicated.

    The protected caller must inject its already-reviewed immutable-root,
    mount and volume-label check under the same lease. The huge initial host
    installer is deliberately NOT imported into the bounded successor ZIP.
    This class fails closed if the trusted attestor is unavailable.
    """

    volume_attestor: Callable[[], None] | None = None

    def __call__(self) -> PostflightStorage:
        try:
            if self.volume_attestor is None or not callable(self.volume_attestor):
                raise _fail()
            self.volume_attestor()
            return capture_storage_fingerprints()
        except Exception:
            raise _fail() from None


def _read_retained_graph(
    pins: adapters.ResourcePins,
    graph: adapters.GraphExpectation,
    attempt: str,
    lease: cleanup.BocaJobLease,
) -> adapters.ResourcePins:
    return adapters.observe_retained(
        pins, graph, attempt, lease, io=same_lease.ProductionRetainedResourceIO()
    )


@dataclass(frozen=True, slots=True)
class PostflightReadSources:
    """Host boundary. Missing site/monitor/login/readback producer is NO_GO.

    These producers are not empty-value defaults. They must come from the
    protected Boca-only run, with independently attested read-only I/O; in
    particular GET `/ingresar` creates a passkey challenge and does not count
    as a mutation-free login probe. No API here supplies that false witness.
    """

    pair_reader: Callable[[str], bytes] = pair.observe
    binding_reader: Callable[[cleanup.BocaJobLease], OnDemandInstallation] = (
        service.read_installed_binding
    )
    retained_reader: Callable[
        [adapters.ResourcePins, adapters.GraphExpectation, str, cleanup.BocaJobLease],
        adapters.ResourcePins,
    ] = _read_retained_graph
    storage_reader: Callable[[], PostflightStorage] | None = None
    rootless_identity_reader: Callable[[], tuple[int, int]] = _read_rootless_identity
    site_saved_reader: Callable[[], str] | None = None
    site_mirror_reader: Callable[[], str] | None = None
    worker_startup_reader: Callable[[], str] | None = None
    panel_login_reader: Callable[[], str] | None = None
    monitor_reader: Callable[[], tuple[str, int]] | None = None
    cleanup_readback: Callable[[], bytes] | None = None


@dataclass(frozen=True, slots=True)
class ProductionPostflightSnapshotReader:
    """One fresh, physical Boca postflight snapshot under the existing lease.

    `postflight.capture_postflight` calls this reader twice and compares all
    values; do not independently acquire or release the lease. It is a
    deliberately incomplete building block until the host proves the missing
    site, mirror, monitor, mutation-free login and durable cleanup sources.
    """

    expected: postflight.PostflightExpected
    sources: PostflightReadSources
    verify_lease: Callable[[cleanup.BocaJobLease, str], None] = (
        cleanup.verify_protected_boca_job_lease
    )

    def __call__(self, lease: cleanup.BocaJobLease) -> postflight.PostflightSnapshot:
        try:
            sources = self.sources
            site_saved_reader = sources.site_saved_reader
            site_mirror_reader = sources.site_mirror_reader
            worker_startup_reader = sources.worker_startup_reader
            panel_login_reader = sources.panel_login_reader
            monitor_reader = sources.monitor_reader
            cleanup_readback = sources.cleanup_readback
            storage_reader = sources.storage_reader
            if (
                type(self.expected) is not postflight.PostflightExpected
                or type(sources) is not PostflightReadSources
                or type(lease) is not cleanup.BocaJobLease
                or not callable(self.verify_lease)
                or site_saved_reader is None
                or storage_reader is None
                or site_mirror_reader is None
                or worker_startup_reader is None
                or panel_login_reader is None
                or monitor_reader is None
                or cleanup_readback is None
                or not all(
                    callable(fn)
                    for fn in (
                        sources.pair_reader,
                        sources.binding_reader,
                        sources.retained_reader,
                        sources.storage_reader,
                        sources.rootless_identity_reader,
                        sources.site_saved_reader,
                        sources.site_mirror_reader,
                        sources.worker_startup_reader,
                        sources.panel_login_reader,
                        sources.monitor_reader,
                        sources.cleanup_readback,
                    )
                )
            ):
                raise _fail()
            postflight._validate_expected(self.expected)
            plan = self.expected.plan
            self.verify_lease(lease, plan.attempt_id)
            if cleanup_readback() != self.expected.cleanup_receipt:
                raise _fail()  # Real durable readback, not a prior in-memory copy.
            pair_raw = sources.pair_reader(plan.attempt_id)
            installed = sources.binding_reader(lease)
            binding._attest(plan.attempt_id, pair_raw, installed)
            observed = postflight._pair_payload(self.expected, pair_raw)
            pair_services = observed.get("services")
            if (
                not isinstance(pair_services, list)
                or len(pair_services) != 2
                or not all(isinstance(item, dict) for item in pair_services)
            ):
                raise _fail()
            controller, worker = cast(list[dict[str, object]], pair_services)
            graph = adapters.GraphExpectation(
                (
                    adapters.ExpectedService(
                        self.expected.controller_id,
                        "controller",
                        plan.new_source_sha,
                        plan.attempt_id,
                        cast(str, controller["image_ref"]),
                    ),
                    adapters.ExpectedService(
                        self.expected.worker_id,
                        "browser-worker",
                        plan.new_source_sha,
                        plan.attempt_id,
                        cast(str, worker["image_ref"]),
                    ),
                )
            )
            retained = sources.retained_reader(
                self.expected.retained, graph, plan.attempt_id, lease
            )
            storage = storage_reader()
            site_saved = site_saved_reader()
            site_mirror = site_mirror_reader()
            worker_startup = worker_startup_reader()
            panel_status = panel_login_reader()
            monitor_source, monitor_count = monitor_reader()
            uid, gid = sources.rootless_identity_reader()
            snapshot = postflight.PostflightSnapshot(
                pair_receipt=pair_raw,
                binding=postflight.PostflightBinding(
                    plan.attempt_id,
                    plan.new_source_sha,
                    installed.controller_id,
                    installed.worker_id,
                    installed.controller_image,
                    installed.worker_image,
                ),
                rootless_uid=uid,
                rootless_gid=gid,
                storage_after=storage,
                retained=retained,
                site_url_saved_fingerprint=site_saved,
                site_url_worker_mirror_fingerprint=site_mirror,
                worker_site_url_startup=worker_startup,
                monitor_source=monitor_source,
                monitor_observation_count=monitor_count,
                panel_loopback_probe=panel_status,
                cleanup_receipt_sha256=hashlib.sha256(self.expected.cleanup_receipt).hexdigest(),
            )
            postflight._validate_snapshot(self.expected, snapshot)
            self.verify_lease(lease, plan.attempt_id)
            return snapshot
        except Exception:
            raise _fail() from None
