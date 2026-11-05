"""Dedicated read-only Docker field adapter for Telegram host phases (#315).

The generic cleanup inventory intentionally exposes a much narrower set of
fields than stopped-controller/Telegram observers require. This module makes
that explicit on the isolated Boca rootless socket, without expanding the
global cleanup inspection allowlist or authorizing any Docker mutation.
"""

from __future__ import annotations

import json

from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_lifecycle_rootless_adapter import (
    LifecycleAdapterNoGo,
    ProductionRootlessDockerIO,
)

_CONTAINER_FIELDS = frozenset(
    {
        "Id",
        "Name",
        "Image",
        "Config.Image",
        "Config.User",
        "Config.Cmd",
        "Config.Env",
        "State.Running",
        "State.Restarting",
        "State.Health.Status",
        "RestartCount",
        "HostConfig.RestartPolicy",
        "HostConfig.ReadonlyRootfs",
        "HostConfig.Privileged",
        "HostConfig.Init",
        "HostConfig.PublishAllPorts",
        "HostConfig.NetworkMode",
        "HostConfig.PortBindings",
        "HostConfig.NanoCpus",
        "HostConfig.Memory",
        "HostConfig.PidsLimit",
        "HostConfig.CapDrop",
        "HostConfig.CapAdd",
        "HostConfig.SecurityOpt",
        "HostConfig.IpcMode",
        "HostConfig.CgroupnsMode",
        "Config.Labels",
        "Mounts",
        "NetworkSettings.Networks",
    }
)
_VOLUME_FIELDS = frozenset({"Name", "Labels", "Mountpoint"})


class TelegramProductionDockerIO(ProductionRootlessDockerIO):
    """Read selected Boca-only Docker fields after rootless inventory attestation.

    Inventory first validates that the dedicated daemon has only the Boca
    project. A caller must check the exact IDs against reviewed release pins
    before trusting the returned values. No raw stderr, paths or Env ever go
    into a public receipt.
    """

    def field(self, kind: str, ident: str, field: str) -> object:
        if self.uid != 10001 or self.gid != 10001:
            raise LifecycleAdapterNoGo("telegram_rootless_owner_unverified")
        scope: tuple[str, ...]
        if (
            kind == "container"
            and cleanup.HEX_ID.fullmatch(ident)
            and field in _CONTAINER_FIELDS
        ):
            scope = ("inspect",)
        elif (
            kind == "volume"
            and ident in cleanup.PERSISTENT_VOLUMES
            and field in _VOLUME_FIELDS
        ):
            scope = ("volume", "inspect")
        else:
            raise LifecycleAdapterNoGo("telegram_docker_readout_not_allowlisted")
        try:
            raw = cleanup._docker(
                *scope, "--format", "{{json ." + field + "}}", ident
            )
            if len(raw) > 16_384:
                raise ValueError("bounded")
            return json.loads(raw)
        except (ValueError, TypeError, cleanup.CleanupError):
            raise LifecycleAdapterNoGo("telegram_docker_readout_unavailable") from None
