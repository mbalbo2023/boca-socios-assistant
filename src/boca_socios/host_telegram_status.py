"""Publish the last verified installed observation, never an inferred heartbeat."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from boca_socios import telegram_bootstrap as bootstrap

if TYPE_CHECKING:
    from boca_socios.host_telegram_installed_context import InstalledTelegramContext
    from boca_socios.host_telegram_maintenance import InstalledMaintenance


# Executed in the exact installed controller, never in the host namespace.
# Both parsers below are present, unchanged, in installed R845f31ab.
PUBLIC_OBSERVE_PROGRAM = r"""
import errno, hashlib, json, os, re, stat, sys
from datetime import UTC, datetime
from pathlib import Path

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

def witness(meta):
    return (meta.st_dev, meta.st_ino, meta.st_mode, meta.st_uid, meta.st_gid,
            meta.st_nlink, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)

def empty(kind, state):
    fields = ("source_sha", "installation_fingerprint", "fingerprint") if kind == "recipient" else (
        "source_sha", "observation_run_id", "installation_run_id", "controller_id", "worker_id",
        "sender_id", "observed_at", "configured", "paired", "sender", "human_receipt")
    return {"state": state, "digest": None, "witness": None, **dict.fromkeys(fields)}

def observe(kind, name, maximum, mode):
    result = empty(kind, "NOT_READ")
    descriptors = []
    parent = None
    before = None
    leaf = None
    try:
        if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10001,) * 4:
            return result
        from boca_socios import telegram_bootstrap as bootstrap
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root = os.open("/", flags)
        descriptors.append(root)
        metadata = os.stat("data", dir_fd=root, follow_symlinks=False)
        before = witness(metadata)
        if (not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700
                or (metadata.st_uid, metadata.st_gid) != (10001, 10001)):
            if witness(os.stat("data", dir_fd=root, follow_symlinks=False)) != before:
                return empty(kind, "CHANGED")
            result["state"] = "INVALID"
            result["witness"] = hashlib.sha256(canonical([before, None])).hexdigest()
            return result
        parent = bootstrap._directory(Path("/data"), 10001)
        descriptors.append(parent)
        if witness(os.fstat(parent)) != before:
            return empty(kind, "CHANGED")
        try:
            metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            result["state"] = "ABSENT"
        else:
            leaf = witness(metadata)
            if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != mode
                    or (metadata.st_uid, metadata.st_gid) != (10001, 10001)
                    or metadata.st_nlink != 1 or not 0 < metadata.st_size <= maximum):
                result["state"] = "INVALID"
            else:
                try:
                    if kind == "recipient":
                        raw = bootstrap._read(parent, name, 10001, maximum=maximum)
                    else:
                        from boca_socios.notify.projection import _read_admin_receipt
                        raw = _read_admin_receipt(Path("/data") / name)
                except Exception:
                    result = empty(kind, "NOT_READ")
                else:
                    try:
                        value = json.loads(raw, object_pairs_hook=bootstrap._unique)
                        source = value["source_sha"]
                        if type(source) is not str or re.fullmatch(r"[a-f0-9]{40}", source) is None:
                            raise ValueError("source")
                        if kind == "recipient":
                            from boca_socios.panel.telegram_recipient import _document
                            recipient, fingerprint = _document(raw, source)
                            result.update(source_sha=source, installation_fingerprint=fingerprint,
                                          fingerprint=recipient.fingerprint)
                        else:
                            from boca_socios.notify.projection import parse_telegram_admin_receipt
                            parsed = parse_telegram_admin_receipt(raw, expected_source_sha=source,
                                                                  now=datetime.now(UTC))
                            result.update({field: value[field] for field in result
                                           if field not in ("state", "digest", "witness")})
                            if parsed.observation_run_id != result["observation_run_id"]:
                                raise ValueError("run")
                        result.update(state="VALID", digest=hashlib.sha256(raw).hexdigest())
                    except ImportError:
                        result = empty(kind, "NOT_READ")
                    except Exception:
                        result = empty(kind, "INVALID")
        try:
            after = witness(os.stat(name, dir_fd=parent, follow_symlinks=False))
        except FileNotFoundError:
            after = None
        if (after != leaf or witness(os.fstat(parent)) != before
                or witness(os.stat("data", dir_fd=root, follow_symlinks=False)) != before):
            return empty(kind, "CHANGED")
        result["witness"] = hashlib.sha256(canonical([before, leaf])).hexdigest()
        return result
    except OSError as error:
        result = empty(kind, "CHANGED" if error.errno == errno.ENOENT and before is not None
                       else "INVALID" if error.errno in (errno.ELOOP, errno.ENOTDIR)
                       else "NOT_READ")
        return result
    except Exception:
        return empty(kind, "NOT_READ")
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)

