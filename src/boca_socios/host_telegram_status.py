"""Publish the last verified installed observation, never an inferred heartbeat."""

from __future__ import annotations

import hashlib
import json
import re
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


# R311 observes names/FD metadata only; unlike PUBLIC_OBSERVE_PROGRAM it must
# never open a leaf, parse its bytes or import the installed document readers.
BOUNDARY_OBSERVE_PROGRAM = r"""
import hashlib,json,os,stat,sys

def identity(s):
    return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,
            s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def digest(*values):
    return hashlib.sha256(json.dumps(values,separators=(',',':')).encode('ascii')).hexdigest()

def empty(kind,state):
    keys=('type','mode','owner') if kind=='parent' else ('type','mode','owner','nlink','size')
    return {'state':state,'checks':dict.fromkeys(keys,'NOT_READ'),'witness':None}

def changed(kind):
    return empty(kind,'CHANGED')

def flags(meta,mode,kind,maximum=0):
    checks={'type':stat.S_ISDIR(meta.st_mode) if kind=='parent' else stat.S_ISREG(meta.st_mode),
            'mode':stat.S_IMODE(meta.st_mode)==mode,
            'owner':(meta.st_uid,meta.st_gid)==(10001,10001)}
    if kind!='parent':
        checks.update(nlink=meta.st_nlink==1,size=0<meta.st_size<=maximum)
    return {name:'PASS' if ok else 'FAIL' for name,ok in checks.items()}

def leaf(parent,name,mode,maximum,parent_identity):
    result=empty('leaf','NOT_READ')
    before=None
    try:
        metadata=os.stat(name,dir_fd=parent,follow_symlinks=False)
        before=identity(metadata)
    except FileNotFoundError:
        result['state']='ABSENT'
    except OSError:
        return result
    else:
        result['checks']=flags(metadata,mode,'leaf',maximum)
        result['state']='METADATA_VALID_PARSE_UNVERIFIED' if all(
            flag=='PASS' for flag in result['checks'].values()) else 'INVALID'
    try:
        after=identity(os.stat(name,dir_fd=parent,follow_symlinks=False))
    except FileNotFoundError:
        after=None
    except OSError:
        return empty('leaf','NOT_READ')
    if before!=after:
        return changed('leaf')
    result['witness']=digest(parent_identity,before)
    return result

def observe():
    result={'parent':empty('parent','NOT_READ'),
            'recipient':empty('leaf','NOT_ATTEMPTED'),
            'admin':empty('leaf','NOT_ATTEMPTED')}
    if (os.getuid(),os.geteuid(),os.getgid(),os.getegid())!=(10001,)*4:
        return result
    root=parent=None
    try:
        flags_dir=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        root=os.open('/',flags_dir)
        try:
            metadata=os.stat('data',dir_fd=root,follow_symlinks=False)
        except FileNotFoundError:
            result['parent']['state']='ABSENT'
            return result
        before=identity(metadata)
        checks=flags(metadata,0o700,'parent')
        result['parent']={'state':'VALID' if all(v=='PASS' for v in checks.values()) else 'INVALID',
                          'checks':checks,'witness':digest(before)}
        if result['parent']['state']!='VALID':
            if identity(os.stat('data',dir_fd=root,follow_symlinks=False))!=before:
                result['parent']=changed('parent')
            return result
        parent=os.open('data',flags_dir,dir_fd=root)
        if (identity(os.fstat(parent))!=before or
                identity(os.stat('data',dir_fd=root,follow_symlinks=False))!=before):
            result['parent']=changed('parent')
            return result
        result['recipient']=leaf(parent,'telegram_recipient_public_v2.json',0o400,1024,before)
        result['admin']=leaf(parent,'boca_telegram_admin_status_v1.json',0o600,4096,before)
        if (identity(os.fstat(parent))!=before or
                identity(os.stat('data',dir_fd=root,follow_symlinks=False))!=before):
            result['parent']=changed('parent')
            result['recipient']=changed('leaf')
            result['admin']=changed('leaf')
        return result
    except FileNotFoundError:
        result['parent']=changed('parent')
        result['recipient']=empty('leaf','NOT_ATTEMPTED')
        result['admin']=empty('leaf','NOT_ATTEMPTED')
        return result
    except OSError:
        result['parent']=empty('parent','NOT_READ')
        result['recipient']=empty('leaf','NOT_ATTEMPTED')
        result['admin']=empty('leaf','NOT_ATTEMPTED')
        return result
    finally:
        if parent is not None:
            os.close(parent)
        if root is not None:
            os.close(root)

sys.stdout.buffer.write(json.dumps(observe(),sort_keys=True,separators=(',',':'),
                                   ensure_ascii=True).encode('ascii'))
"""

