"""Switch a recognized, Ubuntu-signed Noble archive to an independent mirror.

Build-time only: invoked after a failed apt update in Dockerfile.browser.
Only archive URIs change; signatures, suites and package pins remain enforced.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MIRROR = "https://mirrors.edge.kernel.org/ubuntu/"
ARCHIVE = "http://azure.archive.ubuntu.com/ubuntu/"
SECURITY = "http://security.ubuntu.com/ubuntu/"
KEY = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
COMPONENTS = "main restricted universe multiverse"
ARCHIVE_URIS = {
    ARCHIVE,
    ARCHIVE[:-1],
    "http://archive.ubuntu.com/ubuntu/",
    "http://archive.ubuntu.com/ubuntu",
}
SECURITY_URIS = {SECURITY, SECURITY[:-1]}
COMPONENT_SET = set(COMPONENTS.split())


class MirrorSchemaError(ValueError):
    """The base image's Ubuntu APT sources are not the reviewed schema."""


def _source_kind(uri: str) -> str:
    if uri in ARCHIVE_URIS:
        return "archive"
    if uri in SECURITY_URIS:
        return "security"
    raise MirrorSchemaError("unrecognized Ubuntu archive")


def _components_verified(value: str) -> bool:
    components = value.split()
    return len(components) == len(COMPONENT_SET) and set(components) == COMPONENT_SET


def _rewrite_deb822(source: str) -> str:
    chunks = source.strip().split("\n\n")
    if len(chunks) != 2:
        raise MirrorSchemaError("unexpected source count")

    found: set[str] = set()
    for chunk in chunks:
        fields: dict[str, str] = {}
        for line in chunk.splitlines():
            match = re.fullmatch(r"([A-Za-z-]+): (.+)", line)
            if match is None or match.group(1) in fields:
                raise MirrorSchemaError("invalid source field")
            fields[match.group(1)] = match.group(2)

        if set(fields) != {"Types", "URIs", "Suites", "Components", "Signed-By"}:
            raise MirrorSchemaError("unrecognized source fields")
        uri = fields["URIs"]
        kind = _source_kind(uri)
        if kind in found:
            raise MirrorSchemaError("duplicate Ubuntu pocket")
        if (
            fields["Types"] != "deb"
            or fields["Signed-By"] != KEY
            or not _components_verified(fields["Components"])
            or fields["Suites"]
            != ("noble-security" if kind == "security" else "noble noble-updates noble-backports")
        ):
            raise MirrorSchemaError("unrecognized signed Noble pocket")
        found.add(kind)

    if found != {"archive", "security"}:
        raise MirrorSchemaError("missing signed security pocket")
    return "\n".join(
        f"URIs: {MIRROR}" if line.startswith("URIs: ") else line for line in source.split("\n")
    )


def _rewrite_legacy(source: str) -> str:
    expected = {
        ("archive", "noble"),
        ("archive", "noble-updates"),
        ("archive", "noble-backports"),
        ("security", "noble-security"),
    }
    observed: set[tuple[str, str]] = set()
    revised_lines: list[str] = []
    for line in source.splitlines():
        if not line.strip() or line.startswith("#"):
            revised_lines.append(line)
            continue
        pattern = (
            rf"(deb \[signed-by={re.escape(KEY)}\] )(?P<uri>\S+) (?P<suite>\S+) (?P<components>.+)"
        )
        match = re.fullmatch(pattern, line)
        if match is None or not _components_verified(match.group("components")):
            raise MirrorSchemaError("unrecognized signed legacy source")
        identity = (_source_kind(match.group("uri")), match.group("suite"))
        if identity not in expected or identity in observed:
            raise MirrorSchemaError("unrecognized signed legacy source")
        observed.add(identity)
        revised_lines.append(line.replace(match.group("uri"), MIRROR, 1))
    if observed != expected:
        raise MirrorSchemaError("missing legacy Ubuntu pocket")
    return "\n".join(revised_lines) + ("\n" if source.endswith("\n") else "")


def _has_enabled_lines(path: Path) -> bool:
    if path.is_symlink():
        raise MirrorSchemaError("symlinked Ubuntu APT source")
    return any(
        line.strip() and not line.lstrip().startswith("#")
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def rewrite_sources(apt_etc: Path) -> None:
    deb822 = apt_etc / "sources.list.d" / "ubuntu.sources"
    legacy = apt_etc / "sources.list"
    active_legacy = legacy.exists() and _has_enabled_lines(legacy)
    sources_dir = apt_etc / "sources.list.d"
    if sources_dir.exists():
        for extra in sources_dir.iterdir():
            if (
                extra != deb822
                and extra.suffix in {".list", ".sources"}
                and _has_enabled_lines(extra)
            ):
                raise MirrorSchemaError("unreviewed active APT source")
    if deb822.exists():
        if deb822.is_symlink() or active_legacy:
            raise MirrorSchemaError("multiple active Ubuntu source formats")
        source = deb822
        transform = _rewrite_deb822
    elif active_legacy:
        if legacy.is_symlink():
            raise MirrorSchemaError("unrecognized legacy source")
        source = legacy
        transform = _rewrite_legacy
    else:
        raise MirrorSchemaError("missing Ubuntu APT source")

    original = source.read_text(encoding="utf-8")
    revised = transform(original)
    if revised == original:
        raise MirrorSchemaError("no archive URI change")
    source.write_text(revised, encoding="utf-8")


def main() -> int:
    apt_etc = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("/etc/apt")
    try:
        rewrite_sources(apt_etc)
    except (MirrorSchemaError, OSError, UnicodeError):
        print("BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA", file=sys.stderr)
        return 1
    print("BOCA_APT_FALLBACK state=READY mirror=kernel_archives")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
