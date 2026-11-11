"""Reversible replacement boundary for Boca's already installed user socket.

No generic systemd/Compose/delete actions: only two attested, exact Boca
fragments, their hardlinks, and the private on-demand directory may change.
The historical archive and binding remain byte-for-byte in a private parked
directory until the new dual pair is durably accepted. The caller holds the
same rootless Boca lease while parking, installing, restoring or committing.

An interruption between substeps is never blindly retried by a new attempt;
the O_EXCL same-attempt marker and original hardlink/inode checks make drift
visible. The caller must log and reconcile any ambiguous I/O as NO_GO.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from boca_socios import host_boca_pair_observe as pair_observer
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_boca_cleanup import verify_protected_boca_job_lease as _verify_lease
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

_PARKED_PREFIX = ".boca-on-demand-parked-"
_INTENT_PREFIX = ".boca-on-demand-upgrade-"


def _name(home: Path, new_attempt: str) -> tuple[Path, Path]:
    service._check_attempt(new_attempt)
    return home / (_PARKED_PREFIX + new_attempt), home / (_INTENT_PREFIX + new_attempt)


def _proof(home: Path, old: OnDemandInstallation, new_attempt: str) -> bytes:
    # Canonical limited coordinates; no credentials, connection string or raw DB.
    return (
        "BOCA_BINDING_UPGRADE_V1 "
        + new_attempt
        + " "
        + old.installation_run_id
        + " "
        + old.fingerprint()
        + "\n"
    ).encode("ascii")


def _historic(root: Path, home: Path, old: OnDemandInstallation) -> dict[str, bytes]:
    service._directory(root, mode=0o700)
    if (
        service._present(root / service._REMOVING)
        or {p.name for p in root.iterdir()} - service._DATA
    ):
        raise service._refuse()
    if service._read(root / service._MARKER, 32) != service._check_attempt(old.installation_run_id):
        raise service._refuse()
    raw = service._read(root / service._BINDING, service._MAX_PLAN)
    found, digest = service._decode(home, raw)
    if (
        found != old
        or hashlib.sha256(service._read(root / service._ARCHIVE, service._MAX_ZIP)).hexdigest()
        != digest
    ):
        raise service._refuse()
    units = service._units(digest, hashlib.sha256(raw).hexdigest())
    for name, content in units.items():
        if service._read(root / name, len(content), links=(1, 2)) != content:
            raise service._refuse()
    service._directory(root / "socket", mode=0o711)
    if any(item.name != service._SOCKET_NAME for item in (root / "socket").iterdir()):
        raise service._refuse()
    return units


def _intended(home: Path, old: OnDemandInstallation, new_attempt: str) -> tuple[Path, Path]:
    parked, marker = _name(home, new_attempt)
    if not service._present(marker) or service._read(marker, 256) != _proof(home, old, new_attempt):
        raise service._refuse()
    return parked, marker


def _old_pair_only(old: OnDemandInstallation) -> None:
    """Current rootless daemon must contain exactly both old immutable CIDs.

    Names may have changed during park, but neither origin, role, image nor
    attempt may change. No candidate or third-party process may remain before
    restoring a live binding, and no mutation is attempted by this witness.
    """
    if host._browser_docker_ids() != {old.controller_id, old.worker_id}:
        raise service._refuse()
    for cid, name, image in (
        (old.controller_id, "controller", old.controller_image),
        (old.worker_id, "browser-worker", old.worker_image),
    ):
        record = host._browser_inspect_record(cid)
        config = record.get("Config")
        state = record.get("State")
        if not isinstance(config, dict):
            raise service._refuse()
        labels = config.get("Labels")
        if (
            record.get("Id") != cid
            or config.get("Image") != image
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != host.PROJECT
            or labels.get("com.docker.compose.service") != name
            or labels.get(host.BROWSER_ATTEMPT_LABEL) != old.installation_run_id
            or labels.get("org.opencontainers.image.revision") != old.source_sha
            or not isinstance(state, dict)
            or type(state.get("Running")) is not bool
            or (name == "browser-worker" and (state["Running"] or state.get("Pid") != 0))
        ):
            raise service._refuse()


def _new_pair_only(new: OnDemandInstallation) -> None:
    """Strict two-CID observer proves all historical CIDs are now absent."""
    import json

    raw = pair_observer.observe(new.installation_run_id)
    pair_observer.verify(raw, new.installation_run_id)
    observed = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
    services = observed.get("services")
    if (
        not isinstance(services, list)
        or len(services) != 2
        or observed.get("source_sha") != new.source_sha
        or observed.get("attempt_id") != new.installation_run_id
        or services[0].get("container_id") != new.controller_id
        or services[1].get("container_id") != new.worker_id
        or services[0].get("image_ref") != new.controller_image
        or services[1].get("image_ref") != new.worker_image
        or services[0].get("running") is not True
        or services[0].get("health") != "healthy"
        or services[1].get("status") != "created"
        or services[1].get("pid") != 0
    ):
        raise service._refuse()


def park_binding(old: OnDemandInstallation, new_attempt: str, lease: BocaJobLease) -> Path:
    """Stop only Boca's verified listener and atomically park original bytes."""
    _verify_lease(lease, new_attempt)
    home = service._home()
    parked, intent = _name(home, new_attempt)
    if service._present(parked) or service._present(intent):
        raise service._refuse()
    if service._verified_installation(home) != old:
        raise service._refuse()
    root = service._owned(home, old.installation_run_id)
    units = _historic(root, home, old)
    directory = service._unit_dir(home)
    if service._inspect(home, root, units) != (True, True):
        raise service._refuse()

    # Durable intent before interrupting a listener or unlinking one old inode.
    service._new(intent, _proof(home, old, new_attempt))
    service._sync(home)
    service._systemctl(home, "stop", service._SOCKET)
    if service._inspect(home, root, units, cleanup_only=True)[0]:
        raise service._refuse()
    link = directory / "default.target.wants" / service._SOCKET
    if not service._enabled(directory, True):
        raise service._refuse()
    link.unlink()
    service._sync(link.parent)
    for name in units:
        if not service._matches(root / name, directory / name):
            raise service._refuse()
        (directory / name).unlink()
    service._sync(directory)
    service._systemctl(home, "daemon-reload")
    for name in units:
        if service._known(home, directory, name, False)["LoadState"] != "not-found":
            raise service._refuse()
    _historic(root, home, old)
    root.rename(parked)
    service._sync(home)
    _historic(parked, home, old)
    return parked