BOUNDARY_PREFIX = b"BOCA_TELEGRAM_PUBLIC_BOUNDARY_V1 "
BOUNDARY_OPERATION = "telegram-public-boundary-observe"


def _boundary_empty(kind: str, state: str = "NOT_READ") -> dict[str, Any]:
    names = (
        ("type", "mode", "owner")
        if kind == "parent"
        else ("type", "mode", "owner", "nlink", "size")
    )
    return {"state": state, "checks": dict.fromkeys(names, "NOT_READ"), "witness": None}


def _boundary_initial(attempt_id: str, workflow_sha: str) -> dict[str, Any]:
    from boca_socios import host_telegram_backend as prior

    return {
        "version": 1,
        "operation": BOUNDARY_OPERATION,
        "source_sha": prior.DIAGNOSIS_SOURCE,
        "workflow_source_sha": workflow_sha,
        "attempt_id": attempt_id,
        "installation_run_id": prior.DIAGNOSIS_APPLY,
        "controller_id": prior.DIAGNOSIS_CONTROLLER,
        "worker_id": prior.DIAGNOSIS_WORKER,
        "state": "INCOMPLETE_NO_GO",
        "phase": "PREFLIGHT",
        "reason": "GUARD_UNVERIFIED",
        "guards": "NOT_READ",
        "samples": 0,
        "binding_fingerprint": None,
        "parent": _boundary_empty("parent"),
        "recipient": _boundary_empty("leaf", "NOT_ATTEMPTED"),
        "admin": _boundary_empty("leaf", "NOT_ATTEMPTED"),
        "engine": "NOT_READ",
        "sender": "NOT_READ",
        "helper_created": False,
        "helper_retirement": "NOT_APPLICABLE",
        "pair_restarted": False,
        "prepare_authorized": False,
        "adopt_authorized": False,
        "repair_authorized": False,
        "data_writes": 0,
        "custody_writes": 0,
        "status_writes": 0,
        "parse": "NOT_INSPECTED",
        "custody": "NOT_INSPECTED",
        "stage": "NOT_INSPECTED",
        "historical_cause": "UNDETERMINED",
        "recommendation": "PRESERVE_NO_RETRY",
    }


def _boundary_check_sample(sample: Any) -> None:
    if type(sample) is not dict or set(sample) != {"parent", "recipient", "admin"}:
        raise ValueError("boundary_sample")
    for name, item in sample.items():
        kind = "parent" if name == "parent" else "leaf"
        keys = set(_boundary_empty(kind)["checks"])
        states = (
            {"VALID", "INVALID", "ABSENT", "NOT_READ", "CHANGED"}
            if kind == "parent"
            else {
                "METADATA_VALID_PARSE_UNVERIFIED",
                "INVALID",
                "ABSENT",
                "NOT_READ",
                "CHANGED",
                "NOT_ATTEMPTED",
            }
        )
        if (
            type(item) is not dict
            or set(item) != {"state", "checks", "witness"}
            or item["state"] not in states
            or type(item["checks"]) is not dict
            or set(item["checks"]) != keys
            or any(flag not in {"PASS", "FAIL", "NOT_READ"} for flag in item["checks"].values())
            or (
                item["witness"] is not None
                and (
                    type(item["witness"]) is not str
                    or re.fullmatch(r"[a-f0-9]{64}", item["witness"]) is None
                )
            )
        ):
            raise ValueError("boundary_sample")
        checked = list(item["checks"].values())
        if item["state"] in {"VALID", "METADATA_VALID_PARSE_UNVERIFIED"}:
            valid = all(x == "PASS" for x in checked) and item["witness"] is not None
        elif item["state"] == "INVALID":
            valid = "FAIL" in checked and "NOT_READ" not in checked and item["witness"] is not None
        else:
            valid = all(x == "NOT_READ" for x in checked) and (
                (item["witness"] is None) == (item["state"] != "ABSENT" or kind == "parent")
            )
        if not valid:
            raise ValueError("boundary_sample")
    if sample["parent"]["state"] == "VALID":
        if any(sample[name]["state"] == "NOT_ATTEMPTED" for name in ("recipient", "admin")):
            raise ValueError("boundary_parent")
    else:
        allowed = (
            {"NOT_ATTEMPTED", "CHANGED"}
            if sample["parent"]["state"] == "CHANGED"
            else {"NOT_ATTEMPTED"}
        )
        if any(sample[name]["state"] not in allowed for name in ("recipient", "admin")):
            raise ValueError("boundary_parent")


