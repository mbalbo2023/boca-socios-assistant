"""Exercise the image's exact-file removal using an inert filesystem boundary."""

from __future__ import annotations

import builtins
import hashlib
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
IDENTITIES = {
    "amd64": (
        10_563_744,
        "7c893d09a9ecb877dee7ccb3523865c9811ced7b35500e5b3f0e8b11d89f306d",
    ),
    "arm64": (
        9_765_024,
        "12ea522e4d8b35d4e63b6afb6384d8622e05b9f0d8c0a30408ecfe6ecc19868d",
    ),
}


def _cleanup_source() -> str:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    matches = re.findall(
        r"^RUN /usr/bin/python3 -I -c '([^']*)'", dockerfile.replace("\\\n", ""), re.M
    )
    assert len(matches) == 1, "the image needs one isolated exact-file cleanup guard"
    return matches[0]


class ImageBoundary:
    """Only OS/package/artifact identities are substituted; removal is real."""

    def __init__(self, root: Path, architecture: str = "amd64") -> None:
        self.root = root
        self.architecture = architecture
        self.pebble = root / "usr/bin/pebble"
        self.pebble.parent.mkdir(parents=True)
        (root / "bin").symlink_to("usr/bin")
        size, digest = IDENTITIES.get(architecture, IDENTITIES["amd64"])
        payload = bytes(size)
        self.pebble.write_bytes(payload)
        self.pebble.chmod(0o755)
        self.fixture_digest = hashlib.sha256(payload).hexdigest()
        self.image_digest = digest
        self.metadata: dict[str, int] = {}
        self.owner_results: dict[str, tuple[int, str, str]] = {}
        self.architecture_error: Exception | None = None
        self.queries: list[str] = []
        self.post_unlink = False
        self.replace_during_query = False
        self.unlink_error: Exception | None = None

    def path(self, value: str) -> Path:
        path = Path(value)
        return self.root / path.relative_to("/") if path.is_absolute() else path

    def run(self, arguments: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        assert options["capture_output"] is True and options["text"] is True
        assert options["timeout"] == 5 and options["env"] == {"LC_ALL": "C"}
        if arguments == ["/usr/bin/dpkg", "--print-architecture"]:
            assert options.get("check") is True
            if self.architecture_error is not None:
                raise self.architecture_error
            return subprocess.CompletedProcess(arguments, 0, self.architecture + "\n", "")
        assert arguments[:2] == ["/usr/bin/dpkg-query", "--search"]
        assert len(arguments) == 3 and arguments[2] in ("/usr/bin/pebble", "/bin/pebble")
        name = arguments[2]
        self.queries.append(name)
        if self.replace_during_query and name == "/bin/pebble":
            replacement = self.pebble.with_suffix(".replacement")
            replacement.write_bytes(self.pebble.read_bytes())
            replacement.chmod(0o755)
            replacement.replace(self.pebble)
        default = (1, "", f"dpkg-query: no path found matching pattern {name}\n")
        return subprocess.CompletedProcess(arguments, *self.owner_results.get(name, default))

    def execute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        source = _cleanup_source()
        real_import = builtins.__import__
        real_digest = hashlib.sha256
        real_lstat = Path.lstat
        real_unlink = Path.unlink

        def sha256(data: bytes) -> Any:
            observed = real_digest(data)
            # No vulnerable executable is downloaded or executed by tests. Map
            # only the complete inert payload to the independently reviewed
            # OCI artifact identity; changed bytes retain their actual digest.
            if observed.hexdigest() == self.fixture_digest:
                return SimpleNamespace(hexdigest=lambda: self.image_digest)
            return observed

        def lstat(path: Path, **options: Any) -> Any:
            observed = real_lstat(path, **options)
            if path != self.pebble:
                return observed
            values = {
                name: getattr(observed, name)
                for name in (
                    "st_mode",
                    "st_uid",
                    "st_gid",
                    "st_nlink",
                    "st_size",
                    "st_dev",
                    "st_ino",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            }
            # The local test user is unprivileged; image ownership is an OS
            # boundary. Mode/type/size/inode and filesystem effects stay real.
            values.update(st_uid=0, st_gid=0)
            values.update(self.metadata)
            return SimpleNamespace(**values)

        def unlink(path: Path, **options: Any) -> None:
            if path == self.pebble and self.unlink_error is not None:
                raise self.unlink_error
            real_unlink(path, **options)
            if self.post_unlink and path == self.pebble:
                path.symlink_to("missing-replacement")

        modules = {
            "pathlib": SimpleNamespace(Path=self.path),
            "hashlib": SimpleNamespace(sha256=sha256),
            "subprocess": SimpleNamespace(run=self.run),
        }

        def import_boundary(name: str, *arguments: Any, **options: Any) -> Any:
            return modules[name] if name in modules else real_import(name, *arguments, **options)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "lstat", lstat)
            patch.setattr(Path, "unlink", unlink)
            patch.setenv("PATH", "/usr/bin:/bin:/opt/extra/bin")
            exec(  # noqa: S102 - fixed repository guard; OS/artifact boundaries are inert.
                compile(source, "Dockerfile.browser:pebble-cleanup", "exec"),
                {"__builtins__": {**vars(builtins), "__import__": import_boundary}},
            )


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_exact_unowned_binary_is_removed_but_other_files_survive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, architecture: str
) -> None:
    image = ImageBoundary(tmp_path, architecture)
    metadata = tmp_path / "usr/share/rock-info/metadata.yaml"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("retained source metadata\n")
    unrelated = image.pebble.with_name("another-tool")
    unrelated.write_bytes(b"retained executable")
    image.execute(monkeypatch)
    assert not os.path.lexists(image.pebble)
    assert not os.path.lexists(tmp_path / "bin/pebble")
    assert image.queries == ["/usr/bin/pebble", "/bin/pebble"]
    assert metadata.read_text() == "retained source metadata\n"
    assert unrelated.read_bytes() == b"retained executable"