def restore_binding(old: OnDemandInstallation, new_attempt: str, lease: BocaJobLease) -> None:
    """Restore the original *only precommit* after candidate IDs are removed.

    Does not delete a foreign binding. If a partial new install cannot be
    positively compensated by the existing guarded `remove_control`, it
    refuses recovery so the caller records INDETERMINATE, never false GREEN.
    """
    _verify_lease(lease, new_attempt)
    home = service._home()
    parked, marker = _intended(home, old, new_attempt)
    _old_pair_only(old)
    root = home / service._ROOT
    if service._present(parked):
        _historic(parked, home, old)
        if service._present(root):
            service._owned(home, new_attempt)
            service.remove_control(new_attempt, lease)
        if service._present(root):
            raise service._refuse()
        parked.rename(root)
        service._sync(home)
    elif not service._present(root):
        raise service._refuse()

    # park_binding may have failed halfway through unlink/reload/rename.
    units = _historic(root, home, old)
    directory = service._unit_dir(home)
    for name, content in units.items():
        target = directory / name
        if not service._present(target):
            os.link(root / name, target, follow_symlinks=False)
        elif not service._matches(root / name, target):
            raise service._refuse()
        if service._read(root / name, len(content), links=(2,)) != content:
            raise service._refuse()
    service._sync(directory)
    link = directory / "default.target.wants" / service._SOCKET
    if not service._enabled(directory, True):
        os.symlink("../" + service._SOCKET, link)
        service._sync(link.parent)
    service._systemctl(home, "daemon-reload")
    active, ready = service._inspect(home, root, units, cleanup_only=True)
    if not ready:
        raise service._refuse()
    if not active:
        service._systemctl(home, "start", service._SOCKET)
    if service._verified_installation(home) != old:
        raise service._refuse()
    marker.unlink()
    service._sync(home)


def commit_binding(
    old: OnDemandInstallation,
    new: OnDemandInstallation,
    new_attempt: str,
    lease: BocaJobLease,
) -> None:
    """After BOTH old CIDs are durably retired, discard parked Boca-only bytes."""
    _verify_lease(lease, new_attempt)
    home = service._home()
    parked, marker = _intended(home, old, new_attempt)
    if not service._present(parked):
        raise service._refuse()
    units = _historic(parked, home, old)
    service._owned(home, new_attempt)
    if new.installation_run_id != new_attempt or service._verified_installation(home) != new:
        raise service._refuse()
    _new_pair_only(new)
    if service._present(parked / "socket" / service._SOCKET_NAME):
        raise service._refuse()
    for name in (*units, service._ARCHIVE, service._BINDING, service._MARKER):
        (parked / name).unlink()
    (parked / "socket").rmdir()
    parked.rmdir()
    service._sync(home)
    # Do not remove until the parked root is completely retired.
    marker.unlink()
    service._sync(home)
