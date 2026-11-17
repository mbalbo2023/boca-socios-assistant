"""Private fixed-operation adapter over the existing Boca maintenance container."""

from __future__ import annotations

import json
import os
import re
import secrets
import selectors
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

# Host-supplied literal: R already provides _read and _receipt. Never import
# a new image module, open token/chat/markers, or export a directory entry name.
RECIPIENT_OBSERVE_PROGRAM = r"""
import errno, hashlib, json, os, stat, sys

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

def witness(meta):
    return (meta.st_dev, meta.st_ino, meta.st_mode, meta.st_uid, meta.st_gid,
            meta.st_nlink, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)

def empty(state, entries="NOT_READ"):
    return {"state": state, "entries": entries, "fingerprint": None, "witness": None}

def snapshot():
    result = empty("NOT_READ")
    descriptors = []
    before = None
    leaf = None
    try:
        if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10001,) * 4:
            return result
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root = os.open("/", flags)
        descriptors.append(root)
        run = os.open("run", flags, dir_fd=root)
        descriptors.append(run)
        parent = os.open("telegram", flags, dir_fd=run)
        descriptors.append(parent)
        metadata = os.fstat(parent)
        before = witness(metadata)
        if (not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700
                or (metadata.st_uid, metadata.st_gid) != (10001, 10001)):
            if (witness(os.fstat(parent)) != before
                    or witness(os.stat("telegram", dir_fd=run, follow_symlinks=False)) != before):
                return empty("CHANGED", "CHANGED")
            return {**empty("INVALID"), "witness": hashlib.sha256(canonical([before, None])).hexdigest()}
        with os.scandir(parent) as scan:
            names = [entry.name for entry in (next(scan, None), next(scan, None)) if entry is not None]
        entries = "EMPTY" if not names else "KEY_ONLY" if names == ["telegram_recipient_x25519.key"] else "EXTRA_ENTRIES_PRESENT"
        result["entries"] = entries
        if entries == "EMPTY":
            # Absence must also be an ENOENT leaf under the same valid parent.
            try:
                os.stat("telegram_recipient_x25519.key", dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                result["state"] = "ABSENT"
            else:
                return empty("CHANGED", entries)
        elif entries == "KEY_ONLY":
            metadata = os.stat("telegram_recipient_x25519.key", dir_fd=parent, follow_symlinks=False)
            leaf = witness(metadata)
            if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o400
                    or (metadata.st_uid, metadata.st_gid) != (10001, 10001)
                    or metadata.st_nlink != 1 or metadata.st_size != 32):
                result["state"] = "INVALID"
            else:
                try:
                    from boca_socios import telegram_bootstrap as bootstrap
                    private = bootstrap._read(parent, bootstrap.PRIVATE_KEY, 10001, maximum=32)
                except Exception:
                    result["state"] = "NOT_READ"
                else:
                    if (witness(os.stat(bootstrap.PRIVATE_KEY, dir_fd=parent, follow_symlinks=False)) != leaf
                            or witness(os.fstat(parent)) != before):
                        return empty("CHANGED", entries)
                    try:
                        derived = bootstrap._receipt(private, "PREPARED")
                    except Exception:
                        result["state"] = "NOT_READ"
                    else:
                        result.update(state="VALID", fingerprint=derived.fingerprint)
        if entries == "KEY_ONLY" and witness(os.stat("telegram_recipient_x25519.key", dir_fd=parent, follow_symlinks=False)) != leaf:
            return empty("CHANGED", entries)
        if (witness(os.fstat(parent)) != before
                or witness(os.stat("telegram", dir_fd=run, follow_symlinks=False)) != before):
            return empty("CHANGED", entries)
        result["witness"] = hashlib.sha256(canonical([before, leaf])).hexdigest()
        return result
    except OSError as error:
        return empty("CHANGED" if error.errno == errno.ENOENT and before is not None
                     else "INVALID" if error.errno in (errno.ELOOP, errno.ENOTDIR)
                     else "NOT_READ", result["entries"])
    except Exception:
        return empty("NOT_READ", result["entries"])
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)

if sys.stdin.buffer.read(3) != b"{}":
    result = {**empty("NOT_READ"), "samples": 0}
else:
    first, second = snapshot(), snapshot()
    stable = first == second and first["state"] != "CHANGED"
    result = {**(first if stable else empty("CHANGED", "CHANGED")), "samples": 2}
sys.stdout.buffer.write(canonical(result))
"""


class MaintenanceError(ValueError):
    """Static reason only; preserve ambiguous objects and durable state."""