def test_changed_binary_bytes_are_preserved_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = ImageBoundary(tmp_path)
    with image.pebble.open("r+b") as stream:
        stream.write(b"different bytes")
    with pytest.raises(AssertionError, match="pebble_identity_unverified"):
        image.execute(monkeypatch)
    assert image.pebble.is_file() and not image.queries


@pytest.mark.parametrize("architecture", ["armhf", "", "amd64\narm64"])
def test_unreviewed_architecture_never_uses_another_architectures_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, architecture: str
) -> None:
    image = ImageBoundary(tmp_path, architecture)
    with pytest.raises(AssertionError, match="pebble_architecture_unverified"):
        image.execute(monkeypatch)
    assert image.pebble.is_file() and not image.queries


def test_arm64_cannot_use_the_amd64_binary_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = ImageBoundary(tmp_path, "arm64")
    image.image_digest = IDENTITIES["amd64"][1]
    with pytest.raises(AssertionError, match="pebble_identity_unverified"):
        image.execute(monkeypatch)
    assert image.pebble.is_file()


@pytest.mark.parametrize(
    "metadata",
    [{"st_uid": 10002}, {"st_gid": 10002}, {"st_nlink": 2}],
)
def test_unexpected_custody_or_hardlinks_block_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, int]
) -> None:
    image = ImageBoundary(tmp_path)
    image.metadata = metadata
    with pytest.raises(AssertionError, match="pebble_file_unverified"):
        image.execute(monkeypatch)
    assert image.pebble.is_file() and not image.queries


@pytest.mark.parametrize("replacement", ["directory", "symlink", "wrong_mode", "wrong_size"])
def test_unexpected_filesystem_shape_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    image = ImageBoundary(tmp_path)
    if replacement in {"directory", "symlink"}:
        image.pebble.unlink()
        if replacement == "directory":
            image.pebble.mkdir()
        else:
            image.pebble.symlink_to("another-tool")
    elif replacement == "wrong_mode":
        image.pebble.chmod(0o775)
    else:
        image.pebble.write_bytes(b"unexpected size")
    with pytest.raises(AssertionError, match="pebble_(file|identity)_unverified"):
        image.execute(monkeypatch)
    assert os.path.lexists(image.pebble) and not image.queries


@pytest.mark.parametrize("alias", ["usr/sbin", "/usr/bin", "directory"])
def test_unexpected_bin_alias_blocks_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: str
) -> None:
    image = ImageBoundary(tmp_path)
    (tmp_path / "bin").unlink()
    if alias == "directory":
        (tmp_path / "bin").mkdir()
    else:
        (tmp_path / "bin").symlink_to(alias)
    with pytest.raises(AssertionError, match="pebble_alias_unverified"):
        image.execute(monkeypatch)
    assert image.pebble.is_file() and not image.queries


@pytest.mark.parametrize("owned_path", ["/usr/bin/pebble", "/bin/pebble"])
@pytest.mark.parametrize(
    "result",
    [
        (0, "some-package: /usr/bin/pebble\n", ""),
        (2, "", "database failed"),
        (1, "unexpected owner output", ""),
        (1, "", "unrecognized failure"),
    ],
)
def test_owned_or_unverifiable_binary_is_not_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owned_path: str,
    result: tuple[int, str, str],
) -> None:
    image = ImageBoundary(tmp_path)
    image.owner_results[owned_path] = result
    with pytest.raises(AssertionError, match="pebble_ownership_unverified"):
        image.execute(monkeypatch)
    assert image.pebble.is_file()


@pytest.mark.parametrize("error", [OSError("unavailable"), subprocess.TimeoutExpired("dpkg", 5)])
def test_architecture_query_failure_propagates_without_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    image = ImageBoundary(tmp_path)
    image.architecture_error = error
    with pytest.raises(type(error)):
        image.execute(monkeypatch)
    assert image.pebble.is_file() and not image.queries


def test_dangling_replacement_after_unlink_fails_the_absence_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = ImageBoundary(tmp_path)
    image.post_unlink = True
    with pytest.raises(AssertionError, match="pebble_absence_unverified"):
        image.execute(monkeypatch)
    assert image.pebble.is_symlink()


def test_other_path_copy_is_reported_without_deleting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = ImageBoundary(tmp_path)
    extra = tmp_path / "opt/extra/bin/pebble"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"unreviewed other binary")
    with pytest.raises(AssertionError, match="pebble_absence_unverified"):
        image.execute(monkeypatch)
    assert not os.path.lexists(image.pebble)
    assert extra.read_bytes() == b"unreviewed other binary"


def test_replaced_inode_after_hashing_is_preserved_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = ImageBoundary(tmp_path)
    image.replace_during_query = True
    before = image.pebble.stat().st_ino
    with pytest.raises(AssertionError, match="pebble_identity_changed"):
        image.execute(monkeypatch)
    assert image.pebble.is_file() and image.pebble.stat().st_ino != before


def test_failed_unlink_is_a_build_failure_without_other_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = ImageBoundary(tmp_path)
    image.unlink_error = PermissionError("inert denied removal")
    with pytest.raises(PermissionError):
        image.execute(monkeypatch)
    assert image.pebble.is_file()
