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
    # Minimal Ubuntu OCI images may intentionally enable only main/universe.
    # Preserve the exact existing subset: never silently enable new components.
    return (
        bool(components)
        and "main" in components
        and len(components) == len(set(components))
        and set(components) <= COMPONENT_SET
    )


def _rewrite_deb822(source: str) -> str:
    # Ubuntu source files may contain comments from the image publisher.
    # Ignore them for schema verification but preserve their original bytes.
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if not line.strip():
            if current:
                chunks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        chunks.append(current)
    if len(chunks) != 2:
        raise MirrorSchemaError("unexpected source count")

    found: set[str] = set()
    component_set: set[str] | None = None
    architecture_seen: bool | None = None
    mandatory_fields = {"Types", "URIs", "Suites", "Components", "Signed-By"}
    for chunk in chunks:
        fields: dict[str, str] = {}
        for line in chunk:
            match = re.fullmatch(r"([A-Za-z-]+): (.+)", line)
            if match is None or match.group(1) in fields:
                raise MirrorSchemaError("invalid source field")
            fields[match.group(1)] = match.group(2)

        if not mandatory_fields <= set(fields) or set(fields) - mandatory_fields - {
            "Architectures"
        }:
            raise MirrorSchemaError("unrecognized source fields")
        # An explicit architecture restriction in the upstream image is safe
        # only if both signed pockets retain the same x86-64 restriction.
        has_architecture = "Architectures" in fields
        if has_architecture and fields["Architectures"] != "amd64":
            raise MirrorSchemaError("unrecognized source architecture")
        if architecture_seen is not None and (has_architecture != architecture_seen):
            raise MirrorSchemaError("unequal source architectures")
        architecture_seen = has_architecture
        uri = fields["URIs"]
        kind = _source_kind(uri)
        if kind in found:
            raise MirrorSchemaError("duplicate Ubuntu pocket")
        current_components = set(fields["Components"].split())
        if (
            fields["Types"] != "deb"
            or fields["Signed-By"] != KEY
            or not _components_verified(fields["Components"])
            or fields["Suites"]
            != ("noble-security" if kind == "security" else "noble noble-updates noble-backports")
        ):
            raise MirrorSchemaError("unrecognized signed Noble pocket")
        if component_set is not None and current_components != component_set:
            raise MirrorSchemaError("unequal Ubuntu component pockets")
        component_set = current_components
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
    component_set: set[str] | None = None
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
        current_components = set(match.group("components").split())
        if component_set is not None and component_set != current_components:
            raise MirrorSchemaError("unequal legacy component pockets")
        component_set = current_components
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
    except MirrorSchemaError as exc:
        # Diagnostic detail is selected from our fixed parser errors only.
        # It cannot include source URIs, tokens, keys, or file contents.
        detail = str(exc).upper().replace(" ", "_")
        print(
            f"BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA detail={detail}", file=sys.stderr
        )
        return 1
    except (OSError, UnicodeError):
        print("BOCA_APT_FALLBACK state=NO_GO reason=SOURCE_IO", file=sys.stderr)
        return 1
    print("BOCA_APT_FALLBACK state=READY mirror=kernel_archives")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