class MigrationMaintenanceError(MaintenanceError):
    def __init__(self, primary_error: Exception | None, cleanup_error: Exception | None):
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error
        super().__init__("telegram_schema_migration_failed_state_preserved")


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
    migration = operation == "migrate-schema"
    observe = operation == "recipient-observe"
    profile = (
        (("boca_data", "/data", True),)
        if migration
        else MOUNTS["recipient" if observe else operation]
    )
    command = (
        ["python", "-m", "boca_socios.telegram_storage_gate", "migrate"]
        if migration
        else ["python", "-m", "boca_socios.telegram_maintenance", operation]
    )
    if observe:
        command = ["/app/.venv/bin/python", "-I", "-B", "-c", RECIPIENT_OBSERVE_PROGRAM]
    expected = {(f"boca-socios_{volume}", target, rw) for volume, target, rw in profile}
    if (
        value["Name"] != "/" + name
        or config["Image"] != image
        or config["User"] != ("0:0" if operation == "initialize-volume" else "10001:10001")
        or config["Cmd"] != command
        or config["Labels"].get("com.docker.compose.project") != "boca-socios"
        or host["NetworkMode"] != "none"
        or host["ReadonlyRootfs"] is not True
        or host["Privileged"] is not False
        or host["LogConfig"]["Type"] != "none"
        or host["CapDrop"] != ["ALL"]
        or host.get("CapAdd")
        not in ((["CHOWN"], ["CAP_CHOWN"]) if operation == "initialize-volume" else (None, []))
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


def _diagnostic_pipe(command: tuple[str, ...], payload: bytes = b"") -> bytes:
    """Bound both pipes while reading; terminate only the local Docker client."""
    process = subprocess.Popen(  # noqa: S603 - callers supply fixed exec/start commands
        ("/usr/bin/docker", "--host", cleanup.DOCKER_SOCKET, *command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "DOCKER_HOST": cleanup.DOCKER_SOCKET,
            "XDG_RUNTIME_DIR": "/run/user/10001",
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
        },
    )
    output = bytearray()
    deadline = time.monotonic() + 30
    try:
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(payload)
        process.stdin.close()
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MaintenanceError("telegram_diagnostic_transport_unverified")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 4097 - len(output))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is process.stderr or len(output) + len(chunk) > 4096:
                        raise MaintenanceError("telegram_diagnostic_transport_unverified")
                    else:
                        output.extend(chunk)
        if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0 or not output:
            raise MaintenanceError("telegram_diagnostic_transport_unverified")
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for closing_stream in (process.stdin, process.stdout, process.stderr):
            if closing_stream is not None:
                closing_stream.close()


