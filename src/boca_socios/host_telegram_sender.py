"""One exact V2 acceptance, sender, and recoverable installed-binding adoption."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_on_demand_service as service

if TYPE_CHECKING:
    from boca_socios.host_telegram_installed_context import InstalledTelegramContext
    from boca_socios.host_telegram_maintenance import InstalledMaintenance


@dataclass(frozen=True)
class SenderActivationReceipt:
    state: Literal["VERIFIED"]
    source_sha: str
    sender_id: str


@dataclass(frozen=True)
class SenderRecoveryReceipt:
    source_sha: str
    state: str = "RECOVERED"
    restoration: str = "CONTROLLER_HEALTHY_ENGINE_OFF"
    sender_state: str = "VERIFIED"


class SenderActivationError(ValueError):
    """Fixed, redacted category; no container output or provider diagnostics."""


def _identity(attempt: str, source: str, workflow: str, lease: cleanup.BocaJobLease) -> None:
    if (
        not cleanup.ATTEMPT_ID.fullmatch(attempt)
        or not re.fullmatch("[a-f0-9]{40}", source)
        or not re.fullmatch("[a-f0-9]{40}", workflow)
    ):
        raise SenderActivationError("telegram_sender_identity_unverified")
    cleanup.verify_protected_boca_job_lease(lease, attempt)


def _stopped(context: InstalledTelegramContext) -> None:
    cleanup.verify_protected_boca_job_lease(context.lease, context.attempt_id)
    for ident in (context.installation.controller_id, context.installation.worker_id):
        if (
            context.reader.field("container", ident, "State.Running") is not False
            or context.reader.field("container", ident, "State.Restarting") is not False
        ):
            raise SenderActivationError("telegram_sender_pair_not_stopped")


def _cid(value: str) -> str:
    result = value.strip()
    if not re.fullmatch("[a-f0-9]{64}", result):
        raise SenderActivationError("telegram_sender_creation_INDETERMINATE")
    return result


def _accept(context: InstalledTelegramContext, original_attempt: str) -> None:
    from boca_socios import host_first_deploy as deploy

    item, attempt = context.installation, original_attempt
    baseline = {item.controller_id, item.worker_id}
    if {c.ident for c in context.reader.inventory().containers} != baseline:
        raise SenderActivationError("telegram_sender_prior_container_present")
    deploy._telegram_egress(v2=True)
    args = deploy._telegram_test_container(
        item.controller_image, item.source_sha, "", "", v2_attempt=attempt
    )
    ident = _cid(cleanup._docker(*args[1:]))
    verified = False

    def attest(*, running: bool = False, allow_failed: bool = False, created: bool = False) -> None:
        found = deploy._telegram_test_finished(
            item.controller_image,
            item.source_sha,
            "",
            "",
            item.controller_id,
            baseline,
            v2_attempt=attempt,
            created_id=ident if created else "",
            running=running,
            allow_failed=allow_failed,
        )
        if found != ident:
            raise SenderActivationError("telegram_acceptance_identity_changed")

    try:
        attest(created=True)
        verified = True
        context.check_binding()
        _stopped(context)
        # The image atomically fences this attempt's UUID before its sole API call.
        # A lost acknowledgement cannot lead to a retry in this function or recovery.
        result = cleanup._docker("start", "--attach", ident).strip()
        attest()
        if result != (
            f"BOCA_TELEGRAM_TEST state=API_ACCEPTED source_sha={item.source_sha}"
            " synthetic=1 human_receipt=unverified"
        ):
            raise SenderActivationError("telegram_acceptance_INDETERMINATE")
        context.check_binding()
    finally:
        if verified:
            context.check_binding()
            running = context.reader.field("container", ident, "State.Running")
            if type(running) is not bool:
                raise SenderActivationError("telegram_acceptance_cleanup_INDETERMINATE")
            attest(running=running, allow_failed=True)
            if running:
                if cleanup._docker("stop", "--time", "5", ident).strip() != ident:
                    raise SenderActivationError("telegram_acceptance_cleanup_INDETERMINATE")
            attest(allow_failed=True)
            if cleanup._docker("rm", ident).strip() != ident or ident in {
                c.ident for c in context.reader.inventory().containers
            }:
                raise SenderActivationError("telegram_acceptance_cleanup_INDETERMINATE")
        deploy._telegram_egress(v2=True)


def _sender_attest(
    context: InstalledTelegramContext, ident: str, attempt: str, *, running: bool
) -> None:
    from boca_socios import host_first_deploy as deploy

    item = context.installation
    deploy._telegram_worker_inspect(
        ident,
        item.controller_image,
        item.source_sha,
        "",
        "",
        item.installation_run_id,
        running=running,
        runtime_attempt=attempt,
        v2=True,
    )
    if {c.ident for c in context.reader.inventory().containers} != {
        item.controller_id,
        item.worker_id,
        ident,
    }:
        raise SenderActivationError("telegram_sender_inventory_changed")
    deploy._telegram_egress(ident if running else "", v2=True)


@dataclass(frozen=True)
class SenderAcceptanceEvidence:
    source_sha: str
    original_attempt_id: str
    acceptance_state: str


@dataclass(frozen=True)
class SenderCompletionReceipt:
    source_sha: str
    state: str = "READY"
    restoration: str = "CONTROLLER_HEALTHY_ENGINE_OFF"
    sender_state: str = "VERIFIED"


def _sender_evidence(
    context: InstalledTelegramContext, maintenance: InstalledMaintenance
) -> SenderAcceptanceEvidence:
    from boca_socios.host_telegram_owner_stage import _controller_owner_subject
    from boca_socios.telegram_bootstrap import RecipientReceipt

    context.check_binding()
    if context.coordinates is None:
        owner = maintenance.call("owner-identity", {})["owner_digest"]
        recipient = RecipientReceipt(**maintenance.call("recipient", {}))
        context.bind(recipient, owner)
    assert context.coordinates is not None
    value = maintenance.call(
        "sender-evidence",
        {
            "coordinates": asdict(context.coordinates),
            "owner_subject": _controller_owner_subject(
                context.reader, context.installation.controller_id
            ),
            "installation_fingerprint": context.installation.fingerprint(),
        },
    )
    if (
        set(value) != {"source_sha", "original_attempt_id", "acceptance_state"}
        or value["source_sha"] != context.installation.source_sha
        or type(value["original_attempt_id"]) is not str
        or not cleanup.ATTEMPT_ID.fullmatch(value["original_attempt_id"])
        or value["acceptance_state"] not in {"NOT_ATTEMPTED", "API_ACCEPTED", "INDETERMINATE"}
    ):
        raise SenderActivationError("telegram_sender_evidence_unverified")
    context.check_binding()
    return SenderAcceptanceEvidence(**value)


def activate_installed_sender(
    context: InstalledTelegramContext,
    *,
    lease: cleanup.BocaJobLease,
    maintenance: InstalledMaintenance,
    expected_source_sha: str,
    attempt_id: str,
) -> SenderActivationReceipt:
    _identity(attempt_id, expected_source_sha, context.workflow_sha, lease)
    if (
        context.lease is not lease
        or context.attempt_id != attempt_id
        or context.installation.source_sha != expected_source_sha
        or context.installation.pair.sender_id
    ):
        raise SenderActivationError("telegram_sender_binding_unverified")
    evidence = _sender_evidence(context, maintenance)
    if evidence.original_attempt_id != attempt_id:
        raise SenderActivationError("telegram_sender_completion_required")
    return _activate_sender(
        context,
        lease=lease,
        maintenance=maintenance,
        expected_source_sha=expected_source_sha,
        attempt_id=attempt_id,
        evidence=evidence,
    )


def _completion_context(
    lease: cleanup.BocaJobLease, source: str, workflow: str, attempt: str
) -> InstalledTelegramContext:
    from boca_socios.host_telegram_installed_context import (
        InstalledTelegramContext,
        resolve_installed_context,
    )
    from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO

    item = service.read_installed_binding(lease)
    if item.source_sha != source or item.pair.sender_id:
        raise SenderActivationError("telegram_sender_binding_recovery_required")
    reader = TelegramProductionDockerIO()
    if (reader.uid, reader.gid) != (10001, 10001):
        raise SenderActivationError("telegram_sender_rootless_unverified")
    if {c.ident for c in reader.inventory().containers} != {item.controller_id, item.worker_id}:
        # Lost create ACK may leave an unbound object. Preserve it for phase RCA;
        # never infer ownership from its name or start a second sender.
        raise SenderActivationError("telegram_sender_unbound_container_RCA_REQUIRED")
    root = service._home() / service._ROOT
    digest = service._sha(service._read(root / service._BINDING, service._MAX_PLAN))
    context = InstalledTelegramContext(attempt, lease, reader, item, digest, (), workflow)
    running = reader.field("container", item.controller_id, "State.Running")
    if running is True:
        # Reuse the canonical healthy resolver so private maintenance receives
        # freshly verified named-volume sources, not an empty mountpoint map.
        context = resolve_installed_context(
            attempt, lease=lease, reader=reader, expected_source_sha=source, workflow_sha=workflow
        )
    elif running is False:
        _recovery_boundary(context)
    else:
        raise SenderActivationError("telegram_sender_controller_state_unverified")
    return context


def complete_installed_telegram_sender(
    *, lease: cleanup.BocaJobLease, expected_source_sha: str, workflow_sha: str, attempt_id: str
) -> SenderCompletionReceipt:
    """Explicit continuation of committed custody; retain the original send UUID."""
    from boca_socios.host_telegram_maintenance import InstalledMaintenance

    _identity(attempt_id, expected_source_sha, workflow_sha, lease)
    context = _completion_context(lease, expected_source_sha, workflow_sha, attempt_id)
    maintenance = InstalledMaintenance(context)
    restore = (
        context.reader.field("container", context.installation.controller_id, "State.Running")
        is False
    )
    try:
        evidence = _sender_evidence(context, maintenance)
        if evidence.acceptance_state not in {"NOT_ATTEMPTED", "API_ACCEPTED"}:
            raise SenderActivationError("telegram_sender_acceptance_INDETERMINATE")
        if not restore:
            restore = True  # Lost stop ACK still requires exact restoration.
            context.stop()
        context.stopped()
        _recovery_boundary(context)
        if _sender_evidence(context, maintenance) != evidence:
            raise SenderActivationError("telegram_sender_evidence_changed")
        _activate_sender(
            context,
            lease=lease,
            maintenance=maintenance,
            expected_source_sha=expected_source_sha,
            attempt_id=attempt_id,
            evidence=evidence,
        )
    except Exception:
        raise SenderActivationError("telegram_sender_completion_INDETERMINATE") from None
    finally:
        if restore:
            try:
                context.restore()
            except Exception:
                raise SenderActivationError(
                    "telegram_sender_completion_restore_INDETERMINATE"
                ) from None
    from boca_socios.host_telegram_status import publish_installed_status

    try:
        publish_installed_status(context, maintenance)
    except Exception:
        raise SenderActivationError("telegram_sender_completion_publish_INDETERMINATE") from None
    return SenderCompletionReceipt(expected_source_sha)


def _activate_sender(
    context: InstalledTelegramContext,
    *,
    lease: cleanup.BocaJobLease,
    maintenance: InstalledMaintenance,
    expected_source_sha: str,
    attempt_id: str,
    evidence: SenderAcceptanceEvidence,
) -> SenderActivationReceipt:
    from boca_socios import host_first_deploy as deploy

    _identity(attempt_id, expected_source_sha, context.workflow_sha, lease)
    old = context.installation
    if (
        context.lease is not lease
        or context.attempt_id != attempt_id
        or old.source_sha != expected_source_sha
        or old.pair.sender_id
    ):
        raise SenderActivationError("telegram_sender_binding_unverified")
    context.stopped()
    custody = maintenance.verify(Path("/run/telegram"), expected_source_sha=expected_source_sha)
    if custody.source_sha != expected_source_sha or custody.state != "CUSTODY_COMMITTED_NO_SEND":
        raise SenderActivationError("telegram_sender_custody_unverified")
    original_attempt = evidence.original_attempt_id
    if evidence.acceptance_state not in {"NOT_ATTEMPTED", "API_ACCEPTED"}:
        raise SenderActivationError("telegram_sender_acceptance_INDETERMINATE")
    ident = ""
    verified = False
    adopted = False
    try:
        if evidence.acceptance_state == "NOT_ATTEMPTED":
            _accept(context, original_attempt)
        after = _sender_evidence(context, maintenance)
        if after != replace(evidence, acceptance_state="API_ACCEPTED"):
            raise SenderActivationError("telegram_sender_acceptance_INDETERMINATE")
        context.stopped()
        args = deploy._telegram_worker_container(
            old.controller_image,
            expected_source_sha,
            "",
            "",
            old.installation_run_id,
            original_attempt,
            v2=True,
        )
        ident = _cid(cleanup._docker(*args[1:]))
        _sender_attest(context, ident, original_attempt, running=False)
        verified = True
        _stopped(context)
        if cleanup._docker("start", ident).strip() != ident:
            raise SenderActivationError("telegram_sender_start_INDETERMINATE")
        _sender_attest(context, ident, original_attempt, running=True)
        deploy._telegram_worker_ready(ident, expected_source_sha)
        new = replace(
            old,
            pair=replace(
                old.pair,
                sender_id=ident,
                sender_config_hash=deploy._telegram_sender_hash(
                    expected_source_sha, original_attempt
                ),
                sender_attempt_id=original_attempt,
                sender_running=True,
            ),
        )
        digest = service.adopt_sender_binding(
            old,
            new,
            lease,
            stopped=lambda: _stopped(context),
            original_sender_attempt=original_attempt,
        )
        context.installation, context.binding_digest = new, digest
        context.pins = None
        context.coordinates = None
        adopted = True
        context.check_binding()
        _sender_attest(context, ident, original_attempt, running=True)
        return SenderActivationReceipt("VERIFIED", expected_source_sha, ident)
    except Exception:
        # An incomplete publication preserves the sender and journal for explicit
        # recovery. Never delete a sender which might already be canonically bound.
        if verified and not adopted:
            try:
                if service.read_installed_binding(lease) != old:
                    raise SenderActivationError("telegram_sender_binding_changed")
                running = context.reader.field("container", ident, "State.Running")
                if type(running) is not bool:
                    raise SenderActivationError("telegram_sender_state_unknown")
                _sender_attest(context, ident, original_attempt, running=running)
                if running and cleanup._docker("stop", "--time", "5", ident).strip() != ident:
                    raise SenderActivationError("telegram_sender_stop_unknown")
                _sender_attest(context, ident, original_attempt, running=False)
                if cleanup._docker("rm", ident).strip() != ident or ident in {
                    c.ident for c in context.reader.inventory().containers
                }:
                    raise SenderActivationError("telegram_sender_cleanup_unknown")
            except Exception:
                raise SenderActivationError("telegram_sender_INDETERMINATE") from None
        raise SenderActivationError("telegram_sender_INDETERMINATE") from None


def _recovery_boundary(context: InstalledTelegramContext) -> None:
    """Attest the real stopped profiles without requiring a prior pairing receipt."""
    from boca_socios.host_lifecycle_rootless_adapter import RootlessLifecycleProbe
    from boca_socios.host_telegram_postcutover import _service, _stopped_controller_boundary

    item, reader = context.installation, context.reader
    _stopped(context)
    inventory = reader.inventory()
    if not isinstance(inventory, cleanup.Inventory):
        raise SenderActivationError("telegram_recovery_inventory_unverified")
    expected = {item.controller_id, item.worker_id}
    if item.pair.sender_id:
        expected.add(item.pair.sender_id)
    containers = {c.ident: c for c in inventory.containers}
    images = {image.ident: image for image in inventory.images}
    if (
        set(containers) != expected
        or len(inventory.containers) != len(expected)
        or len(images) != len(inventory.images)
    ):
        raise SenderActivationError("telegram_recovery_inventory_unverified")
    for ident, role, image, config in (
        (item.controller_id, "controller", item.controller_image, item.pair.controller_config_hash),
        (item.worker_id, "browser-worker", item.worker_image, item.pair.worker_config_hash),
    ):
        _service(
            containers[ident],
            source_sha=item.source_sha,
            browser_attempt=item.installation_run_id,
            image_ref=image,
            config_hash=config,
            service=role,
            images=images,
        )
    if not _stopped_controller_boundary(reader, item):
        raise SenderActivationError("telegram_recovery_current_profile_required")
    RootlessLifecycleProbe(item.pair, reader, on_demand=True)._service_boundary(
        item.worker_id, "browser-worker", item.worker_image
    )
    base_volumes = {"boca_data", "boca_key", "boca_owner", "boca_browser_ipc", "boca_site_config"}
    volume_names = {v.name for v in inventory.volumes}
    expected_volumes = {"boca-socios_" + name for name in base_volumes}
    telegram = "boca-socios_boca_telegram"
    if (
        len(volume_names) != len(inventory.volumes)
        or volume_names not in (expected_volumes, expected_volumes | {telegram})
        or item.pair.sender_id
        and telegram not in volume_names
    ):
        raise SenderActivationError("telegram_recovery_volumes_unverified")
    volumes = []
    for volume in inventory.volumes:
        labels = dict(volume.labels)
        path = "/home/boca-deploy/.local/share/docker/volumes/" + volume.name + "/_data"
        if (
            len(labels) != len(volume.labels)
            or labels.get("com.docker.compose.project") != "boca-socios"
            or labels.get("com.docker.compose.volume") != volume.name.removeprefix("boca-socios_")
            or reader.field("volume", volume.name, "Mountpoint") != path
        ):
            raise SenderActivationError("telegram_recovery_volumes_unverified")
        volumes.append((volume.name, path))
    if str(item.database_path.parent) != dict(volumes)["boca-socios_boca_data"]:
        raise SenderActivationError("telegram_recovery_database_unverified")
    baseline = {"boca-socios_boca_private", "boca-socios_boca_browser_egress"}
    egress = "boca-socios_boca_telegram_egress"
    networks = {n.name: n for n in inventory.networks}
    if (
        len(networks) != len(inventory.networks)
        or set(networks) not in (baseline, baseline | {egress})
        or item.pair.sender_id
        and egress not in networks
    ):
        raise SenderActivationError("telegram_recovery_networks_unverified")
    for name, network in networks.items():
        labels = dict(network.labels)
        suffix = "telegram_egress" if name == egress else name.removeprefix("boca-socios_")
        peers = (item.pair.sender_id,) if name == egress and item.pair.sender_running else ()
        if (
            len(labels) != len(network.labels)
            or labels.get("com.docker.compose.project") != "boca-socios"
            or labels.get("com.docker.compose.network") != suffix
            or network.attached_ids != peers
        ):
            raise SenderActivationError("telegram_recovery_networks_unverified")
    context.volumes = tuple(volumes)
    _stopped(context)


def recover_installed_sender(
    *, lease: cleanup.BocaJobLease, expected_source_sha: str, workflow_sha: str, attempt_id: str
) -> SenderRecoveryReceipt:
    """Explicit recovery only: attest the journal's sender and finish, never send."""
    from boca_socios import host_first_deploy as deploy
    from boca_socios import host_on_demand_sender_update as update
    from boca_socios.host_telegram_installed_context import (
        InstalledTelegramContext,
        resolve_installed_context,
    )
    from boca_socios.host_telegram_maintenance import InstalledMaintenance
    from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO

    _identity(attempt_id, expected_source_sha, workflow_sha, lease)
    try:
        root = service._home() / service._ROOT
        pending = service._present(root / service._UPDATING)
        if pending:
            old, new, original_attempt = update.pending(lease)
        else:
            # Process loss after the final journal unlink is already committed.
            # This recovery still attests the bound sender and never sends again.
            old = new = service.read_installed_binding(lease)
            original_attempt = new.pair.sender_attempt_id
        if (
            old.source_sha != expected_source_sha
            or new.pair.sender_attempt_id != original_attempt
            or bool(new.pair.sender_id) != new.pair.sender_running
        ):
            raise SenderActivationError("telegram_sender_recovery_source_changed")
        reader = TelegramProductionDockerIO()
        if (reader.uid, reader.gid) != (10001, 10001):
            raise SenderActivationError("telegram_sender_rootless_unverified")
        already_healthy = (
            not pending and reader.field("container", new.controller_id, "State.Running") is True
        )
        if already_healthy:
            context = resolve_installed_context(
                attempt_id,
                lease=lease,
                reader=reader,
                expected_source_sha=expected_source_sha,
                workflow_sha=workflow_sha,
                allow_registered_sender=True,
            )
        else:
            context = InstalledTelegramContext(attempt_id, lease, reader, new, "", (), workflow_sha)
            _recovery_boundary(context)
        if new.pair.sender_id:
            _sender_attest(context, new.pair.sender_id, original_attempt, running=True)
            deploy._telegram_worker_ready(new.pair.sender_id, expected_source_sha)
        context.binding_digest = (
            update.recover(lease, stopped=lambda: _stopped(context), commit=True)
            if pending
            else service._sha(service._read(root / service._BINDING, service._MAX_PLAN))
        )
        if new.pair.sender_id:
            custody = InstalledMaintenance(context).verify(
                Path("/run/telegram"), expected_source_sha=expected_source_sha
            )
            if (
                custody.source_sha != expected_source_sha
                or custody.state != "CUSTODY_COMMITTED_NO_SEND"
            ):
                raise SenderActivationError("telegram_sender_recovery_custody_unverified")
        if already_healthy:
            # A publication-only repair never starts a controller which drifted
            # after the healthy observation. It must remain healthy throughout.
            context.healthy()
        else:
            context.restore()
        from boca_socios.host_telegram_status import publish_installed_status

        publish_installed_status(context, InstalledMaintenance(context))
        return SenderRecoveryReceipt(
            expected_source_sha, sender_state="VERIFIED" if new.pair.sender_id else "OFF"
        )
    except Exception:
        raise SenderActivationError("telegram_sender_recovery_INDETERMINATE") from None