sys.stdout.buffer.write(canonical({
    "recipient": observe("recipient", "telegram_recipient_public_v2.json", 1024, 0o400),
    "admin": observe("admin", "boca_telegram_admin_status_v1.json", 4096, 0o600),
}))
"""


def observe_installed_public(context: InstalledTelegramContext) -> dict[str, Any]:
    """Read only the two public documents with parsers inside the installed image."""
    from boca_socios.host_telegram_maintenance import _diagnostic_pipe

    context.check_binding()
    raw = _diagnostic_pipe(
        (
            "exec",
            "--user",
            "10001:10001",
            context.installation.controller_id,
            "/app/.venv/bin/python",
            "-I",
            "-B",
            "-c",
            PUBLIC_OBSERVE_PROGRAM,
        )
    )
    context.check_binding()
    value = json.loads(raw, object_pairs_hook=bootstrap._unique)
    if type(value) is not dict or bootstrap._canonical(value) != raw:
        raise ValueError("telegram_public_observation_unverified")
    return value


def publish_installed_status(
    context: InstalledTelegramContext,
    maintenance: InstalledMaintenance,
    *,
    expected_custody: str | None = None,
) -> None:
    if expected_custody not in {None, "ABSENT", "VERIFIED"}:
        raise ValueError("telegram_status_expectation_unverified")
    context.healthy()
    item = context.installation
    sender_id = item.pair.sender_id or None
    request: dict[str, object] = {
        "source_sha": item.source_sha,
        "observation_run_id": context.attempt_id,
        "installation_run_id": item.installation_run_id,
        "controller_id": item.controller_id,
        "worker_id": item.worker_id,
        "sender_id": sender_id,
        "sender": "RUNNING" if item.pair.sender_running else "STOPPED" if sender_id else "ABSENT",
        "observed_at": datetime.now(UTC).isoformat(),
    }
    present = "boca-socios_boca_telegram" in dict(context.volumes)
    result = maintenance.call("publish-status" if present else "publish-status-absent", request)
    if (
        set(result) != {"state", "sha256", "configured", "paired"}
        or result["state"] != "STATUS_PUBLISHED"
        or (result["configured"], result["paired"])
        not in {("ABSENT", "NOT_PAIRED"), ("VERIFIED", "VERIFIED"), ("UNVERIFIED", "UNVERIFIED")}
    ):
        raise ValueError("telegram_status_publication_unverified")
    raw = (
        bootstrap._canonical(
            {
                "version": 1,
                **request,
                "configured": result["configured"],
                "paired": result["paired"],
                "human_receipt": "UNVERIFIED",
            }
        )
        + b"\n"
    )
    if result["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("telegram_status_publication_unverified")
    context.healthy()
    expected = (
        ("VERIFIED", "VERIFIED")
        if item.pair.sender_running or expected_custody == "VERIFIED"
        else ("ABSENT", "NOT_PAIRED")
        if expected_custody == "ABSENT"
        else None
    )
    if expected is not None and (result["configured"], result["paired"]) != expected:
        # Keep the truthful downgraded observation on disk, but do not turn it
        # into PREPARED/READY. Restoration-only recovery may report uncertainty.
        raise ValueError("telegram_status_custody_changed")
