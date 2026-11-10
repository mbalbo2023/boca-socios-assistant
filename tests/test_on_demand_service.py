"""Offline activation and compensation with real AF_UNIX and disposable unit fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair

ATTEMPT = "622"
OP = "2a9f2a37-7e72-5ac2-b58d-517330c57d1c"
CTL = "a" * 64
ZIP = b"fixture public run archive"
SOCKET = "boca-bot-control.socket"
UNIT = "boca-bot-control@.service"


def installation(home: Path):
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

    return OnDemandInstallation(
        installation_run_id=ATTEMPT,
        source_sha="9" * 40,
        controller_id=CTL,
        controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        worker_id="c" * 64,
        worker_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "d" * 64,
        database_path=home / ".local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3",
        pair=ReviewedInstalledPair(ATTEMPT, "e" * 64, "f" * 64),
    )


@pytest.mark.parametrize(
    "payload,accepted",
    [
        ((OP + "\n").encode(), True),
        ((OP.upper() + "\n").encode(), False),
        ((OP + "\n\n").encode(), False),
        (OP.encode(), False),
        (b"00000000-0000-0000-0000-000000000000\n", False),
        ((OP + "\n" + OP + "\n").encode(), False),
        (b"start\n", False),
    ],
)
def test_only_one_closed_uuid_frame(tmp_path, payload, accepted):
    effects = []
    item = installation(tmp_path)
    with pair() as (server, client):
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        assert (
            service.handle_connection(
                server,
                item,
                peer_check=lambda conn, binding: True,
                apply=lambda op, binding: effects.append((op, binding)),
            )
            is accepted
        )
    assert effects == ([(OP, item)] if accepted else [])


@contextmanager
def pair() -> Iterator[tuple[socket.socket, socket.socket]]:
    server, client = socket.socketpair()
    with server, client:
        yield server, client


def test_rejected_peer_never_applies(tmp_path):
    with pair() as (server, client):
        client.sendall((OP + "\n").encode())
        client.shutdown(socket.SHUT_WR)
        assert not service.handle_connection(
            server,
            installation(tmp_path),
            peer_check=lambda conn, binding: False,
            apply=lambda *unused: pytest.fail("foreign peer reached effect"),
        )


def test_peer_requires_exact_cgroup_and_matching_host_mapping(tmp_path, monkeypatch):
    # The kernel supplies the actual socketpair credentials. Only Docker/proc metadata is faked.
    item = installation(tmp_path)
    with pair() as (server, _):
        uid, gid = os.geteuid(), os.getegid()
        me = os.getpid()
        cgroup = f"0::/user.slice/test/docker-{CTL}.scope\n"
        facts = {"uid_map": f"10001 {uid} 1\n", "gid_map": f"10001 {gid} 1\n", "cgroup": cgroup}
        monkeypatch.setattr(service, "_controller_pid", lambda _cid: me)
        monkeypatch.setattr(service, "_proc_field", lambda pid, name: facts[name])
        assert service.verify_controller_peer(server, item)
        facts["gid_map"] = f"10001 {gid + 1} 1\n"
        assert not service.verify_controller_peer(server, item)
        facts["gid_map"] = f"10001 {gid} 1\n"
        for wrong in ("0::/\n", f"0::/docker-{CTL}0.scope\n", "0::/user.slice/shared\n"):
            facts["cgroup"] = wrong
            assert not service.verify_controller_peer(server, item)


class Manager:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.active = False
        self.known = False
        self.foreign = False
        self.effects = []

    def __call__(self, home: Path, *args: str) -> str:
        assert home == self.home
        folder = home / ".config/systemd/user"
        if args[0] == "show":
            unit = args[-1]
            target = SOCKET if unit == SOCKET else UNIT
            present = self.known and (folder / target).exists()
            if self.foreign:
                return "LoadState=loaded\nFragmentPath=/etc/foreign.socket\nDropInPaths=\nActiveState=inactive\nSubState=dead\n"
            return (
                f"LoadState={'loaded' if present else 'not-found'}\n"
                f"FragmentPath={folder / target if present else ''}\nDropInPaths=\n"
                f"ActiveState={'active' if self.active and target == SOCKET else 'inactive'}\n"
                f"SubState={'listening' if self.active and target == SOCKET else 'dead'}\n"
            )
        self.effects.append(args)
        if args == ("daemon-reload",):
            self.known = True
        elif args == ("start", SOCKET):
            path = home / ".boca-on-demand/socket/control.sock"
            # A unit-manager fixture creates only the expected inode. Wire tests use real pairs.
            os.mknod(path, stat.S_IFSOCK | 0o600)
            path.chmod(0o666)
            self.active = True
        elif args == ("stop", SOCKET):
            (home / ".boca-on-demand/socket/control.sock").unlink()
            self.active = False
        else:
            pytest.fail(f"unexpected unit mutation {args}")
        return ""


@pytest.fixture
def host(tmp_path, monkeypatch):
    home = tmp_path
    unit = home / ".config/systemd/user"
    (unit / "default.target.wants").mkdir(parents=True)
    for path in (home, home / ".config", unit.parent, unit, unit / "default.target.wants"):
        path.chmod(0o700)
    manager = Manager(home)
    lease = BocaJobLease(ATTEMPT, 5, os.getpid(), True)
    monkeypatch.setattr(service, "_home", lambda: home)
    monkeypatch.setattr(service, "_systemctl", manager)
    monkeypatch.setattr(service, "_bundle", lambda expected: ZIP)
    monkeypatch.setattr(
        service,
        "_verify_lease",
        lambda proof, run: (
            None if (proof is lease and run == ATTEMPT) else pytest.fail("missing exact lease")
        ),
    )
    yield home, unit, manager, lease


def test_install_repeat_committed_binding_then_remove(host):
    home, unit, manager, lease = host
    item = installation(home)
    root = home / ".boca-on-demand"
    assert service.prepare_control_directory(ATTEMPT, lease) == root / "socket"
    service.install_control(item, lease)
    service.install_control(item, lease)
    assert service.read_installed_binding(lease) == item
    assert manager.effects.count(("start", SOCKET)) == 1
    assert (unit / UNIT).samefile(root / UNIT)
    assert (unit / SOCKET).samefile(root / SOCKET)
    assert "Accept=yes" in (unit / SOCKET).read_text()
    assert "StandardInput=socket" in (unit / UNIT).read_text()
    plan = (root / "binding.json").read_bytes()
    assert json.loads(plan)["bundle_sha256"] == hashlib.sha256(ZIP).hexdigest()
    assert hashlib.sha256(plan).hexdigest() in (unit / UNIT).read_text()
    service.remove_control(ATTEMPT, lease)
    service.remove_control(ATTEMPT, lease)
    assert not root.exists() and not (unit / UNIT).exists() and not manager.active


def test_prepared_only_and_unowned_files_are_preserved(host):
    home, unit, manager, lease = host
    path = service.prepare_control_directory(ATTEMPT, lease)
    service.remove_control(ATTEMPT, lease)
    assert not path.exists()
    service.prepare_control_directory(ATTEMPT, lease)
    (unit / SOCKET).write_bytes(b"foreign")
    with pytest.raises(service.ControlRefused):
        service.install_control(installation(home), lease)
    service.remove_control(ATTEMPT, lease)
    assert (unit / SOCKET).read_bytes() == b"foreign"
    assert manager.effects == []


def test_compensation_preserves_drift_and_foreign_fragment(host):
    home, unit, manager, lease = host
    service.prepare_control_directory(ATTEMPT, lease)
    manager.foreign = True
    with pytest.raises(service.ControlRefused):
        service.install_control(installation(home), lease)
    assert not manager.effects
    manager.foreign = False
    service.install_control(installation(home), lease)
    (unit / UNIT).unlink()
    (unit / UNIT).write_text("unowned replacement")
    with pytest.raises(service.ControlRefused):
        service.remove_control(ATTEMPT, lease)
    assert manager.active and (unit / UNIT).read_text() == "unowned replacement"


def test_derived_archive_contains_only_reviewed_runtime_entries():
    import io
    import zipfile

    full = io.BytesIO()
    with zipfile.ZipFile(full, "w") as package:
        for name in service._RUNTIME_FILES:
            package.writestr(name, "trusted source fixture " + name)
        package.writestr("scripts/historical_recovery.py", b"never persist this")
        package.writestr("__main__.py", b"never install the general Cutover dispatcher")
    derived = service._runtime_archive(full.getvalue())
    assert service._runtime_archive(full.getvalue()) == derived
    with zipfile.ZipFile(io.BytesIO(derived)) as bundle:
        assert set(bundle.namelist()) == {*service._RUNTIME_FILES, "__main__.py"}
        assert b"on-demand-serve" in bundle.read("__main__.py")
        assert b"general Cutover" not in bundle.read("__main__.py")


def test_exec_pins_archive_and_uses_sealed_bytes(tmp_path):
    import subprocess
    import zipfile

    archive = tmp_path / "fixture.pyz"
    code = (
        "import fcntl,sys\n"
        "fd=int(sys.argv[0].rsplit('/',1)[1])\n"
        "seals=fcntl.fcntl(fd,fcntl.F_GET_SEALS)\n"
        "raise SystemExit(0 if sys.argv[1:]==['on-demand-serve','binding'] and "
        "seals & fcntl.F_SEAL_WRITE else 9)\n"
    )
    with zipfile.ZipFile(archive, "w") as fixture:
        fixture.writestr("__main__.py", code)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    command = [
        "/usr/bin/python3",
        "-I",
        "-B",
        "-c",
        service._LOADER,
        str(archive),
        digest,
        "binding",
    ]
    assert subprocess.run(command, check=False, capture_output=True).returncode == 0  # noqa: S603
    archive.write_bytes(b"changed")
    result = subprocess.run(command, check=False, capture_output=True)  # noqa: S603
    assert (result.returncode, result.stdout, result.stderr) == (3, b"", b"")


def test_verification_stops_on_altered_private_bundle_or_binding(host):
    home, _, _, lease = host
    service.prepare_control_directory(ATTEMPT, lease)
    item = installation(home)
    service.install_control(item, lease)
    root = home / ".boca-on-demand"
    archive = root / "handler.pyz"
    archive.write_bytes(b"unexpected bytes")
    with pytest.raises(service.ControlRefused):
        service.verify_control(item, lease)
    with pytest.raises(service.ControlRefused):
        service.remove_control(ATTEMPT, lease)
    archive.write_bytes(ZIP)
    marker = root / "binding.json"
    marker.write_bytes(marker.read_bytes() + b" ")
    with pytest.raises(service.ControlRefused):
        service.verify_control(item, lease)
    with pytest.raises(service.ControlRefused):
        service.remove_control(ATTEMPT, lease)


def test_unrelated_preexisting_directory_and_symlink_preserved(host):
    home, _, manager, lease = host
    root = home / ".boca-on-demand"
    root.mkdir(mode=0o700)
    (root / "foreign").write_text("keep")
    with pytest.raises((OSError, service.ControlRefused)):
        service.prepare_control_directory(ATTEMPT, lease)
    assert (root / "foreign").read_text() == "keep" and not manager.effects
    (root / "foreign").unlink()
    root.rmdir()
    (home / "other").mkdir()
    root.symlink_to(home / "other")
    with pytest.raises(service.ControlRefused):
        service.prepare_control_directory(ATTEMPT, lease)
    assert root.is_symlink() and not list((home / "other").iterdir())


def test_failed_start_can_be_compensated_without_a_listener(host, monkeypatch):
    home, unit, manager, lease = host
    service.prepare_control_directory(ATTEMPT, lease)

    def failed_start(home, *args):
        if args == ("start", SOCKET):
            raise service.ControlRefused("injected unreachable service")
        return manager(home, *args)

    monkeypatch.setattr(service, "_systemctl", failed_start)
    with pytest.raises(service.ControlRefused):
        service.install_control(installation(home), lease)
    service.remove_control(ATTEMPT, lease)
    assert not (home / ".boca-on-demand").exists()
    assert not (unit / SOCKET).exists() and not (unit / UNIT).exists()


def test_units_pass_offline_systemd_verifier(tmp_path):
    import shutil
    import subprocess

    verifier = shutil.which("systemd-analyze")
    if not verifier:
        pytest.skip("systemd's offline unit verifier unavailable")
    files = []
    for name, data in service._units("a" * 64, "b" * 64).items():
        path = tmp_path / name
        path.write_bytes(data)
        files.append(str(path))
    result = subprocess.run(  # noqa: S603
        [verifier, "verify", "--man=no", "--generators=no", "--recursive-errors=no", *files],
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