class InstalledMaintenance:
    def __init__(self, context: InstalledTelegramContext) -> None:
        self.context = context
        self._created_volume = False
        self._created_network: str | None = None
        self.migration_helper_retired = True
        self.direct_writer_retired = True
        self.recipient_observation: dict[str, Any] = {
            "id": None,
            "create_attempted": False,
            "start_attempted": False,
            "stop_attempted": False,
            "remove_attempted": False,
            "retirement": "NOT_ATTEMPTED",
        }

    def call(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        if operation == "migrate-schema":
            if type(request) is not dict or request != {}:
                raise MaintenanceError("telegram_schema_migration_request_unverified")
            return self._migrate_schema()
        from boca_socios.host_first_deploy import _telegram_container, _telegram_volume

        observe = operation == "recipient-observe"
        profile = "recipient" if observe else operation
        effects = self.recipient_observation
        if observe and (type(request) is not dict or request != {} or effects["create_attempted"]):
            raise MaintenanceError("telegram_recipient_observation_request_unverified")
        if operation == "initialize-volume" and not self._created_volume:
            raise MaintenanceError("telegram_existing_volume_initialization_forbidden")
        if profile not in MOUNTS:
            raise MaintenanceError("telegram_maintenance_operation_unverified")
        self.context.check_binding()
        if any(volume == "boca_telegram" for volume, _, _ in MOUNTS[profile]):
            if observe and "boca-socios_boca_telegram" not in dict(self.context.volumes):
                raise MaintenanceError("telegram_recipient_volume_absent")
            _telegram_volume()
        payload = bootstrap._canonical(request)
        if not 0 < len(payload) <= MAX_FRAME:
            raise MaintenanceError("telegram_maintenance_frame_unverified")
        name = "boca-socios-telegram-maint-" + self.context.attempt_id + "-" + secrets.token_hex(8)
        image = self.context.installation.controller_image
        mountpoints = dict(self.context.volumes)
        argv = _telegram_container(
            image, "telegram_maintenance", profile, writable=False, maintenance_name=name
        )
        if observe:
            argv = (
                *argv[:-4],
                "/app/.venv/bin/python",
                "-I",
                "-B",
                "-c",
                RECIPIENT_OBSERVE_PROGRAM,
            )
            effects.update(create_attempted=True, retirement="INDETERMINATE")
        if operation == "install-direct":
            self.direct_writer_retired = False
        ident = cleanup._docker(*argv[1:]).strip()
        if re.fullmatch(r"[a-f0-9]{64}", ident) is None:
            raise MaintenanceError("telegram_maintenance_creation_uncertain")
        if observe:
            effects["id"] = ident
        verified = False
        try:
            before = _attest(ident, name, image, operation, mountpoints)
            if observe and before["State"]["Running"] is not False:
                raise MaintenanceError("telegram_recipient_creation_state_unverified")
            verified = True
            self.context.check_binding()
            env = {
                "DOCKER_HOST": cleanup.DOCKER_SOCKET,
                "XDG_RUNTIME_DIR": "/run/user/10001",
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
            }
            if observe:
                effects["start_attempted"] = True
                observed = _diagnostic_pipe(("start", "--attach", "--interactive", ident), b"{}")
                result = subprocess.CompletedProcess([], 0, observed, b"")
            else:
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
            try:
                after = _attest(ident, name, image, operation, mountpoints)
            except Exception:
                if observe:
                    verified = False
                raise
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
                    if observe:
                        effects["stop_attempted"] = True
                    if cleanup._docker("stop", "-t", "5", ident).strip() != ident:
                        raise MaintenanceError("telegram_maintenance_stop_uncertain")
                    final = _attest(ident, name, image, operation, mountpoints)
                if final["State"]["Running"] is not False:
                    raise MaintenanceError("telegram_maintenance_cleanup_uncertain")
                if observe:
                    effects["remove_attempted"] = True
                if cleanup._docker("rm", ident).strip() != ident:
                    raise MaintenanceError("telegram_maintenance_cleanup_uncertain")
                if ident in {item.ident for item in self.context.reader.inventory().containers}:
                    raise MaintenanceError("telegram_maintenance_cleanup_unverified")
                if observe:
                    effects["retirement"] = "RETIRED"
            self.context.check_binding()
            if operation == "install-direct" and verified:
                self.direct_writer_retired = True

    def _migrate_schema(self) -> dict[str, Any]:
        """Run the installed fixed CLI; restoration requires proven writer retirement."""
        from boca_socios.host_first_deploy import _telegram_container

        self.context.stopped()
        self.context.check_binding()
        image = self.context.installation.controller_image
        name = "boca-socios-telegram-maint-" + self.context.attempt_id + "-" + secrets.token_hex(8)
        base = _telegram_container(image, "telegram_storage_gate", "migrate", writable=True)
        argv = (
            "create",
            "--interactive",
            "--log-driver",
            "none",
            "--name",
            name,
            "--label",
            "com.docker.compose.project=boca-socios",
            *base[3:],
        )
        ident = ""
        verified = False
        primary_error: Exception | None = None
        cleanup_error: Exception | None = None
        # From here even a lost create acknowledgement can leave a SQLite writer.
        self.migration_helper_retired = False
        try:
            ident = cleanup._docker(*argv).strip()
            if re.fullmatch(r"[a-f0-9]{64}", ident) is None:
                raise MaintenanceError("telegram_schema_creation_uncertain")
            before = _attest(ident, name, image, "migrate-schema", dict(self.context.volumes))
            if before["State"]["Running"] is not False:
                raise MaintenanceError("telegram_schema_creation_state_unverified")
            verified = True
            self.context.stopped()
            result = subprocess.run(  # noqa: S603 - fixed installed CLI on exact CID
                [
                    "/usr/bin/docker",
                    "--host",
                    cleanup.DOCKER_SOCKET,
                    "start",
                    "--attach",
                    "--interactive",
                    ident,
                ],
                input=b"{}",
                capture_output=True,
                timeout=30,
                check=False,
                env={
                    "DOCKER_HOST": cleanup.DOCKER_SOCKET,
                    "XDG_RUNTIME_DIR": "/run/user/10001",
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C",
                },
            )
            try:
                after = _attest(ident, name, image, "migrate-schema", dict(self.context.volumes))
            except Exception:
                # A later favorable inspect cannot erase a lost identity witness.
                verified = False
                raise
            if (
                result.returncode != 0
                or result.stderr
                or result.stdout != b"BOCA_TELEGRAM_STORAGE state=MIGRATED schema=0007\n"
                or after["State"]["Running"] is not False
                or after["State"]["ExitCode"] != 0
            ):
                raise MaintenanceError("telegram_schema_result_unverified")
        except Exception as error:
            primary_error = error
        finally:
            try:
                self.context.check_binding()
                if not verified:
                    raise MaintenanceError("telegram_schema_helper_identity_uncertain")
                final = _attest(ident, name, image, "migrate-schema", dict(self.context.volumes))
                if final["State"]["Running"]:
                    if cleanup._docker("stop", "-t", "5", ident).strip() != ident:
                        raise MaintenanceError("telegram_schema_stop_uncertain")
                    final = _attest(
                        ident, name, image, "migrate-schema", dict(self.context.volumes)
                    )
                if final["State"]["Running"] is not False:
                    raise MaintenanceError("telegram_schema_stop_unverified")
                if cleanup._docker("rm", ident).strip() != ident:
                    raise MaintenanceError("telegram_schema_removal_uncertain")
                if ident in {item.ident for item in self.context.reader.inventory().containers}:
                    raise MaintenanceError("telegram_schema_removal_unverified")
                self.migration_helper_retired = True
                self.context.check_binding()
            except Exception as error:
                cleanup_error = error
        if primary_error is not None or cleanup_error is not None:
            raise MigrationMaintenanceError(primary_error, cleanup_error)
        return {"schema": 7}

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
