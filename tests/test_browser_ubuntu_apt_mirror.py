"""APT mirror fallback must preserve signed Noble sources or refuse to rewrite."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ARCHIVE = "http://azure.archive.ubuntu.com/ubuntu/"
SECURITY = "http://security.ubuntu.com/ubuntu/"
MIRROR = "https://mirrors.edge.kernel.org/ubuntu/"
KEY = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"


def _run_tool(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed script and isolated tmp_path, no shell
        [sys.executable, str(ROOT / "scripts/browser_ubuntu_apt_mirror.py"), str(root)],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )


def _deb822(*, key: str = KEY, security_suite: str = "noble-security") -> str:
    return (
        "Types: deb\n"
        f"URIs: {ARCHIVE}\n"
        "Suites: noble noble-updates noble-backports\n"
        "Components: main restricted universe multiverse\n"
        f"Signed-By: {key}\n\n"
        "Types: deb\n"
        f"URIs: {SECURITY}\n"
        f"Suites: {security_suite}\n"
        "Components: main restricted universe multiverse\n"
        f"Signed-By: {key}\n"
    )


def test_rewrites_only_ubuntu_mirror_uris_and_preserves_signed_pockets(tmp_path: Path) -> None:
    source = tmp_path / "sources.list.d" / "ubuntu.sources"
    source.parent.mkdir()
    source.write_text(_deb822(), encoding="utf-8")

    result = _run_tool(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "BOCA_APT_FALLBACK state=READY" in result.stdout
    expected = _deb822().replace(ARCHIVE, MIRROR).replace(SECURITY, MIRROR)
    assert source.read_text(encoding="utf-8") == expected


def test_accepts_canonical_noble_component_order_and_uri_without_slash(tmp_path: Path) -> None:
    source = tmp_path / "sources.list.d" / "ubuntu.sources"
    source.parent.mkdir()
    upstream = (
        _deb822()
        .replace(ARCHIVE, "http://archive.ubuntu.com/ubuntu")
        .replace(SECURITY, "http://security.ubuntu.com/ubuntu")
        .replace(
            "Components: main restricted universe multiverse",
            "Components: main universe restricted multiverse",
        )
    )
    source.write_text(upstream, encoding="utf-8")

    result = _run_tool(tmp_path)

    assert result.returncode == 0, result.stderr
    actual = source.read_text(encoding="utf-8")
    assert actual.count(f"URIs: {MIRROR}") == 2
    assert actual.count("Components: main universe restricted multiverse") == 2
    assert actual.count(f"Signed-By: {KEY}") == 2


def test_rejects_non_ubuntu_component(tmp_path: Path) -> None:
    source = tmp_path / "sources.list.d" / "ubuntu.sources"
    source.parent.mkdir()
    malformed = _deb822().replace(
        "Components: main restricted universe multiverse", "Components: main outsider", 1
    )
    source.write_text(malformed, encoding="utf-8")

    result = _run_tool(tmp_path)

    assert result.returncode != 0
    assert source.read_text(encoding="utf-8") == malformed


@pytest.mark.parametrize(
    "bad_contents",
    [
        _deb822(key="/untrusted-keyring.gpg"),
        _deb822(security_suite="noble-proposed"),
        _deb822().replace(ARCHIVE, "https://unrelated.invalid/ubuntu/"),
        _deb822().replace("Types: deb", "Types: deb-src", 1),
        _deb822().replace("Signed-By:", "Trusted: yes\nSigned-By:", 1),
        _deb822() + "\nTypes: deb\nURIs: https://extra.invalid/ubuntu/\n",
    ],
)
def test_does_not_mutate_unrecognized_or_untrusted_deb822(
    tmp_path: Path, bad_contents: str
) -> None:
    source = tmp_path / "sources.list.d" / "ubuntu.sources"
    source.parent.mkdir()
    source.write_text(bad_contents, encoding="utf-8")

    result = _run_tool(tmp_path)

    assert result.returncode != 0
    assert "BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA" in result.stderr
    assert source.read_text(encoding="utf-8") == bad_contents


def test_rewrites_legacy_only_with_explicit_ubuntu_signed_by(tmp_path: Path) -> None:
    source = tmp_path / "sources.list"
    source.write_text(
        f"deb [signed-by={KEY}] {ARCHIVE} noble main restricted universe multiverse\n"
        f"deb [signed-by={KEY}] {ARCHIVE} noble-updates main restricted universe multiverse\n"
        f"deb [signed-by={KEY}] {ARCHIVE} noble-backports main restricted universe multiverse\n"
        f"deb [signed-by={KEY}] {SECURITY} noble-security main restricted universe multiverse\n",
        encoding="utf-8",
    )

    result = _run_tool(tmp_path)

    assert result.returncode == 0, result.stderr
    result = source.read_text(encoding="utf-8")
    assert result.count(MIRROR) == 4
    assert result.count(f"signed-by={KEY}") == 4
    assert "noble-security" in result


def test_rejects_unsigned_legacy_and_absent_sources(tmp_path: Path) -> None:
    source = tmp_path / "sources.list"
    source.write_text(f"deb {SECURITY} noble-security main universe\n", encoding="utf-8")
    result = _run_tool(tmp_path)
    assert result.returncode != 0
    assert "BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA" in result.stderr
    assert source.read_text(encoding="utf-8") == (f"deb {SECURITY} noble-security main universe\n")
    source.unlink()
    result = _run_tool(tmp_path)
    assert result.returncode != 0
    assert "BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA" in result.stderr


def test_rejects_parallel_deb822_and_legacy_ubuntu_sources(tmp_path: Path) -> None:
    deb822 = tmp_path / "sources.list.d" / "ubuntu.sources"
    deb822.parent.mkdir()
    deb822.write_text(_deb822(), encoding="utf-8")
    legacy = tmp_path / "sources.list"
    legacy.write_text(f"deb {SECURITY} noble-security main universe\n", encoding="utf-8")
    result = _run_tool(tmp_path)
    assert result.returncode != 0
    assert "BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA" in result.stderr
    assert deb822.read_text(encoding="utf-8") == _deb822()


def test_rejects_additional_enabled_apt_source_before_mutating(tmp_path: Path) -> None:
    ubuntu = tmp_path / "sources.list.d" / "ubuntu.sources"
    ubuntu.parent.mkdir()
    ubuntu.write_text(_deb822(), encoding="utf-8")
    extra = ubuntu.parent / "extra.list"
    extra.write_text("deb https://unreviewed.invalid/ubuntu noble main\n", encoding="utf-8")

    result = _run_tool(tmp_path)

    assert result.returncode != 0
    assert "BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA" in result.stderr
    assert ubuntu.read_text(encoding="utf-8") == _deb822()
