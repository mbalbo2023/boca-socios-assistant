"""Read only installed Boca Telegram recipient metadata through one fixed Docker exec.

This is not Telegram activation, preparation, repair, custody or a deploy gate.
Only two in-container stat observations may be obtained; file content is never
opened, copied, parsed or emitted. The owner pair/binding is independently
attested before and after each of the two fixed, bounded exec calls.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import Any

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair

OPERATION = "boca-public-recipient-metadata-observe"
PREFIX = b"BOCA_PUBLIC_RECIPIENT_METADATA_V3 "
SOURCE = "55da98df6713d40ebf1455fb328005544043d091"
APPLY = "43813151261"
CONTROLLER = "2c08e3900a75166639c1b03bc8d14e921b51bf9e2ebf0d3937a270522e8f7065"
WORKER = "8def04f7fa8d9ef7f1600c856595f9a6ffb335739a6d933772ee276040034e8b"
CONTROLLER_OCI = "sha256:9312e690c754d1000751a7d04a2af81238bae6a3ab38f19b6f668553768c8cfa"
WORKER_OCI = "sha256:761e3878e1d1cbd7c7219f59710403115823a41274170c1d0d15916a7c9cc4a5"
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PREFIX_FAILURE = b"BOCA_PUBLIC_RECIPIENT_METADATA_V3 state=INCOMPLETE_NO_GO reason=UNVERIFIED\n"
_LIMIT = 4096
_SAMPLE = frozenset({"parent", "recipient", "parent_mode", "parent_witness", "recipient_witness"})
_PARENT = frozenset({"ABSENT", "INVALID", "METADATA_VALID", "CHANGED", "NOT_READ"})
_RECIPIENT = frozenset(
    {"NOT_ATTEMPTED", "ABSENT", "INVALID", "METADATA_VALID_PARSE_UNVERIFIED", "CHANGED", "NOT_READ"}
)
_REASON = frozenset(
    {
        "NONE",
        "IDENTITY_UNVERIFIED",
        "ENGINE_UNVERIFIED",
        "METADATA_UNVERIFIED",
        "METADATA_CHANGED",
        "EXEC_UNVERIFIED",
        "TRANSPORT_UNVERIFIED",
    }
)
_PHASE = frozenset({"PREFLIGHT", "METADATA_A", "METADATA_B", "POSTFLIGHT", "COMPLETE"})
_FIELDS = frozenset(
    {
        "version",
        "operation",
        "observation_run_id",
        "workflow_source_sha",
        "state",
        "phase",
        "reason",
        "guards",
        "samples",
        "binding",
        "parent",
        "recipient",
        "engine",
        "sender",
        "exec_attempts",
        "exec_started",
        "exec_retired",
        "application_data_writes",
        "admin",
        "custody",
        "stage",
        "document_parse",
        "prepare_authorized",
        "adopt_authorized",
        "repair_authorized",
        "recommendation",
    }
)

# Fixed, stdlib-only code inside the exact bound controller CID. Do not add
# arbitrary host target, user paths, environment, helper or per-request code.
METADATA_PROGRAM = r"""
import hashlib,json,os,stat,sys
flag=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
def identity(st):
    return (st.st_dev,st.st_ino,st.st_mode,st.st_uid,st.st_gid,st.st_nlink,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
def digest(st):return hashlib.sha256(repr(identity(st)).encode('ascii')).hexdigest()
def emit(parent='NOT_READ',recipient='NOT_ATTEMPTED',pst=None,lst=None):
    print(json.dumps({'parent':parent,'recipient':recipient,'parent_mode':format(stat.S_IMODE(pst.st_mode),'04o') if pst else 'NONE','parent_witness':digest(pst) if pst else 'NONE','recipient_witness':digest(lst) if lst else 'NONE'},sort_keys=True,separators=(',',':')))
    sys.exit(0)
if (os.getuid(),os.geteuid(),os.getgid(),os.getegid())!=(10001,10001,10001,10001):emit()
fd=-1;root=-1
try:
    root=os.open('/',flag)
    def parent_stat():
        try:return os.stat('data',dir_fd=root,follow_symlinks=False)
        except FileNotFoundError:return None
    first=parent_stat()
    if first is None:
        second=parent_stat()
        emit('ABSENT' if second is None else 'CHANGED')
    if not stat.S_ISDIR(first.st_mode) or (first.st_uid,first.st_gid)!=(10001,10001) or stat.S_IMODE(first.st_mode) not in (0o700,0o755):
        second=parent_stat()
        if second is None or identity(first)!=identity(second):emit('CHANGED')
        emit('INVALID','NOT_ATTEMPTED',first)
    fd=os.open('data',flag,dir_fd=root)
    opened=os.fstat(fd)
    if identity(first)!=identity(opened) or not os.access('data',os.X_OK,dir_fd=root,effective_ids=True,follow_symlinks=False):emit('CHANGED')
    try:
        before=os.stat('telegram_recipient_public_v2.json',dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError:before=None
    try:
        second=os.stat('telegram_recipient_public_v2.json',dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError:second=None
    after=parent_stat()
    if after is None or identity(first)!=identity(after) or identity(opened)!=identity(os.fstat(fd)):emit('CHANGED','CHANGED')
    if before is None and second is None:emit('METADATA_VALID','ABSENT',opened)
    if before is None or second is None or identity(before)!=identity(second):emit('METADATA_VALID','CHANGED',opened)
    if not stat.S_ISREG(before.st_mode) or (before.st_uid,before.st_gid)!=(10001,10001) or stat.S_IMODE(before.st_mode)!=0o400 or before.st_nlink!=1 or not 1<=before.st_size<=1024:emit('METADATA_VALID','INVALID',opened,before)
    emit('METADATA_VALID','METADATA_VALID_PARSE_UNVERIFIED',opened,before)
except (OSError,ValueError,TypeError):emit()
finally:
    if fd>=0:os.close(fd)
    if root>=0:os.close(root)
"""


class NoGo(ValueError):
    """Fail-closed metadata witness or installed identity ambiguity."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NoGo("duplicate metadata key")
        result[key] = value
    return result


def _json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("ascii"),
        object_pairs_hook=_unique,
        parse_constant=lambda _: (_ for _ in ()).throw(NoGo("nonfinite")),
    )


def _canonical(record: dict[str, Any]) -> bytes:
    return (
        PREFIX
        + json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
        + b"\n"
    )


def _sample(raw: bytes) -> dict[str, Any]:
    if len(raw) > 1024 or not raw.endswith(b"\n"):
        raise NoGo("container metadata framing")
    value = _json(raw)
    if (
        type(value) is not dict
        or value.keys() != _SAMPLE
        or raw != json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    ):
        raise NoGo("container metadata schema")
    parent, recipient = value["parent"], value["recipient"]
    if (
        type(parent) is not str
        or type(recipient) is not str
        or parent not in _PARENT
        or recipient not in _RECIPIENT
    ):
        raise NoGo("container metadata state")
    if parent != "METADATA_VALID" and recipient not in ("NOT_ATTEMPTED", "CHANGED"):
        raise NoGo("container metadata parent")
    if (
        parent == "METADATA_VALID"
        and recipient == "NOT_ATTEMPTED"
        or parent in ("ABSENT", "INVALID", "NOT_READ")
        and recipient != "NOT_ATTEMPTED"
    ):
        raise NoGo("container metadata impossible parent/leaf combination")
    if parent in ("METADATA_VALID", "INVALID"):
        if (
            type(value["parent_mode"]) is not str
            or re.fullmatch(r"0[0-7]{3}", value["parent_mode"]) is None
            or parent == "METADATA_VALID"
            and value["parent_mode"] not in ("0700", "0755")
            or type(value["parent_witness"]) is not str
            or not _HEX.fullmatch(value["parent_witness"])
        ):
            raise NoGo("container metadata parent witness")
    elif value["parent_mode"] != "NONE" or value["parent_witness"] != "NONE":
        raise NoGo("invalid parent witness")
    if recipient in ("METADATA_VALID_PARSE_UNVERIFIED", "INVALID"):
        if type(value["recipient_witness"]) is not str or not _HEX.fullmatch(
            value["recipient_witness"]
        ):
            raise NoGo("container metadata leaf witness")
    elif value["recipient_witness"] != "NONE":
        raise NoGo("invalid leaf witness")
    return value


def _docker_exec(cid: str) -> bytes:
    """Only bounded stdout/stderr and a bounded local Docker client lifetime."""
    command = (
        "/usr/bin/docker",
        "--host",
        cleanup.DOCKER_SOCKET,
        "exec",
        "--user",
        "10001:10001",
        cid,
        "/app/.venv/bin/python",
        "-I",
        "-B",
        "-c",
        METADATA_PROGRAM,
    )
    process = subprocess.Popen(  # noqa: S603 - fully literal Docker argv, pinned bound CID
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "HOME": "/", "DOCKER_HOST": cleanup.DOCKER_SOCKET},
        close_fds=True,
    )
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    polling = selectors.DefaultSelector()
    try:
        assert process.stdout is not None and process.stderr is not None
        for stream, kind in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            polling.register(stream, selectors.EVENT_READ, kind)
        deadline = time.monotonic() + 20
        while polling.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NoGo("docker exec timeout")
            for key, _ in polling.select(remaining):
                chunk = os.read(key.fd, 1024)
                if not chunk:
                    polling.unregister(key.fileobj)
                    continue
                outputs[key.data].extend(chunk)
                if len(outputs["stdout"]) > 1024 or len(outputs["stderr"]) > 1024:
                    raise NoGo("docker exec output exceeded bound")
        if (
            process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0
            or outputs["stderr"]
            or not outputs["stdout"]
        ):
            raise NoGo("docker exec returned no verified evidence")
        return bytes(outputs["stdout"])
    finally:
        polling.close()
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise NoGo("local Docker client not retired") from None
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _guard(run_id: str) -> dict[str, Any]:
    first = pair.observe(run_id)
    item = binding._read_host_binding()
    record = binding._attest(run_id, first, item)
    payload = _json(first[len(pair._PREFIX) :])
    controller, worker = payload["services"]
    if (
        item.source_sha != SOURCE
        or item.installation_run_id != APPLY
        or item.controller_id != CONTROLLER
        or item.worker_id != WORKER
        or controller["image_ref"] != f"ghcr.io/mbalbo2023/boca-socios-assistant@{CONTROLLER_OCI}"
        or worker["image_ref"] != f"ghcr.io/mbalbo2023/boca-socios-assistant-browser@{WORKER_OCI}"
        or item.controller_id == item.worker_id
        or record["state"] != "OBSERVED_NO_GO"
    ):
        raise NoGo("installed pair pin mismatch")
    return {
        "installed_source_sha": SOURCE,
        "apply_run_id": APPLY,
        "controller_id": CONTROLLER,
        "worker_id": WORKER,
        "controller_oci": CONTROLLER_OCI,
        "worker_oci": WORKER_OCI,
        "fingerprint": item.fingerprint(),
    }


def _frame(run_id: str, workflow_sha: str) -> dict[str, Any]:
    return {
        "version": 3,
        "operation": OPERATION,
        "observation_run_id": run_id,
        "workflow_source_sha": workflow_sha,
        "state": "INCOMPLETE_NO_GO",
        "phase": "PREFLIGHT",
        "reason": "IDENTITY_UNVERIFIED",
        "guards": {"before": "NOT_ATTEMPTED", "after": "NOT_ATTEMPTED"},
        "samples": [],
        "binding": None,
        "parent": "NOT_READ",
        "recipient": "NOT_ATTEMPTED",
        "engine": "UNVERIFIED",
        "sender": "ABSENT_UNVERIFIED",
        "exec_attempts": 0,
        "exec_started": 0,
        "exec_retired": 0,
        "application_data_writes": 0,
        "admin": "NOT_INSPECTED",
        "custody": "NOT_INSPECTED",
        "stage": "NOT_INSPECTED",
        "document_parse": "NOT_INSPECTED",
        "prepare_authorized": False,
        "adopt_authorized": False,
        "repair_authorized": False,
        "recommendation": "PRESERVE_NO_RETRY",
    }


def observe(run_id: str, workflow_sha: str) -> bytes:
    if (
        type(run_id) is not str
        or not _RUN.fullmatch(run_id)
        or type(workflow_sha) is not str
        or not _SHA.fullmatch(workflow_sha)
        or (os.geteuid(), os.getegid()) != (10001, 10001)
    ):
        raise NoGo("invalid observer identity")
    value = _frame(run_id, workflow_sha)
    try:
        initial = _guard(run_id)
        value["guards"]["before"] = "VERIFIED"
        value["binding"] = initial
        value["sender"] = "ABSENT"
        for phase in ("METADATA_A", "METADATA_B"):
            value["phase"] = phase
            value["exec_attempts"] += 1
            sample = _sample(_docker_exec(CONTROLLER))
            value["exec_started"] += 1
            value["exec_retired"] += 1
            value["samples"].append(sample)
        value["phase"] = "POSTFLIGHT"
        final = _guard(run_id)
        if initial != final:
            value["reason"] = "IDENTITY_UNVERIFIED"
        else:
            value["guards"]["after"] = "VERIFIED"
            first, second = value["samples"]
            if first != second or any(
                sample[key] == "CHANGED"
                for sample in (first, second)
                for key in ("parent", "recipient")
            ):
                value["reason"] = "METADATA_CHANGED"
            elif any(
                sample[key] == "NOT_READ"
                for sample in (first, second)
                for key in ("parent", "recipient")
            ):
                value["reason"] = "METADATA_UNVERIFIED"
            else:
                value["state"] = "OBSERVED_NO_GO"
                value["phase"] = "COMPLETE"
                value["reason"] = "NONE"
                value["parent"] = first["parent"]
                value["recipient"] = first["recipient"]
    except (ValueError, OSError, subprocess.SubprocessError, TimeoutError):
        if value["phase"] in ("METADATA_A", "METADATA_B"):
            value["reason"] = "EXEC_UNVERIFIED"
        elif value["phase"] == "POSTFLIGHT":
            value["reason"] = "IDENTITY_UNVERIFIED"
    raw = _canonical(value)
    verify(raw, run_id=run_id, workflow_sha=workflow_sha, allow_failure=True)
    return raw


def verify(
    raw: bytes, *, run_id: str, workflow_sha: str, allow_failure: bool = False
) -> dict[str, object]:
    if (
        type(raw) is not bytes
        or len(raw) > _LIMIT
        or not raw.startswith(PREFIX)
        or not raw.endswith(b"\n")
        or type(run_id) is not str
        or not _RUN.fullmatch(run_id)
        or type(workflow_sha) is not str
        or not _SHA.fullmatch(workflow_sha)
    ):
        raise NoGo("receipt framing invalid")
    try:
        item = _json(raw[len(PREFIX) :])
    except (ValueError, UnicodeError, RecursionError):
        raise NoGo("receipt JSON invalid") from None
    if (
        type(item) is not dict
        or item.keys() != _FIELDS
        or type(item["version"]) is not int
        or item["version"] != 3
        or item["operation"] != OPERATION
        or item["observation_run_id"] != run_id
        or item["workflow_source_sha"] != workflow_sha
        or item["state"] not in ("OBSERVED_NO_GO", "INCOMPLETE_NO_GO")
        or item["phase"] not in _PHASE
        or item["reason"] not in _REASON
        or type(item["exec_attempts"]) is not int
        or type(item["exec_started"]) is not int
        or type(item["exec_retired"]) is not int
        or not 0 <= item["exec_retired"] <= item["exec_started"] <= item["exec_attempts"] <= 2
        or item["application_data_writes"] != 0
        or type(item["application_data_writes"]) is not int
        or any(
            item[name] != "NOT_INSPECTED"
            for name in ("admin", "custody", "stage", "document_parse")
        )
        or any(
            item[name] is not False
            for name in ("prepare_authorized", "adopt_authorized", "repair_authorized")
        )
        or item["recommendation"] != "PRESERVE_NO_RETRY"
        or item["engine"] != "UNVERIFIED"
        or item["sender"] not in ("ABSENT", "ABSENT_UNVERIFIED")
        or type(item["guards"]) is not dict
        or item["guards"].keys() != {"before", "after"}
        or any(
            item["guards"][which] not in ("NOT_ATTEMPTED", "VERIFIED")
            for which in ("before", "after")
        )
        or type(item["samples"]) is not list
        or len(item["samples"]) > 2
        or any(type(sample) is not dict for sample in item["samples"])
        or item["parent"] not in _PARENT
        or item["recipient"] not in _RECIPIENT
        or raw != _canonical(item)
    ):
        raise NoGo("closed receipt schema invalid")
    for sample in item["samples"]:
        _sample((json.dumps(sample, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
    if item["binding"] is not None:
        bound = item["binding"]
        if (
            type(bound) is not dict
            or bound.keys()
            != {
                "installed_source_sha",
                "apply_run_id",
                "controller_id",
                "worker_id",
                "controller_oci",
                "worker_oci",
                "fingerprint",
            }
            or (
                bound["installed_source_sha"],
                bound["apply_run_id"],
                bound["controller_id"],
                bound["worker_id"],
                bound["controller_oci"],
                bound["worker_oci"],
            )
            != (SOURCE, APPLY, CONTROLLER, WORKER, CONTROLLER_OCI, WORKER_OCI)
            or type(bound["fingerprint"]) is not str
            or not _HEX.fullmatch(bound["fingerprint"])
        ):
            raise NoGo("installed binding mismatch")
    elif item["guards"]["before"] != "NOT_ATTEMPTED":
        raise NoGo("binding guard missing")
    before_verified = item["guards"]["before"] == "VERIFIED"
    after_verified = item["guards"]["after"] == "VERIFIED"
    if not before_verified and (
        item["binding"] is not None
        or after_verified
        or item["phase"] != "PREFLIGHT"
        or item["reason"] != "IDENTITY_UNVERIFIED"
        or (item["exec_attempts"], item["exec_started"], item["exec_retired"]) != (0, 0, 0)
        or item["samples"]
        or item["engine"] != "UNVERIFIED"
        or item["sender"] != "ABSENT_UNVERIFIED"
    ):
        raise NoGo("preflight unverified receipt contradictory")
    if before_verified and (
        item["binding"] is None
        or item["engine"] != "UNVERIFIED"
        or item["sender"] != "ABSENT"
        or item["phase"] == "PREFLIGHT"
        or (item["phase"] == "METADATA_A" and item["exec_attempts"] != 1)
        or (item["phase"] == "METADATA_B" and item["exec_attempts"] != 2)
        or (item["phase"] in ("POSTFLIGHT", "COMPLETE") and item["exec_attempts"] != 2)
        or (after_verified and item["phase"] not in ("POSTFLIGHT", "COMPLETE"))
        or len(item["samples"]) > item["exec_retired"]
    ):
        raise NoGo("post-preflight receipt contradictory")
    if item["state"] == "OBSERVED_NO_GO":
        if (
            item["phase"] != "COMPLETE"
            or item["reason"] != "NONE"
            or item["guards"] != {"before": "VERIFIED", "after": "VERIFIED"}
            or len(item["samples"]) != 2
            or item["samples"][0] != item["samples"][1]
            or any(
                sample[key] in ("NOT_READ", "CHANGED")
                for sample in item["samples"]
                for key in ("parent", "recipient")
            )
            or (item["exec_attempts"], item["exec_started"], item["exec_retired"]) != (2, 2, 2)
            or item["parent"] != item["samples"][0]["parent"]
            or item["recipient"] != item["samples"][0]["recipient"]
            or item["engine"] != "UNVERIFIED"
            or item["sender"] != "ABSENT"
            or item["binding"] is None
        ):
            raise NoGo("successful metadata witness inconsistent")
    elif (
        not allow_failure
        or item["reason"] == "NONE"
        or item["phase"] == "COMPLETE"
        or (item["parent"], item["recipient"]) != ("NOT_READ", "NOT_ATTEMPTED")
        or (item["phase"] in ("METADATA_A", "METADATA_B") and item["reason"] != "EXEC_UNVERIFIED")
        or (
            item["phase"] == "POSTFLIGHT"
            and item["reason"]
            not in ("IDENTITY_UNVERIFIED", "METADATA_CHANGED", "METADATA_UNVERIFIED")
        )
        or (
            item["reason"] == "METADATA_CHANGED"
            and (
                not after_verified
                or len(item["samples"]) != 2
                or not (
                    item["samples"][0] != item["samples"][1]
                    or any(
                        sample[key] == "CHANGED"
                        for sample in item["samples"]
                        for key in ("parent", "recipient")
                    )
                )
            )
        )
        or (
            item["reason"] == "METADATA_UNVERIFIED"
            and (
                not after_verified
                or len(item["samples"]) != 2
                or not any(
                    sample[key] == "NOT_READ"
                    for sample in item["samples"]
                    for key in ("parent", "recipient")
                )
            )
        )
    ):
        raise NoGo("incomplete metadata witness cannot be promoted")
    return item


def main(argv: Sequence[str]) -> int:
    try:
        if len(argv) != 3 or argv[0] not in ("host", "verify"):
            raise NoGo("unknown mode")
        if argv[0] == "host":
            raw = observe(argv[1], argv[2])
            verified = verify(raw, run_id=argv[1], workflow_sha=argv[2], allow_failure=True)
        else:
            raw = sys.stdin.buffer.read(_LIMIT + 1)
            verified = verify(raw, run_id=argv[1], workflow_sha=argv[2], allow_failure=True)
        sys.stdout.buffer.write(raw)
        return 0 if verified["state"] == "OBSERVED_NO_GO" else 3
    except Exception:
        sys.stdout.buffer.write(_PREFIX_FAILURE)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