def verify_public_boundary(
    raw: bytes,
    *,
    attempt_id: str,
    source_sha: str,
    workflow_sha: str,
    allow_failure: bool = False,
) -> dict[str, Any]:
    """Strictly typed receipt distinct from the R309 diagnostic and V1 backend."""
    try:
        from boca_socios import host_telegram_backend as prior

        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= 4096
            or not raw.startswith(BOUNDARY_PREFIX)
            or not raw.endswith(b"\n")
            or source_sha != prior.DIAGNOSIS_SOURCE
            or re.fullmatch(r"[a-f0-9]{40}", workflow_sha) is None
            or re.fullmatch(r"[1-9][0-9]{0,19}", attempt_id) is None
            or type(allow_failure) is not bool
        ):
            raise ValueError("frame")
        value = json.loads(raw[len(BOUNDARY_PREFIX) : -1], object_pairs_hook=bootstrap._unique)
        initial = _boundary_initial(attempt_id, workflow_sha)
        if (
            type(value) is not dict
            or set(value) != set(initial)
            or raw != BOUNDARY_PREFIX + bootstrap._canonical(value) + b"\n"
            or type(value["version"]) is not int
            or any(
                type(value[key]) is not bool
                for key in (
                    "helper_created",
                    "pair_restarted",
                    "prepare_authorized",
                    "adopt_authorized",
                    "repair_authorized",
                )
            )
            or any(
                type(value[key]) is not int
                for key in ("data_writes", "custody_writes", "status_writes")
            )
            or any(
                value[key] != initial[key]
                for key in (
                    "version",
                    "operation",
                    "source_sha",
                    "workflow_source_sha",
                    "attempt_id",
                    "installation_run_id",
                    "controller_id",
                    "worker_id",
                    "helper_created",
                    "helper_retirement",
                    "pair_restarted",
                    "prepare_authorized",
                    "adopt_authorized",
                    "repair_authorized",
                    "data_writes",
                    "custody_writes",
                    "status_writes",
                    "parse",
                    "custody",
                    "stage",
                    "historical_cause",
                    "recommendation",
                )
            )
            or value["state"] not in {"OBSERVED_NO_GO", "INCOMPLETE_NO_GO"}
            or value["phase"]
            not in {"LEASE", "PREFLIGHT", "PUBLIC_A", "PUBLIC_B", "POSTFLIGHT", "COMPLETE"}
            or value["reason"]
            not in {
                "NONE",
                "LEASE_UNVERIFIED",
                "GUARD_UNVERIFIED",
                "PUBLIC_UNVERIFIED",
                "PUBLIC_CHANGED",
                "TRANSPORT_UNVERIFIED",
            }
            or value["guards"] not in {"NOT_READ", "BEFORE", "BEFORE_AFTER"}
            or type(value["samples"]) is not int
            or value["samples"] not in {0, 1, 2}
            or value["engine"] not in {"NOT_READ", "STOPPED"}
            or value["sender"] not in {"NOT_READ", "ABSENT"}
            or (
                value["binding_fingerprint"] is not None
                and (
                    type(value["binding_fingerprint"]) is not str
                    or re.fullmatch(r"[a-f0-9]{64}", value["binding_fingerprint"]) is None
                )
            )
            or (value["guards"] == "NOT_READ") != (value["binding_fingerprint"] is None)
        ):
            raise ValueError("fields")
        _boundary_check_sample({name: value[name] for name in ("parent", "recipient", "admin")})
        if value["state"] == "OBSERVED_NO_GO":
            if (
                value["phase"] != "COMPLETE"
                or value["reason"] != "NONE"
                or value["guards"] != "BEFORE_AFTER"
                or value["samples"] != 2
                or value["engine"] != "STOPPED"
                or value["sender"] != "ABSENT"
                or value["parent"]["state"] in {"NOT_READ", "CHANGED"}
                or any(
                    value[name]["state"] in {"NOT_READ", "CHANGED"}
                    for name in ("recipient", "admin")
                )
            ):
                raise ValueError("complete")
        elif not allow_failure or value["phase"] == "COMPLETE" or value["reason"] == "NONE":
            raise ValueError("incomplete")
        return value
    except Exception:
        raise ValueError("telegram_public_boundary_unverified") from None


