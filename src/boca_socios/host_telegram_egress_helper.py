"""Boca-only ephemeral Telegram GET transport under an *existing* protected lease.

This is a transport factory, not a host dispatch, CLI, owner GO, release gate,
custody commit, or Telegram sender. The caller of this factory must be the sole
protected Cutover/Telegram transaction and supply genuine owner-stage/host
rechecks to :func:`telegram_host_readonly_session.four_gets_under_existing_lease`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_boca_cleanup import BocaJobLease, verify_protected_boca_job_lease
from boca_socios.host_telegram_postcutover import TelegramHostPins
from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO
from boca_socios.telegram_pairing_cutover import CutoverCoordinates, _coordinates_valid
from boca_socios.telegram_pairing_resolver import TelegramApiFetch

_ID = re.compile(r"[0-9a-f]{64}\Z")
_EGRESS = "boca-socios_boca_telegram_egress"
_IMAGE_SOURCE = "https://github.com/mbalbo2023/boca-socios-assistant"
_LABEL_ATTEMPT = "boca.socios.telegram-helper-attempt"
_LABEL_REVISION = "org.opencontainers.image.revision"
_CMD = ["-m", "boca_socios.telegram_readonly_exec", "idle"]
_MEMORY = 96 * 1024 * 1024
_METHODS = frozenset({"getMe", "getWebhookInfo", "getUpdates", "getChat"})


class TelegramPhysicalNoGo(ValueError):
    """Fixed nonsecret failure; never echo Docker stderr/provider response."""


def _private_exec(container_id: str, payload: bytes) -> bytes:
    """Docker exec STDIN only; credentials never go into argv or environment."""
    if (
        _ID.fullmatch(container_id) is None
        or not isinstance(payload, bytes)
        or not 0 < len(payload) <= 512
        or os.geteuid() != cleanup.EXPECTED_UID
        or os.getegid() != cleanup.EXPECTED_GID
        or os.environ.get("DOCKER_HOST", cleanup.DOCKER_SOCKET) != cleanup.DOCKER_SOCKET
        or any(
            name in os.environ
            for name in (
                "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
                "DOCKER_TLS", "DOCKER_CONFIG",
            )
        )
    ):
        raise TelegramPhysicalNoGo("telegram_private_exec_boundary_unverified")
    env = {
        "DOCKER_HOST": cleanup.DOCKER_SOCKET,
        "XDG_RUNTIME_DIR": f"/run/user/{cleanup.EXPECTED_UID}",
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
    }
    argv = [
        "/usr/bin/docker", "--host", cleanup.DOCKER_SOCKET,
        "exec", "--interactive", "--user", "10001:10001", container_id,
        "python", "-m", "boca_socios.telegram_readonly_exec", "get",
    ]
    try:
        result = subprocess.run(  # noqa: S603 - immutable argv, no shell
            argv, input=payload, capture_output=True, timeout=9, check=False, env=env,
        )
        if result.returncode or not 0 < len(result.stdout) <= 22_000 or result.stderr:
            raise TelegramPhysicalNoGo("telegram_private_exec_no_ack")
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise TelegramPhysicalNoGo("telegram_private_exec_transport_uncertain") from None


def _helper_attested(
    reader: TelegramProductionDockerIO,
    helper_id: str,
    name: str,
    pins: TelegramHostPins,
    coordinates: CutoverCoordinates,
) -> None:
    """Fresh rootless inventory and identity before each private GET."""
    try:
        inventory = reader.inventory()
        matches = [item for item in inventory.containers if item.ident == helper_id]
        images = {image.ident: image for image in inventory.images}
        networks = {network.name: network for network in inventory.networks}
        if len(matches) != 1:
            raise ValueError("helper missing")
        item = matches[0]
        labels = dict(item.labels)
        image = images.get(item.image_id)
        egress = networks[_EGRESS]
        helper_networks = reader.field("container", helper_id, "NetworkSettings.Networks")
        if (
            item.name != "/" + name
            or not item.running
            or item.volumes
            or item.networks != (_EGRESS,)
            or labels.get("com.docker.compose.project") != "boca-socios"
            or labels.get(_LABEL_ATTEMPT) != pins.attempt_id
            or labels.get(_LABEL_REVISION) != pins.source_sha
            or image is None
            or image.source != _IMAGE_SOURCE
            or coordinates.image_digest not in image.references
            or tuple(egress.attached_ids) != (helper_id,)
            or reader.field("container", helper_id, "Config.Image") != coordinates.image_digest
            or reader.field("container", helper_id, "Config.User") != "10001:10001"
            or reader.field("container", helper_id, "Config.Cmd") != _CMD
            or reader.field("container", helper_id, "State.Running") is not True
            or reader.field("container", helper_id, "State.Restarting") is not False
            or reader.field("container", helper_id, "HostConfig.NetworkMode") != _EGRESS
            or reader.field("container", helper_id, "HostConfig.ReadonlyRootfs") is not True
            or reader.field("container", helper_id, "HostConfig.Privileged") is not False
            or reader.field("container", helper_id, "HostConfig.PublishAllPorts") is not False
            or reader.field("container", helper_id, "HostConfig.PortBindings") not in ({}, None)
            or reader.field("container", helper_id, "HostConfig.Memory") != _MEMORY
            or reader.field("container", helper_id, "HostConfig.PidsLimit") != 32
            or reader.field("container", helper_id, "HostConfig.CapDrop") != ["ALL"]
            or reader.field("container", helper_id, "Mounts") != []
            or not isinstance(helper_networks, dict)
            or set(helper_networks) != {_EGRESS}
        ):
            raise ValueError("helper unexpected")
        env = reader.field("container", helper_id, "Config.Env")
        if not isinstance(env, list) or any(type(v) is not str for v in env):
            raise ValueError("environment")
        required = {
            "BOCA_RUNTIME_MODE=simulation",
            "BOCA_ENGINE_MODE=off",
            "BOCA_TELEGRAM_READONLY_MODE=explicit",
        }
        if not required <= set(env) or any(
            "TOKEN" in v or "SECRET" in v or "CHAT_ID" in v for v in env
        ):
            raise ValueError("injected secrets or mode")
    except Exception:
        raise TelegramPhysicalNoGo("telegram_helper_attestation_unverified") from None


def _run_helper(pins: TelegramHostPins, coordinates: CutoverCoordinates) -> str:
    name = "boca-socios-telegram-readonly-" + pins.attempt_id
    args = (
        "run", "--detach", "--pull=never", "--name", name,
        "--label", "com.docker.compose.project=boca-socios",
        "--label", _LABEL_ATTEMPT + "=" + pins.attempt_id,
        "--label", _LABEL_REVISION + "=" + pins.source_sha,
        "--network", _EGRESS, "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=32", "--memory=96m",
        "--cpus=0.5", "--user", "10001:10001", "--restart=no",
        "--env", "BOCA_RUNTIME_MODE=simulation",
        "--env", "BOCA_ENGINE_MODE=off",
        "--env", "BOCA_TELEGRAM_READONLY_MODE=explicit",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--entrypoint", "python", coordinates.image_digest, *_CMD,
    )
    try:
        output = cleanup._docker(*args).strip()
        if _ID.fullmatch(output) is None:
            raise ValueError("uncertain new helper")
        return output
    except Exception:
        # If Docker run created a container but the ACK was lost, never guess
        # its identity or remove an unreviewed resource by name.
        raise TelegramPhysicalNoGo("telegram_helper_creation_uncertain") from None


def _remove_helper(helper_id: str) -> None:
    try:
        if cleanup._docker("rm", "--force", helper_id).strip() not in (helper_id,):
            raise ValueError("unexpected cleanup ACK")
    except Exception:
        raise TelegramPhysicalNoGo("telegram_helper_cleanup_unverified") from None


@contextmanager
def protected_ephemeral_get_session(
    pins: TelegramHostPins,
    coordinates: CutoverCoordinates,
    *,
    lease: BocaJobLease,
    reader: TelegramProductionDockerIO | None = None,
) -> Iterator[TelegramApiFetch]:
    """Yield four-method GET callback under the SAME caller-owned flock.

    No autonomous lease acquisition or host entry point. The caller remains
    responsible for fresh Cutover A physical proofs and phase recheck callback;
    successful egress is still NOT sender, custody or human notification GO.
    """
    try:
        pins.require()
        if (
            not _coordinates_valid(coordinates)
            or pins.attempt_id != coordinates.attempt_id
            or pins.source_sha != coordinates.target_sha
            or pins.controller_id != coordinates.controller_id
            or pins.controller_image != coordinates.image_digest
        ):
            raise ValueError("coordinate mismatch")
        verify_protected_boca_job_lease(lease, pins.attempt_id)
        probe = TelegramProductionDockerIO() if reader is None else reader
        if probe.uid != 10001 or probe.gid != 10001:
            raise ValueError("rootless mismatch")
    except Exception:
        raise TelegramPhysicalNoGo("telegram_helper_preflight_unverified") from None
    helper_id = _run_helper(pins, coordinates)
    name = "boca-socios-telegram-readonly-" + pins.attempt_id
    try:
        _helper_attested(probe, helper_id, name, pins, coordinates)

        def private_get(token: str, method: str, chat_id: int | None) -> bytes:
            if method not in _METHODS or (method == "getChat") != (type(chat_id) is int):
                raise TelegramPhysicalNoGo("telegram_helper_method_unreviewed")
            try:
                verify_protected_boca_job_lease(lease, pins.attempt_id)
                _helper_attested(probe, helper_id, name, pins, coordinates)
                frame = json.dumps(
                    {"version": 1, "method": method, "token": token, "chat_id": chat_id},
                    separators=(",", ":"), sort_keys=True,
                ).encode("ascii")
                raw = _private_exec(helper_id, frame)
                response = json.loads(raw)
                if (
                    type(response) is not dict
                    or set(response) != {"version", "response_base64url"}
                    or response["version"] != 1
                    or type(response["response_base64url"]) is not str
                ):
                    raise ValueError("invalid GET response")
                encoded = cast(str, response["response_base64url"])
                data = base64.b64decode(
                    encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                )
                if not 0 < len(data) <= 16_384:
                    raise ValueError("unbounded GET response")
                return data
            except Exception:
                raise TelegramPhysicalNoGo("telegram_helper_get_unverified") from None

        yield private_get
    finally:
        # Removal is positive-ID-scoped to the helper this context created.
        # Never prune or touch existing Boca/Porota/other Docker objects.
        verify_protected_boca_job_lease(lease, pins.attempt_id)
        _remove_helper(helper_id)
