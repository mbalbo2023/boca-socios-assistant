"""Validate one untrusted Boca linger SSH receipt before publishing Action logs.

Runner-only, stdlib-only. A valid metadata NO_GO is a completed read and can
precede the existing independent prerequisite inspection. Transport errors,
truncation and unexpected text are fatal, with no remote bytes in logs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_RECEIPT = 4096
UID = 10001
NUM = r"(?:UNKNOWN|[0-9]{1,10})"
MODE = r"(?:UNKNOWN|[0-7]{4})"
FILE = r"(?:DIRECTORY|SOCKET|REGULAR|UNSAFE|ABSENT|UNAVAILABLE)"
DIRECTORY = r"(?:PRIVATE|DIRECTORY|SOCKET|REGULAR|UNSAFE|ABSENT|UNAVAILABLE)"
DOCKER_ROOT = r"(?:OWNER_0710|PRIVATE|SOCKET|REGULAR|UNSAFE|ABSENT|UNAVAILABLE)"
SOCKET = r"(?:OWNED|SYSTEMD_DEFAULT|OPEN_MODE|NO_OWNER_WRITE|DIRECTORY|REGULAR|UNSAFE|ABSENT|UNAVAILABLE)"
YES_NO = r"(?:YES|NO|UNKNOWN)"


class ReceiptError(ValueError):
    """Untrusted SSH bytes fail the strict, constant-vocabulary contract."""


def _meta(prefix: str) -> dict[str, str]:
    return {f"{prefix}_uid": NUM, f"{prefix}_gid": NUM, f"{prefix}_mode": MODE}


FIELDS: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "BOCA_LINGER_ROOTLESS",
        {
            "state": r"(?:METADATA_CANDIDATE|PREREQUISITES_UNPROVEN)",
            "identity": "OK",
            "linger": YES_NO,
            "marker": FILE,
        },
    ),
    (
        "BOCA_LINGER_DIR",
        {"home": DIRECTORY, **_meta("home"), "runtime": DIRECTORY, **_meta("runtime")},
    ),
    (
        "BOCA_LINGER_SOCKET",
        {
            "manager": SOCKET,
            **_meta("manager"),
            "bus": SOCKET,
            **_meta("bus"),
            "docker_socket": SOCKET,
            **_meta("docker"),
        },
    ),
    (
        "BOCA_LINGER_LAYOUT",
        {
            "data_root": DOCKER_ROOT,
            **_meta("data"),
            "unit": FILE,
            **_meta("unit"),
            "marker": FILE,
            **_meta("marker"),
        },
    ),
    (
        "BOCA_LINGER_IDS",
        {
            "subuid": r"(?:VALID|INVALID|UNKNOWN)",
            "subgid": r"(?:VALID|INVALID|UNKNOWN)",
            "newuidmap": r"(?:AVAILABLE|UNAVAILABLE|UNKNOWN)",
            "newgidmap": r"(?:AVAILABLE|UNAVAILABLE|UNKNOWN)",
            "userns": r"(?:AVAILABLE|DISABLED|UNKNOWN)",
        },
    ),
    (
        "BOCA_LINGER_SCOPE",
        {
            "docker_queries": "0",
            "changes": "NONE",
            "blackbox": "UNTOUCHED",
            "exitcode1_cause": "UNKNOWN",
            "deploy": "NO_GO",
        },
    ),
)


def _parse(line: str, expected: tuple[str, dict[str, str]]) -> dict[str, str]:
    name, rules = expected
    tokens = line.split(" ")
    if len(tokens) != len(rules) + 1 or tokens[0] != name:
        raise ReceiptError("unexpected line or field count")
    observed: dict[str, str] = {}
    for token, (key, pattern) in zip(tokens[1:], rules.items(), strict=True):
        prefix = f"{key}="
        if not token.startswith(prefix):
            raise ReceiptError("unexpected field order")
        value = token[len(prefix) :]
        if re.fullmatch(pattern, value, flags=re.ASCII) is None:
            raise ReceiptError("invalid field")
        if key.endswith(("_uid", "_gid")) and value != "UNKNOWN" and int(value) >= 2**32:
            raise ReceiptError("numeric value out of range")
        observed[key] = value
    return observed


def _coherent(rows: list[dict[str, str]]) -> bool:
    root, dirs, sockets, layout, ids, _scope = rows
    if root["marker"] != layout["marker"]:
        return False
    for prefix, row in (
        ("home", dirs),
        ("runtime", dirs),
        ("manager", sockets),
        ("bus", sockets),
        ("docker", sockets),
        ("data", layout),
        ("unit", layout),
        ("marker", layout),
    ):
        values = [row[f"{prefix}_{suffix}"] for suffix in ("uid", "gid", "mode")]
        if any(value == "UNKNOWN" for value in values) and not all(
            value == "UNKNOWN" for value in values
        ):
            return False
        key = {"docker": "docker_socket", "data": "data_root"}.get(prefix, prefix)
        state = row[key]
        if state in {"ABSENT", "UNAVAILABLE"} and any(value != "UNKNOWN" for value in values):
            return False
    for name in ("home", "runtime"):
        if dirs[name] == "PRIVATE" and (
            dirs[f"{name}_uid"],
            dirs[f"{name}_gid"],
            dirs[f"{name}_mode"],
        ) != (str(UID), str(UID), "0700"):
            return False
    docker_root_metadata = (
        layout["data_uid"],
        layout["data_gid"],
        layout["data_mode"],
    )
    docker_root_mode = layout["data_root"]
    if docker_root_mode == "OWNER_0710" and docker_root_metadata != (str(UID), str(UID), "0710"):
        return False
    if docker_root_mode == "PRIVATE" and docker_root_metadata != (str(UID), str(UID), "0700"):
        return False
    if docker_root_mode == "UNSAFE" and docker_root_metadata in {
        (str(UID), str(UID), "0710"),
        (str(UID), str(UID), "0700"),
    }:
        return False
    for name, prefix in (("manager", "manager"), ("bus", "bus"), ("docker_socket", "docker")):
        state = sockets[name]
        if state in ("OWNED", "OPEN_MODE", "SYSTEMD_DEFAULT", "NO_OWNER_WRITE"):
            if sockets[f"{prefix}_uid"] != str(UID):
                return False
            mode = int(sockets[f"{prefix}_mode"], 8)
            public = bool(mode & 0o002)
            owner_writable = bool(mode & 0o200)
            if state == "SYSTEMD_DEFAULT" and (name == "docker_socket" or mode != 0o666):
                return False
            if state == "NO_OWNER_WRITE" and owner_writable:
                return False
            if state in ("OWNED", "OPEN_MODE") and (
                not owner_writable or public != (state == "OPEN_MODE")
            ):
                return False
    candidate = (
        root["linger"] == "YES"
        and dirs["home"] == dirs["runtime"] == "PRIVATE"
        and sockets["manager"] in {"OWNED", "SYSTEMD_DEFAULT"}
        and sockets["bus"] in {"OWNED", "SYSTEMD_DEFAULT"}
        and sockets["docker_socket"] == "OWNED"
        and ids["subuid"] == ids["subgid"] == "VALID"
        and ids["newuidmap"] == ids["newgidmap"] == ids["userns"] == "AVAILABLE"
    )
    return candidate == (root["state"] == "METADATA_CANDIDATE")


def verify(data: bytes, remote_status: int) -> str:
    if not 0 < len(data) <= MAX_RECEIPT or not data.endswith(b"\n"):
        raise ReceiptError("missing or oversized report")
    try:
        decoded = data.decode("ascii")
    except UnicodeError as exc:
        raise ReceiptError("non-ASCII report") from exc
    if any(ord(letter) < 32 and letter != "\n" for letter in decoded):
        raise ReceiptError("non-printable report")
    lines = decoded.removesuffix("\n").split("\n")
    if len(lines) != len(FIELDS):
        raise ReceiptError("unexpected report line count")
    rows = [_parse(line, expected) for line, expected in zip(lines, FIELDS, strict=True)]
    state = rows[0]["state"]
    if remote_status != (0 if state == "METADATA_CANDIDATE" else 1) or not _coherent(rows):
        raise ReceiptError("report status or metadata mismatch")
    return state


def main() -> int:
    try:
        if len(sys.argv) != 4 or sys.argv[2] not in {"0", "1"}:
            raise ReceiptError("unaccepted status")
        with Path(sys.argv[1]).open("rb") as stream:
            data = stream.read(MAX_RECEIPT + 1)
        state = verify(data, int(sys.argv[2]))
        with open(sys.argv[3], "a", encoding="ascii") as output:
            output.write(
                "candidate=true\n" if state == "METADATA_CANDIDATE" else "candidate=false\n"
            )
        print(data.decode("ascii"), end="")  # only after complete schema validation
        print(f"BOCA_LINGER_VERIFIED status={state} transport=VALIDATED deploy=NO_GO")
        return 0
    except (OSError, ReceiptError, ValueError, UnicodeError):
        print("BOCA_LINGER_VERIFIER status=NO_GO reason=UNVERIFIED_RECEIPT")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
