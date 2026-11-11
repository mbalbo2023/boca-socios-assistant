"""R179 reversible Boca-only binding relocation, isolated fake user manager."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_replace as replace
from boca_socios import host_on_demand_service as service
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

OLD = "42806447101"
NEW = "43080012345"


@pytest.fixture
def installation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[OnDemandInstallation, Path, dict[str, object]]:
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path / "lease")
    (tmp_path / "lease").mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    home = tmp_path / "boca-deploy"
    home.mkdir(mode=0o700)
    monkeypatch.setattr(service, "_home", lambda: home)
    units = home / ".config" / "systemd" / "user"
    (units / "default.target.wants").mkdir(parents=True, mode=0o700)
    root = home / ".boca-on-demand"
    root.mkdir(mode=0o700)
    socket = root / "socket"
    socket.mkdir(mode=0o711)

    original = OnDemandInstallation(
        installation_run_id=OLD,
        source_sha="03df9a14bdd78cf768386a865876fed9d5656911",
        controller_id="c" * 64,
        controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        worker_id="d" * 64,
        worker_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64,
        database_path=home / service._DB,
        pair=ReviewedInstalledPair(OLD, "1" * 64, "2" * 64),
    )
    monkeypatch.setattr(
        host, "_browser_docker_ids", lambda: {original.controller_id, original.worker_id}
    )

    def docker_record(cid: str) -> dict[str, object]:
        if cid == original.controller_id:
            role, image = "controller", original.controller_image
        elif cid == original.worker_id:
            role, image = "browser-worker", original.worker_image
        else:
            raise ValueError("unknown fake CID")
        return {
            "Id": cid,
            "State": {
                "Running": role == "controller",
                "Pid": 127 if role == "controller" else 0,
            },
            "Config": {
                "Image": image,
                "Labels": {
                    "com.docker.compose.project": host.PROJECT,
                    "com.docker.compose.service": role,
                    host.BROWSER_ATTEMPT_LABEL: original.installation_run_id,
                    "org.opencontainers.image.revision": original.source_sha,
                },
            },
        }

    monkeypatch.setattr(host, "_browser_inspect_record", docker_record)

    def write(path: Path, data: bytes) -> None:
        path.write_bytes(data)
        path.chmod(0o600)

    write(root / "attempt", (OLD + "\n").encode("ascii"))
    archive = b"fake signed immutable archive bytes"
    archive_digest = hashlib.sha256(archive).hexdigest()
    raw_plan = service._plan(home, original, archive_digest)
    write(root / "binding.json", raw_plan)
    write(root / "handler.pyz", archive)
    for name, data in service._units(archive_digest, hashlib.sha256(raw_plan).hexdigest()).items():
        write(root / name, data)
        os.link(root / name, units / name)
    (units / "default.target.wants" / service._SOCKET).symlink_to("../" + service._SOCKET)

    systemd: dict[str, object] = {"active": True, "events": [], "failure": ""}

    def state(_: Path, name: str) -> dict[str, str]:
        target = units / name
        present = target.exists()
        active = bool(systemd["active"]) and name == service._SOCKET and present
        return {
            "LoadState": "loaded" if present else "not-found",
            "FragmentPath": str(target) if present else "",
            "DropInPaths": "",
            "ActiveState": "active" if active else "inactive",
            "SubState": "listening" if active else "dead",
        }

    def systemctl(_: Path, *args: str) -> str:
        events = systemd["events"]
        if isinstance(events, list):
            events.append(args)
        if systemd["failure"] == args[0]:
            raise service.ControlRefused("injected manager failure")
        if args[0] == "stop":
            systemd["active"] = False
        if args[0] == "start":
            systemd["active"] = True
        return ""

    monkeypatch.setattr(service, "_state", state)
    monkeypatch.setattr(service, "_systemctl", systemctl)
    monkeypatch.setattr(service, "_socket", lambda *_args, **_kwargs: None)
    return original, home, systemd


def test_park_and_restore_exact_installation_and_user_unit_links(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
) -> None:
    original, home, systemd = installation
    with cleanup.protected_boca_job_lease(NEW) as lease:
        stash = replace.park_binding(original, NEW, lease)
        assert stash == home / f".boca-on-demand-parked-{NEW}"
        assert stash.is_dir() and not (home / ".boca-on-demand").exists()
        assert not (home / ".config/systemd/user/boca-bot-control.socket").exists()
        assert systemd["active"] is False
        replace.restore_binding(original, NEW, lease)
        assert service._verified_installation(home) == original
    assert not stash.exists()
    assert (home / ".config/systemd/user/default.target.wants/boca-bot-control.socket").is_symlink()


def test_prepared_new_attempt_binding_removed_before_old_restore(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
) -> None:
    original, home, _ = installation
    with cleanup.protected_boca_job_lease(NEW) as lease:
        replace.park_binding(original, NEW, lease)
        service.prepare_control_directory(NEW, lease)
        replace.restore_binding(original, NEW, lease)
        assert service._verified_installation(home) == original


def test_old_binding_restoration_rejects_running_browser_worker(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, _, _ = installation
    original_inspect = host._browser_inspect_record

    def invalid_worker_record(cid: str) -> dict[str, object]:
        record = original_inspect(cid)
        if cid == original.worker_id:
            record["State"] = {"Running": True, "Pid": 512}
        return record

    monkeypatch.setattr(host, "_browser_inspect_record", invalid_worker_record)
    with pytest.raises(service.ControlRefused):
        replace._old_pair_only(original)


def test_repeat_park_fails_closed_and_does_not_touch_old_archive(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
) -> None:
    original, home, _ = installation
    with cleanup.protected_boca_job_lease(NEW) as lease:
        replace.park_binding(original, NEW, lease)
        archive = (home / f".boca-on-demand-parked-{NEW}/handler.pyz").read_bytes()
        with pytest.raises(service.ControlRefused):
            replace.park_binding(original, NEW, lease)
        assert (home / f".boca-on-demand-parked-{NEW}/handler.pyz").read_bytes() == archive


def test_restore_refuses_missing_stash_or_alien_root(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
) -> None:
    original, home, _ = installation
    with cleanup.protected_boca_job_lease(NEW) as lease:
        with pytest.raises(service.ControlRefused):
            replace.restore_binding(original, NEW, lease)
        replace.park_binding(original, NEW, lease)
        (home / ".boca-on-demand").mkdir(mode=0o700)
        (home / ".boca-on-demand/attempt").write_text("9999999999\n")
        (home / ".boca-on-demand/attempt").chmod(0o600)
        with pytest.raises(service.ControlRefused):
            replace.restore_binding(original, NEW, lease)


def test_systemd_failure_before_park_can_be_recovered_same_lease(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
) -> None:
    original, home, systemd = installation
    with cleanup.protected_boca_job_lease(NEW) as lease:
        systemd["failure"] = "daemon-reload"
        with pytest.raises(service.ControlRefused):
            replace.park_binding(original, NEW, lease)
        assert (home / ".boca-on-demand").exists()
        systemd["failure"] = ""
        replace.restore_binding(original, NEW, lease)
        assert service._verified_installation(home) == original


def test_no_silent_foreign_unit_link_replacement(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
) -> None:
    original, home, _ = installation
    units = home / ".config/systemd/user"
    (units / service._SERVICE).unlink()
    alien = units / service._SERVICE
    alien.write_bytes(b"foreign unit bytes")
    alien.chmod(0o600)
    with cleanup.protected_boca_job_lease(NEW) as lease:
        with pytest.raises(service.ControlRefused):
            replace.park_binding(original, NEW, lease)
        assert alien.read_bytes() == b"foreign unit bytes"


def test_park_refuses_preexisting_removing_marker(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
) -> None:
    original, home, systemd = installation
    (home / ".boca-on-demand/removing").write_bytes(b"half removed")
    (home / ".boca-on-demand/removing").chmod(0o600)
    with cleanup.protected_boca_job_lease(NEW) as lease:
        with pytest.raises(service.ControlRefused):
            replace.park_binding(original, NEW, lease)
    assert systemd["events"] == []


def test_restore_requires_original_pair_exact_cids_not_a_foreign_third(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, _, _ = installation
    with cleanup.protected_boca_job_lease(NEW) as lease:
        replace.park_binding(original, NEW, lease)
        monkeypatch.setattr(
            host,
            "_browser_docker_ids",
            lambda: {original.controller_id, original.worker_id, "f" * 64},
        )
        with pytest.raises(service.ControlRefused):
            replace.restore_binding(original, NEW, lease)


def test_restore_requires_old_role_labels_after_rename(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, _, _ = installation
    with cleanup.protected_boca_job_lease(NEW) as lease:
        replace.park_binding(original, NEW, lease)
        monkeypatch.setattr(
            host,
            "_browser_inspect_record",
            lambda cid: {
                "Id": cid,
                "Config": {"Image": original.controller_image, "Labels": {}},
            },
        )
        with pytest.raises(service.ControlRefused):
            replace.restore_binding(original, NEW, lease)


def test_commit_requires_new_pair_evidence_before_deleting_old_archive(
    installation: tuple[OnDemandInstallation, Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace as dataclass_replace

    original, home, systemd = installation
    successor = dataclass_replace(
        original,
        installation_run_id=NEW,
        source_sha="a" * 40,
        controller_id="3" * 64,
        worker_id="4" * 64,
        pair=ReviewedInstalledPair(NEW, "5" * 64, "6" * 64),
    )
    with cleanup.protected_boca_job_lease(NEW) as lease:
        parked = replace.park_binding(original, NEW, lease)
        new_root = home / ".boca-on-demand"
        new_root.mkdir(mode=0o700)
        (new_root / "attempt").write_text(NEW + "\n")
        (new_root / "attempt").chmod(0o600)
        monkeypatch.setattr(service, "_verified_installation", lambda h: successor)
        monkeypatch.setattr(
            replace, "_new_pair_only", lambda n: (_ for _ in ()).throw(service._refuse())
        )
        with pytest.raises(service.ControlRefused):
            replace.commit_binding(original, successor, NEW, lease)
        assert (parked / "handler.pyz").exists()
        monkeypatch.setattr(replace, "_new_pair_only", lambda n: None)
        replace.commit_binding(original, successor, NEW, lease)
        assert not parked.exists()
        assert systemd["active"] is False
