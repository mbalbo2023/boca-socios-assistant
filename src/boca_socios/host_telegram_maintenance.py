"""Private fixed-operation adapter over the existing Boca maintenance container."""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.host_telegram_installed_context import InstalledTelegramContext
from boca_socios.telegram_maintenance_contract import MAX_FRAME, MOUNTS
from boca_socios.telegram_owner_webauthn import parse_witness_document
from boca_socios.telegram_pairing_cutover import CutoverCoordinates
from boca_socios.telegram_pairing_install import PairingCustodyReceipt
from boca_socios.telegram_pairing_resolver import PairingInstallPlan
from boca_socios.telegram_same_lease_stage import EncryptedPairingStage


class MaintenanceError(ValueError):
    """Static reason only; preserve ambiguous objects and durable state."""


def _inspect(ident: str) -> dict[str, Any]:
    raw = cleanup._docker("inspect", "--format", "{{json .}}", ident)
    value = json.loads(raw)
    if type(value) is not dict or value.get("Id") != ident:
        raise MaintenanceError("telegram_maintenance_identity_unverified")
    return value


def _attest(
    ident: str, name: str, image: str, operation: str, mountpoints: dict[str, str]
) -> dict[str, Any]:
    value = _inspect(ident)
    config, host = value["Config"], value["HostConfig"]
    mounts = value["Mounts"]
    expected = {(f"boca-socios_{volume}", target, rw) for volume, target, rw in MOUNTS[operation]}
    if (
        value["Name"] != "/" + name
        or config["Image"] != image
        or config["User"] != ("0:0" if operation == "initialize-volume" else "10001:10001")
        or config["Cmd"] != ["python", "-m", "boca_socios.telegram_maintenance", operation]
        or config["Labels"].get("com.docker.compose.project") != "boca-socios"
        or host["NetworkMode"] != "none"
        or host["ReadonlyRootfs"] is not True
        or host["Privileged"] is not False
        or host["LogConfig"]["Type"] != "none"
        or host["CapDrop"] != ["ALL"]
        or host.get("CapAdd")
        not in ((["CHOWN"],) if operation == "initialize-volume" else (None, []))
        or host["PidsLimit"] != 16
        or host["Memory"] != 67108864
        or host["NanoCpus"] != 250000000
        or host["PublishAllPorts"] is not False
        or host.get("PortBindings") not in (None, {})
        or host["RestartPolicy"]["Name"] != "no"
        or host["SecurityOpt"] not in (["no-new-privileges"], ["no-new-privileges:true"])
        or len(mounts) != len(expected)
        or {
            (m["Name"], m["Destination"], m["RW"])
            for m in mounts
            if m["Type"] == "volume" and m["Driver"] == "local"
        }
        != expected
        or any(m.get("Source") != mountpoints.get(m.get("Name")) for m in mounts)
        or set(value["NetworkSettings"]["Networks"]) - {"none"}
        or value["State"]["Restarting"] is not False
    ):
        raise MaintenanceError("telegram_maintenance_boundary_unverified")
    return value


