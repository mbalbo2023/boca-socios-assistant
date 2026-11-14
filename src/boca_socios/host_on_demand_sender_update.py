"""Recoverable sender-only binding publication under the protected host lease.

The fixed journal fences handlers, including after process loss. Each rename is
atomic, the sequence is not. Recovery admits only exact old/new canonical bytes;
foreign files and partial/unrecognized state are preserved as INDETERMINATE.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from boca_socios import host_on_demand_service as s
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation


def _compatible(old: OnDemandInstallation, new: OnDemandInstallation) -> None:
    if (
        old.pair.sender_id
        or not new.pair.sender_running
        or not new.pair.sender_id
        or replace(
            new,
            pair=replace(
                new.pair,
                sender_id="",
                sender_config_hash="",
                sender_attempt_id="",
                sender_running=False,
            ),
        )
        != old
    ):
        raise s._refuse()
    new.coordinates("00000000-0000-4000-8000-000000000001")


def _journal(old: bytes, new: bytes, attempt: str) -> bytes:
    return json.dumps(
        {"version": 1, "attempt": attempt, "old": old.decode("ascii"), "new": new.decode("ascii")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def pending(lease: BocaJobLease) -> tuple[OnDemandInstallation, OnDemandInstallation, str]:
    """Read a strict recovery fence without admitting the normal installed handler."""
    s._verify_lease(lease, lease.attempt_id)
    home = s._home()
    root = home / s._ROOT
    s._directory(root, mode=0o700)
    raw = s._read(root / s._UPDATING, 2 * s._MAX_PLAN + 1024)
    try:
        obj = json.loads(raw)
        old_raw, new_raw, attempt = (
            obj["old"].encode("ascii"),
            obj["new"].encode("ascii"),
            obj["attempt"],
        )
        s._check_attempt(attempt)
        if raw != _journal(old_raw, new_raw, attempt):
            raise s._refuse()
        old, archive = s._decode(home, old_raw)
        new, new_archive = s._decode(home, new_raw)
        _compatible(old, new)
        if new.pair.sender_attempt_id != attempt:
            raise s._refuse()
        if new_archive != archive or s._sha(s._read(root / s._ARCHIVE, s._MAX_ZIP)) != archive:
            raise s._refuse()
        s._owned(home, old.installation_run_id)
        if s._present(root / s._REMOVING):
            raise s._refuse()
    except (KeyError, TypeError, AttributeError, UnicodeError, ValueError):
        raise s._refuse() from None
    return old, new, attempt


def _contents(home: Path, item: OnDemandInstallation, archive: str) -> dict[str, bytes]:
    plan = s._plan(home, item, archive)
    return {s._BINDING: plan, **s._units(archive, s._sha(plan))}


def _idle(home: Path) -> None:
    if s._systemctl(
        home,
        "list-units",
        "--no-legend",
        "--plain",
        "--all",
        "--state=active,activating,deactivating",
        "boca-bot-control@*.service",
    ).strip():
        raise s._refuse()


def _transition(
    old: OnDemandInstallation,
    new: OnDemandInstallation,
    target: OnDemandInstallation,
    lease: BocaJobLease,
    stopped: Callable[[], None],
) -> str:
    home = s._home()
    root, directory = home / s._ROOT, s._unit_dir(home)
    archive = s._sha(s._read(root / s._ARCHIVE, s._MAX_ZIP))
    prior, following, wanted = (_contents(home, item, archive) for item in (old, new, target))
    # Inspect the complete recoverable namespace before any mutation. Every linked
    # unit is one of the journal's two exact byte strings; extra links fail closed.
    stage = root / s._NEXT
    allowed = set(prior.values()) | set(following.values())
    if s._present(stage) and s._read(stage, s._MAX_PLAN, links=(1, 2)) not in allowed:
        raise s._refuse()
    all_paths = [root / name for name in prior] + [
        directory / name for name in prior if name != s._BINDING
    ]
    if s._present(stage):
        all_paths.append(stage)
    identities = [path.lstat() for path in all_paths]
    if any(
        node.st_nlink != sum(os.path.samestat(node, peer) for peer in identities)
        for node in identities
    ):
        raise s._refuse()
    for name in prior:
        paths = (root / name,) if name == s._BINDING else (root / name, directory / name)
        for path in paths:
            if s._read(path, s._MAX_PLAN, links=(1, 2)) not in (prior[name], following[name]):
                raise s._refuse()
        if name != s._BINDING:
            s._known(home, directory, name, True)
    if not s._enabled(directory, True):
        raise s._refuse()
    s._verify_lease(lease, lease.attempt_id)
    stopped()
    state = s._state(home, s._SOCKET)
    if state["ActiveState"] == "active" and state["SubState"] == "listening":
        s._systemctl(home, "stop", s._SOCKET)
    state = s._state(home, s._SOCKET)
    if state["ActiveState"] != "inactive" or s._present(root / "socket" / s._SOCKET_NAME):
        raise s._refuse()
    _idle(home)
    for name, data in wanted.items():
        s._verify_lease(lease, lease.attempt_id)
        stopped()
        if s._present(stage):
            stage.unlink()
            s._sync(root)
        s._new(stage, data)
        os.replace(stage, root / name)
        s._sync(root)
        if name != s._BINDING:
            os.link(root / name, stage, follow_symlinks=False)
            os.replace(stage, directory / name)
            s._sync(directory)
            s._sync(root)
    s._systemctl(home, "daemon-reload")
    if s._inspect(home, root, {k: v for k, v in wanted.items() if k != s._BINDING}) != (
        False,
        True,
    ):
        raise s._refuse()
    stopped()
    s._verify_lease(lease, lease.attempt_id)
    # Socket normalization admits only its pinned bytes while the journal still
    # fences actual requests. Retain recovery evidence until live verification.
    s._systemctl(home, "start", s._SOCKET)
    if s._verified_installation(home, sender_update=True) != target:
        raise s._refuse()
    (root / s._UPDATING).unlink()
    s._sync(root)
    if s._verified_installation(home) != target:
        raise s._refuse()
    return s._sha(wanted[s._BINDING])


def recover(lease: BocaJobLease, *, stopped: Callable[[], None], commit: bool) -> str:
    """Recovery-only; caller must freshly attest the sender before committing."""
    old, new, _ = pending(lease)
    return _transition(old, new, new if commit else old, lease, stopped)


def adopt(
    old: OnDemandInstallation,
    new: OnDemandInstallation,
    lease: BocaJobLease,
    *,
    stopped: Callable[[], None],
    original_sender_attempt: str | None = None,
) -> str:
    s._verify_lease(lease, lease.attempt_id)
    sender_attempt = (
        lease.attempt_id if original_sender_attempt is None else original_sender_attempt
    )
    s._check_attempt(sender_attempt)
    if new.pair.sender_attempt_id != sender_attempt:
        raise s._refuse()
    _compatible(old, new)
    home = s._home()
    if s._verified_installation(home) != old:
        raise s._refuse()
    root = home / s._ROOT
    stopped()
    _idle(home)
    archive = s._sha(s._read(root / s._ARCHIVE, s._MAX_ZIP))
    s._new(
        root / s._UPDATING,
        _journal(s._plan(home, old, archive), s._plan(home, new, archive), sender_attempt),
    )
    try:
        return _transition(old, new, new, lease, stopped)
    except Exception:
        try:
            recover(lease, stopped=stopped, commit=False)
        except Exception:
            raise s.ControlRefused("telegram_sender_binding_INDETERMINATE") from None
        raise s.ControlRefused("telegram_sender_binding_NO_GO") from None