def _boundary_frame(value: dict[str, Any]) -> bytes:
    raw = BOUNDARY_PREFIX + bootstrap._canonical(value) + b"\n"
    verify_public_boundary(
        raw,
        attempt_id=value["attempt_id"],
        source_sha=value["source_sha"],
        workflow_sha=value["workflow_source_sha"],
        allow_failure=True,
    )
    return raw


def observe_installed_public_boundary(context: InstalledTelegramContext) -> dict[str, Any]:
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
            BOUNDARY_OBSERVE_PROGRAM,
        )
    )
    context.check_binding()
    value = json.loads(raw, object_pairs_hook=bootstrap._unique)
    if type(value) is not dict or bootstrap._canonical(value) != raw:
        raise ValueError("boundary_sample")
    _boundary_check_sample(value)
    return value


def diagnose_public_boundary(
    attempt_id: str,
    *,
    lease: Any,
    reader: Any = None,
    expected_source_sha: str,
    workflow_sha: str,
) -> bytes:
    from boca_socios import host_telegram_backend as prior
    from boca_socios.host_telegram_installed_context import resolve_installed_context

    value = _boundary_initial(attempt_id, workflow_sha)
    _boundary_frame(value)
    try:
        if expected_source_sha != prior.DIAGNOSIS_SOURCE:
            raise ValueError("source")
        context = resolve_installed_context(
            attempt_id,
            lease=lease,
            reader=reader,
            expected_source_sha=expected_source_sha,
            workflow_sha=workflow_sha,
        )
        prior._diagnosis_guard(context)
        if (
            context.reader.field("container", context.installation.controller_id, "Config.User")
            != "10001:10001"
            or context.reader.field("container", context.installation.worker_id, "State.Status")
            != "created"
            or context.reader.field("container", context.installation.worker_id, "State.Pid") != 0
        ):
            raise ValueError("target")
        value.update(
            guards="BEFORE",
            engine="STOPPED",
            sender="ABSENT",
            binding_fingerprint=context.installation.fingerprint(),
            phase="PUBLIC_A",
            reason="PUBLIC_UNVERIFIED",
        )
        before = observe_installed_public_boundary(context)
        value.update(before, samples=1, phase="PUBLIC_B")
        after = observe_installed_public_boundary(context)
        value["samples"] = 2
        for name in before:
            if before[name] != after[name]:
                value[name] = _boundary_empty("parent" if name == "parent" else "leaf", "CHANGED")
        value.update(phase="POSTFLIGHT", reason="GUARD_UNVERIFIED")
        prior._diagnosis_guard(context)
        value["guards"] = "BEFORE_AFTER"
        states = {value[name]["state"] for name in before}
        if "CHANGED" in states or any(value[name]["state"] == "CHANGED" for name in before):
            value.update(phase="PUBLIC_B", reason="PUBLIC_CHANGED")
        elif "NOT_READ" in states:
            value.update(phase="PUBLIC_B", reason="PUBLIC_UNVERIFIED")
        else:
            value.update(state="OBSERVED_NO_GO", phase="COMPLETE", reason="NONE")
    except Exception:
        if value["phase"] == "POSTFLIGHT":
            value.update(engine="NOT_READ", sender="NOT_READ")
    return _boundary_frame(value)


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