class InstalledMaintenance:
    def __init__(self, context: InstalledTelegramContext) -> None:
        self.context = context
        self._created_volume = False
        self._created_network: str | None = None

    def call(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        from boca_socios.host_first_deploy import _telegram_container, _telegram_volume

        if operation == "initialize-volume" and not self._created_volume:
            raise MaintenanceError("telegram_existing_volume_initialization_forbidden")
        if operation not in MOUNTS:
            raise MaintenanceError("telegram_maintenance_operation_unverified")
        self.context.check_binding()
        if any(volume == "boca_telegram" for volume, _, _ in MOUNTS[operation]):
            _telegram_volume()
        payload = bootstrap._canonical(request)
        if not 0 < len(payload) <= MAX_FRAME:
            raise MaintenanceError("telegram_maintenance_frame_unverified")
        name = "boca-socios-telegram-maint-" + self.context.attempt_id + "-" + secrets.token_hex(8)
        image = self.context.installation.controller_image
        mountpoints = dict(self.context.volumes)
        argv = _telegram_container(
            image, "telegram_maintenance", operation, writable=False, maintenance_name=name
        )
        ident = cleanup._docker(*argv[1:]).strip()
        if re.fullmatch(r"[a-f0-9]{64}", ident) is None:
            raise MaintenanceError("telegram_maintenance_creation_uncertain")
        verified = False
        try:
            _attest(ident, name, image, operation, mountpoints)
            verified = True
            self.context.check_binding()
            env = {
                "DOCKER_HOST": cleanup.DOCKER_SOCKET,
                "XDG_RUNTIME_DIR": "/run/user/10001",
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
            }
            result = subprocess.run(  # noqa: S603 - fixed exact-ID private pipe
                [
                    "/usr/bin/docker",
                    "--host",
                    cleanup.DOCKER_SOCKET,
                    "start",
                    "--attach",
                    "--interactive",
                    ident,
                ],
                input=payload,
                capture_output=True,
                timeout=30,
                check=False,
                env=env,
            )
            after = _attest(ident, name, image, operation, mountpoints)
            if (
                result.returncode
                or result.stderr
                or after["State"]["Running"] is not False
                or after["State"]["ExitCode"] != 0
                or not 0 < len(result.stdout) <= MAX_FRAME
            ):
                raise MaintenanceError("telegram_maintenance_operation_failed")
            value = json.loads(result.stdout, object_pairs_hook=bootstrap._unique)
            if type(value) is not dict or bootstrap._canonical(value) != result.stdout:
                raise MaintenanceError("telegram_maintenance_response_unverified")
            return value
        except Exception:
            raise MaintenanceError("telegram_maintenance_failed_state_preserved") from None
        finally:
            # A changed identity is preserved rather than removed by name.
            self.context.check_binding()
            if verified:
                final = _attest(ident, name, image, operation, mountpoints)
                if final["State"]["Running"]:
                    if cleanup._docker("stop", "--time", "5", ident).strip() != ident:
                        raise MaintenanceError("telegram_maintenance_stop_uncertain")
                    final = _attest(ident, name, image, operation, mountpoints)
                if (
                    final["State"]["Running"] is not False
                    or cleanup._docker("rm", ident).strip() != ident
                ):
                    raise MaintenanceError("telegram_maintenance_cleanup_uncertain")
                if ident in {item.ident for item in self.context.reader.inventory().containers}:
                    raise MaintenanceError("telegram_maintenance_cleanup_unverified")
            self.context.check_binding()

    def provision(self) -> None:
        """Explicit prepare creates only missing Boca Telegram resources."""
        from boca_socios.host_first_deploy import _telegram_egress, _telegram_volume

        self.context.stopped()
        name = "boca-socios_boca_telegram"
        inventory = self.context.reader.inventory()
        existing = [volume for volume in inventory.volumes if volume.name == name]
        if not existing:
            if (
                cleanup._docker(
                    "volume",
                    "create",
                    "--driver",
                    "local",
                    "--label",
                    "com.docker.compose.project=boca-socios",
                    "--label",
                    "com.docker.compose.volume=boca_telegram",
                    name,
                ).strip()
                != name
            ):
                raise MaintenanceError("telegram_volume_creation_uncertain")
            self._created_volume = True
        _telegram_volume()
        labels = self.context.reader.field("volume", name, "Labels")
        path = self.context.reader.field("volume", name, "Mountpoint")
        expected_path = "/home/boca-deploy/.local/share/docker/volumes/" + name + "/_data"
        if (
            self.context.reader.field("volume", name, "Name") != name
            or path != expected_path
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != "boca-socios"
            or labels.get("com.docker.compose.volume") != "boca_telegram"
        ):
            raise MaintenanceError("telegram_volume_identity_unverified")
        if (name, expected_path) not in self.context.volumes:
            self.context.volumes += ((name, expected_path),)
        if self._created_volume:
            if self.call("initialize-volume", {"new_empty_volume": name}) != {"initialized": True}:
                raise MaintenanceError("telegram_volume_initialization_unverified")
        network = "boca-socios_boca_telegram_egress"
        existing_networks = [
            item for item in self.context.reader.inventory().networks if item.name == network
        ]
        if not existing_networks:
            ident = cleanup._docker(
                "network",
                "create",
                "--driver",
                "bridge",
                "--label",
                "com.docker.compose.project=boca-socios",
                "--label",
                "com.docker.compose.network=telegram_egress",
                network,
            ).strip()
            if re.fullmatch(r"[a-f0-9]{64}", ident) is None:
                raise MaintenanceError("telegram_network_creation_uncertain")
            self._created_network = ident
        _telegram_egress(v2=True)
        self.context.check_binding()

    def cleanup_failed_provision(self) -> None:
        """Retain persistent volume; delete only this attempt's empty bridge."""
        if self._created_network is None:
            return
        self.context.check_binding()
        items = [
            n for n in self.context.reader.inventory().networks if n.ident == self._created_network
        ]
        if (
            len(items) != 1
            or items[0].name != "boca-socios_boca_telegram_egress"
            or items[0].attached_ids
        ):
            raise MaintenanceError("telegram_network_cleanup_identity_unverified")
        if cleanup._docker("network", "rm", self._created_network).strip() != self._created_network:
            raise MaintenanceError("telegram_network_cleanup_uncertain")
        if any(n.ident == self._created_network for n in self.context.reader.inventory().networks):
            raise MaintenanceError("telegram_network_cleanup_unverified")

    def _coordinates(self) -> CutoverCoordinates:
        if self.context.coordinates is None:
            raise MaintenanceError("telegram_coordinates_required")
        return self.context.coordinates

    def read_stage(
        self,
        directory: Path,
        *,
        coordinates: CutoverCoordinates,
        lease: cleanup.BocaJobLease,
        trusted_now: int | None = None,
    ) -> EncryptedPairingStage:
        self.context.check_binding()
        if coordinates != self._coordinates() or lease is not self.context.lease:
            raise MaintenanceError("telegram_stage_binding_changed")
        value = self.call(
            "read-stage",
            {
                "coordinates": asdict(coordinates),
                "now": int(time.time()) if trusted_now is None else trusted_now,
            },
        )
        envelope = bootstrap._unb64(value.pop("envelope"), maximum=4096)
        witness = value.pop("owner_witness")
        value["file_identity"] = tuple(value["file_identity"])
        return EncryptedPairingStage(
            **value,
            envelope=envelope,
            owner_witness=None if witness is None else parse_witness_document(witness),
        )

    def consume_nonce(
        self,
        directory: Path,
        nonce: str,
        coordinates: CutoverCoordinates,
        *,
        lease: cleanup.BocaJobLease,
    ) -> bool:
        if coordinates != self._coordinates() or lease is not self.context.lease:
            raise MaintenanceError("telegram_nonce_binding_changed")
        value = self.call("consume-nonce", {"coordinates": asdict(coordinates), "nonce": nonce})
        return value == {"consumed": True}

    def unseal(
        self, envelope: bytes, private: bytes | None, recipient: bootstrap.RecipientReceipt
    ) -> tuple[bytes, str]:
        if private is not None:
            raise MaintenanceError("telegram_private_key_export_forbidden")
        value = self.call(
            "unseal", {"envelope": bootstrap._b64(envelope), "recipient": asdict(recipient)}
        )
        return value["token"].encode("ascii"), value["code"]

    def seal(self, recipient: bootstrap.RecipientReceipt, token: str, chat: str) -> bytes:
        value = self.call("seal", {"recipient": asdict(recipient), "token": token, "chat": chat})
        return bootstrap._unb64(value["envelope"], maximum=4096)

    def install(
        self, directory: Path, plan: PairingInstallPlan, *, expected_source_sha: str, now: int
    ) -> PairingCustodyReceipt:
        value = self.call(
            "install-v2",
            {
                "receipt": asdict(plan.receipt),
                "envelope": bootstrap._b64(plan.sealed_v1_envelope),
                "source_sha": expected_source_sha,
                "now": now,
            },
        )
        return PairingCustodyReceipt(**value)

    def verify(self, directory: Path, *, expected_source_sha: str) -> PairingCustodyReceipt:
        return PairingCustodyReceipt(**self.call("verify-v2", {"source_sha": expected_source_sha}))
