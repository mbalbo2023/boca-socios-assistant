"""One real, isolated Boca worker boot; disposable CID, no Cutover or site traffic."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_first_deploy as deploy
from boca_socios import host_on_demand_service as service
from boca_socios import worker_start_capture as capture
from boca_socios.host_on_demand_lifecycle import _RootlessIO, read_panel_status
from boca_socios.host_on_demand_service import read_installed_binding

# Source and published images are *not* the new workflow's implementation SHA.
RELEASE_RUN_ID = "42847341532"
RELEASE_SOURCE_SHA = "31cc6987c30d705113d0323b0700c156fec97eb5"
CONTROLLER_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@"
    "sha256:822e88ca0ff617b94baa180c51261fcc0a40fb9d463bf6aeb61ed5c05ce46fad"
)
BROWSER_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@"
    "sha256:0f181b5eab2954453d2054866682efa94c8dbad577ec2adfa3774e68222070cb"
)
INSTALLED_RUN_ID = "42806447101"
INSTALLED_SOURCE_SHA = "03df9a14bdd78cf768386a865876fed9d5656911"
SECCOMP_SHA256 = "cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849"
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_CID = re.compile(r"[0-9a-f]{64}\Z")
_PROBE_ID = "00000000-0000-4000-8000-000000000001"
_PREFIX = "BOCA_WORKER_PHYSICAL "
_MAX_RECEIPT = 1400
_FIELDS = frozenset(
    {
        "schema",
        "run_id",
        "release_run_id",
        "image_ref",
        "container_id",
        "started",
        "boot",
        "cause",
        "exit_code",
        "oom",
        "controller",
        "engine",
        "installed_worker",
        "cleanup",
        "image_cache",
    }
)


class PhysicalProbeUnavailable(ValueError):
    """An exact Boca host or receipt guard failed; no private data may escape."""


def create_argv(run_id: str, seccomp_path: str) -> tuple[str, ...]:
    """The only Docker create command permitted for this disposable worker."""
    if (
        type(run_id) is not str
        or not _RUN.fullmatch(run_id)
        or type(seccomp_path) is not str
        or not seccomp_path.startswith("/")
        or "\n" in seccomp_path
        or "\x00" in seccomp_path
    ):
        raise PhysicalProbeUnavailable
    return (
        "create",
        "--pull",
        "never",
        "--name",
        f"boca-physical-worker-{run_id}",
        "--label",
        "boca.socios.physical-probe=1",
        "--label",
        f"boca.socios.physical-run={run_id}",
        "--label",
        f"boca.socios.physical-release={RELEASE_RUN_ID}",
        "--user",
        "10002:10002",
        "--restart",
        "no",
        "--log-driver",
        "none",
        "--init",
        "--network",
        "none",
        "--ipc",
        "private",
        "--cgroupns",
        "private",
        "--read-only",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        f"seccomp={seccomp_path}",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "SYS_CHROOT",
        "--pids-limit",
        "128",
        "--memory",
        "768m",
        "--cpus",
        "1.00",
        "--shm-size",
        "64m",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=32m",  # noqa: S108
        "--tmpfs",
        "/home/boca-browser:rw,noexec,nosuid,size=16m",
        "--tmpfs",
        "/run/boca-browser-ipc:rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0711",
        "--env",
        "BOCA_ENVIRONMENT=staging",
        "--env",
        "BOCA_RUNTIME_MODE=simulation",
        "--env",
        "BOCA_ENGINE_MODE=off",
        "--env",
        "BOCA_OBSERVER_STOP=1",
        "--health-cmd",
        "python -m boca_socios.browser.worker_health >/dev/null 2>&1",
        "--health-interval",
        "2s",
        "--health-timeout",
        "3s",
        "--health-retries",
        "3",
        "--health-start-period",
        "5s",
        BROWSER_IMAGE,
        "python",
        "-m",
        "boca_socios.browser.ipc_worker",
    )


def checked(document: object, run_id: str) -> str:
    """Convert ONLY fixed, independently verifiable facts into a public receipt."""
    if (
        type(document) is not dict
        or document.keys() != _FIELDS
        or type(run_id) is not str
        or not _RUN.fullmatch(run_id)
    ):
        raise PhysicalProbeUnavailable
    if (
        type(document["schema"]) is not int
        or document["schema"] != 1
        or document["run_id"] != run_id
        or document["release_run_id"] != RELEASE_RUN_ID
        or document["image_ref"] != BROWSER_IMAGE
        or type(document["container_id"]) is not str
        or not _CID.fullmatch(document["container_id"])
        or document["started"] is not True
        or document["boot"] not in ("HEALTHY", "FAILED")
        or type(document["cause"]) is not str
        or document["controller"] != "HEALTHY"
        or document["engine"] != "STOPPED"
        or document["installed_worker"] != "IDLE"
        or document["cleanup"] != "VERIFIED"
        or document["image_cache"] != "RETAINED"
    ):
        raise PhysicalProbeUnavailable
    cause = document["cause"]
    if (
        cause != "NONE"
        and not capture.is_capture_result(cause)
        and cause
        not in (
            "HEALTH_EXITED",
            "HEALTH_WAIT",
            "HEALTH_UNHEALTHY",
            "HEALTH_TIMEOUT",
            "START_NO_ACK",
        )
        or document["boot"] == "HEALTHY"
        and (cause != "NONE" or document["exit_code"] is not None or document["oom"] is not None)
        or document["boot"] == "FAILED"
        and cause == "NONE"
        or document["exit_code"] is not None
        and (type(document["exit_code"]) is not int or not 0 <= document["exit_code"] <= 255)
        or document["oom"] is not None
        and type(document["oom"]) is not bool
    ):
        raise PhysicalProbeUnavailable
    result = _PREFIX + json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    if len(result.encode("ascii")) > _MAX_RECEIPT:
        raise PhysicalProbeUnavailable
    return result


def _verified_boca_home() -> Path:
    home = service._home()
    info = home.lstat()
    if (
        not home.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != cleanup.EXPECTED_UID
        or info.st_gid != cleanup.EXPECTED_GID
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PhysicalProbeUnavailable
    return home


def _claim_once(home: Path, run_id: str) -> None:
    """One permanent release-specific mark, fsynced BEFORE the single START."""
    name = f".boca-worker-physical-{RELEASE_RUN_ID}.claim"
    try:
        fd = os.open(home / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                data = json.dumps({"run_id": run_id, "release_run_id": RELEASE_RUN_ID}).encode(
                    "ascii"
                )
                if handle.write(data) != len(data):
                    raise PhysicalProbeUnavailable
                handle.flush()
                os.fsync(handle.fileno())
            parent_fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except Exception:
            # On short write or uncertain crash, retain claim to prohibit retry.
            raise PhysicalProbeUnavailable from None
    except OSError:
        raise PhysicalProbeUnavailable from None


def _verify_rootless() -> None:
    if (
        os.geteuid() != cleanup.EXPECTED_UID
        or os.getegid() != cleanup.EXPECTED_GID
        or not deploy._rootless_socket_secure()
    ):
        raise PhysicalProbeUnavailable
    options = json.loads(cleanup._docker("info", "--format", "{{json .SecurityOptions}}"))
    if not isinstance(options, list) or "name=rootless" not in options:
        raise PhysicalProbeUnavailable


def _idle(lease: Any, run_id: str) -> tuple[Any, str]:
    installed = read_installed_binding(lease)
    if (
        installed.installation_run_id != INSTALLED_RUN_ID
        or installed.source_sha != INSTALLED_SOURCE_SHA
    ):
        raise PhysicalProbeUnavailable
    coords = replace(installed.coordinates(_PROBE_ID), attempt_id=run_id)
    io = _RootlessIO(installed)
    observed = io.observe(coords, lease)
    if (
        observed.require(coords) is not False
        or observed.bot_engine_running is not False
        or observed.controller_running is not True
        or observed.controller_healthy is not True
        or io.worker_state(installed.worker_id) not in ("created", "exited")
        or io.field("container", installed.worker_id, "State.Pid") != 0
        or read_panel_status(installed) is not None
    ):
        raise PhysicalProbeUnavailable
    return installed, installed.fingerprint()


def _image_retained() -> None:
    """Pin the one intentionally cached Boca immutable image, no broad pruning."""
    digests = json.loads(
        cleanup._docker("image", "inspect", "--format", "{{json .RepoDigests}}", BROWSER_IMAGE)
    )
    revision = cleanup._docker(
        "image",
        "inspect",
        "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        BROWSER_IMAGE,
    ).strip()
    if (
        not isinstance(digests, list)
        or BROWSER_IMAGE not in digests
        or revision != RELEASE_SOURCE_SHA
    ):
        raise PhysicalProbeUnavailable


def _image_pull_and_verify() -> deploy.StorageSnapshot:
    # Read-only manifest checks happened on the runner. This is the dedicated
    # rootless daemon, with one immutable digest, never a mutable tag.
    before = deploy._storage_snapshot()
    deploy._validate_storage_capacity(before)
    deploy._run("docker", "pull", BROWSER_IMAGE, timeout=180)
    after = deploy._storage_snapshot()
    deploy._validate_storage_continuity(
        before,
        after,
        min_free_bytes=deploy.POSTINSTALL_STORAGE_MIN_BYTES,
    )
    _image_retained()
    return before


def _profile_path(stage: Path) -> str:
    with zipfile.ZipFile(sys.argv[0]) as package:
        data = package.read("docker/seccomp_profile.json")
    if len(data) > 24_000 or hashlib.sha256(data).hexdigest() != SECCOMP_SHA256:
        raise PhysicalProbeUnavailable
    path = stage / "seccomp.json"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        if handle.write(data) != len(data):
            raise PhysicalProbeUnavailable
        handle.flush()
        os.fsync(handle.fileno())
    return str(path)


def _identify_probe(cid: str, run_id: str) -> dict[str, Any]:
    """Exact CID/name/image/labels for compensation even if create flags drift."""
    if not _CID.fullmatch(cid):
        raise PhysicalProbeUnavailable
    record = deploy._browser_inspect_record(cid)
    config = record.get("Config")
    if (
        record.get("Name") != f"/boca-physical-worker-{run_id}"
        or type(config) is not dict
        or config.get("Image") != BROWSER_IMAGE
        or not isinstance(config.get("Labels"), dict)
        or config["Labels"].get("boca.socios.physical-run") != run_id
        or config["Labels"].get("boca.socios.physical-release") != RELEASE_RUN_ID
    ):
        raise PhysicalProbeUnavailable
    return record


def _inspect_probe(cid: str, run_id: str, seccomp_path: str | None = None) -> dict[str, Any]:
    record = _identify_probe(cid, run_id)
    host = record.get("HostConfig")
    if (
        type(host) is not dict
        or host.get("NetworkMode") != "none"
        or host.get("RestartPolicy", {}).get("Name") != "no"
        or host.get("Privileged") is not False
        or host.get("ReadonlyRootfs") is not True
        or host.get("Memory") != 768 * 1024 * 1024
        or host.get("NanoCpus") != 1_000_000_000
        or host.get("PidsLimit") != 128
        or host.get("IpcMode") != "private"
        or host.get("CgroupnsMode") != "private"
        or host.get("LogConfig", {}).get("Type") != "none"
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd") not in (["SYS_CHROOT"], ["CAP_SYS_CHROOT"])
        or host.get("Binds") not in (None, [])
        or record.get("Mounts") != []
        or host.get("Tmpfs")
        != {
            "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108
            "/home/boca-browser": "rw,noexec,nosuid,size=16m",
            "/run/boca-browser-ipc": "rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0711",
        }
    ):
        raise PhysicalProbeUnavailable
    if seccomp_path is not None:
        try:
            deploy._browser_effective_seccomp_options(
                host.get("SecurityOpt"),
                SECCOMP_SHA256,
                staged_profile=Path(seccomp_path).read_bytes(),
            )
        except (OSError, deploy.PreflightError):
            raise PhysicalProbeUnavailable from None
    return record


def _exact_cleanup(cid: str, run_id: str, seccomp_path: str) -> None:
    # NEVER demand successful runtime isolation to delete an owned CID: an
    # incorrectly enforced Docker create must still be compensated by ID.
    record = _identify_probe(cid, run_id)
    state = record.get("State")
    if not isinstance(state, dict) or type(state.get("Running")) is not bool:
        raise PhysicalProbeUnavailable
    if state["Running"]:
        if deploy._run("docker", "stop", "-t", "8", cid, timeout=20) != cid:
            raise PhysicalProbeUnavailable
    if deploy._run("docker", "rm", cid, timeout=25) != cid:
        raise PhysicalProbeUnavailable
    if cleanup._docker("ps", "-a", "-q", "--no-trunc", "--filter", f"id={cid}").strip():
        raise PhysicalProbeUnavailable


def _diagnose(run_id: str) -> dict[str, object]:
    if type(run_id) is not str or not _RUN.fullmatch(run_id):
        raise PhysicalProbeUnavailable
    with cleanup.protected_boca_job_lease(run_id) as lease:
        _verify_rootless()
        installed, fingerprint = _idle(lease, run_id)
        home = _verified_boca_home()
        storage_before = _image_pull_and_verify()
        # No installed volume is mounted. ZIP-owned seccomp lives only while
        # Docker create reads it, and this directory is Boca UID10001 private.
        with tempfile.TemporaryDirectory(prefix=".boca-physical-", dir=home) as name:
            cid: str | None = None
            started = False
            boot = "FAILED"
            cause = "HEALTH_WAIT"
            exit_code: int | None = None
            oom: bool | None = None
            try:
                seccomp_path = _profile_path(Path(name))
                args = create_argv(run_id, seccomp_path)
                # Persist the release's one-attempt claim BEFORE Docker create:
                # even a lost create ACK must not invite a blind second attempt.
                _claim_once(home, run_id)
                cid = deploy._run("docker", *args, timeout=35)
                if not _CID.fullmatch(cid):
                    raise PhysicalProbeUnavailable
                observed = _inspect_probe(cid, run_id, seccomp_path)
                if observed.get("State", {}).get("Status") != "created":
                    raise PhysicalProbeUnavailable
                # This finite Engine attach is armed before starting real code.
                with capture.attach_output(deploy.ROOTLESS_SOCKET, cid) as armed:
                    started = True  # Even lost START ACK consumes the one budget.
                    try:
                        if deploy._run("docker", "start", cid, timeout=35) != cid:
                            raise deploy.PreflightError("start no ACK")
                    except deploy.PreflightError:
                        cause = "START_NO_ACK"
                    else:
                        try:
                            deploy._browser_wait_healthy(cid)
                        except deploy.WorkerHealthPhaseError as exc:
                            cause = (
                                armed.finish().value if exc.phase == "HEALTH_EXITED" else exc.phase
                            )
                            exit_code = exc.exit_code if type(exc.exit_code) is int else None
                            oom = exc.oom_killed if type(exc.oom_killed) is bool else None
                        else:
                            # Effective kernel UID/cgroups/seccomp/no-egress must
                            # also be proven by the disposable running process.
                            deploy._browser_worker_probe(cid)
                            boot = "HEALTHY"
                            cause = "NONE"
            finally:
                if cid is not None:
                    # A lost start ACK can still leave a running process; exact
                    # CID removal is mandatory before any positive receipt.
                    _exact_cleanup(cid, run_id, seccomp_path)
        deploy._validate_storage_continuity(
            storage_before,
            deploy._storage_snapshot(),
            min_free_bytes=deploy.POSTINSTALL_STORAGE_MIN_BYTES,
        )
        _image_retained()
        after, after_fingerprint = _idle(lease, run_id)
        if cid is None or not started or after_fingerprint != fingerprint or after != installed:
            raise PhysicalProbeUnavailable
        return {
            "schema": 1,
            "run_id": run_id,
            "release_run_id": RELEASE_RUN_ID,
            "image_ref": BROWSER_IMAGE,
            "container_id": cid,
            "started": True,
            "boot": boot,
            "cause": cause,
            "exit_code": exit_code,
            "oom": oom,
            "controller": "HEALTHY",
            "engine": "STOPPED",
            "installed_worker": "IDLE",
            "cleanup": "VERIFIED",
            "image_cache": "RETAINED",
        }


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) != 2 or args[0] not in ("host", "verify") or not _RUN.fullmatch(args[1]):
            raise PhysicalProbeUnavailable
        if args[0] == "host":
            for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                signal.signal(sig, lambda _s, _f: (_ for _ in ()).throw(PhysicalProbeUnavailable()))
            document = _diagnose(args[1])
            line = checked(document, args[1])
        else:
            raw = sys.stdin.buffer.read(_MAX_RECEIPT + 1)
            if not raw.startswith(_PREFIX.encode("ascii")) or len(raw) > _MAX_RECEIPT:
                raise PhysicalProbeUnavailable
            document = json.loads(raw[len(_PREFIX) :].decode("ascii"))
            line = checked(document, args[1])
            if line.encode("ascii") != raw:
                raise PhysicalProbeUnavailable
    except BaseException:
        print(_PREFIX + "result=NO_GO")
        return 3
    sys.stdout.write(line)
    return 4 if document["boot"] == "FAILED" and args[0] == "verify" else 0


if __name__ == "__main__":
    raise SystemExit(main())
