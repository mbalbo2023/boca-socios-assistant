"""Disposable hosted-runner evidence for #250/#251, never a host installer.

The real Docker records, kernel limits and IPC are tested unchanged. Images
are local builds: only the absent registry RepoDigests/config reference is
adapted in memory for the production identity predicates. This is explicitly
not publication, rootless-host, owner-enrollment or Telegram API evidence.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOKEN = "12345:synthetic-bot-token-for-tests"  # noqa: S105 - invented offline fixture
CHAT = "123456789"
BOT = "12345"
CHAT_HMAC = hmac.new(TOKEN.encode(), CHAT.encode(), hashlib.sha256).hexdigest()


def seed_sender(source: str) -> None:
    """Only inside the disposable network-none UID10001 bootstrap container."""
    from boca_socios import telegram_bootstrap, telegram_one_shot, telegram_storage_gate
    from boca_socios.notify.telegram_transport import TelegramAck, TelegramTransport

    assert os.geteuid() == os.getegid() == 10001
    assert os.listdir("/sys/class/net") == ["lo"]
    directory = Path("/run/telegram")
    recipient = telegram_bootstrap.prepare(directory)
    telegram_bootstrap.install(
        directory, telegram_bootstrap.seal_for_recipient(recipient, TOKEN, CHAT)
    )
    telegram_storage_gate.migrate()
    transport = TelegramTransport(directory / "bot_token", directory / "chat_id")
    notice = telegram_one_shot.acceptance_notice_id(transport, source, int(BOT), CHAT_HMAC)

    class OfflineSender:
        def preflight(self) -> None:
            pass

        async def send(self, _notice):
            return TelegramAck(42)

    asyncio.run(
        telegram_one_shot.deliver_once(
            Path("/data/boca.sqlite3"), OfflineSender(), source, notice_id=notice
        )
    )
    print("BOCA_CI_TELEGRAM_SEED state=PASS ledger=synthetic provider=not_contacted")


def docker(*args: str, timeout: int = 30) -> str:
    result = subprocess.run(  # noqa: S603 - fixed Docker CLI on guarded disposable CI only
        ["docker", *args],  # noqa: S607 - hosted runner configured CLI
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("disposable Docker operation failed; output withheld")
    return result.stdout.strip()


def inspection_summary(record: dict, *, service: str) -> dict:
    """Only fixed, nonsecret Docker boundary fields from a synthetic CI object."""
    config, host = record["Config"], record["HostConfig"]
    network = record.get("NetworkSettings", {})
    environment = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
    return {
        "service": service,
        "running": record["State"]["Running"],
        "state_status": record["State"].get("Status"),
        "network_ports": network.get("Ports"),
        "network_names": sorted(network.get("Networks", {})),
        "entrypoint_absent": config.get("Entrypoint") in (None, []),
        "worker_command_matches": config.get("Cmd")
        == ["python", "-m", "boca_socios.browser.ipc_worker"],
        "boca_environment_keys": sorted(key for key in environment if key.startswith("BOCA_")),
        "required_environment_matches": all(
            environment.get(key) == value
            for key, value in {
                "BOCA_ENVIRONMENT": "staging",
                "BOCA_RUNTIME_MODE": "simulation",
                "BOCA_ENGINE_MODE": "off",
                **({"BOCA_OBSERVER_STOP": "1"} if service == "browser-worker" else {}),
            }.items()
        ),
        "exposed_ports": config.get("ExposedPorts"),
        "isolation": {
            name: host.get(name)
            for name in (
                "NetworkMode",
                "IpcMode",
                "CgroupnsMode",
                "NanoCpus",
                "Memory",
                "PidsLimit",
                "ShmSize",
                "CapDrop",
                "CapAdd",
                "PortBindings",
                "Tmpfs",
            )
        },
    }


def peer_receipt(raw: str) -> dict:
    """Validate diagnostic shape only; the production guard still authorizes."""
    if len(raw) > 160:
        raise ValueError("IPC peer diagnostic is unbounded")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"pid", "uid", "gid"}
        or any(type(item) is not int or not -(2**31) <= item < 2**31 for item in value.values())
    ):
        raise ValueError("IPC peer diagnostic shape is invalid")
    return value


PEER_DIAGNOSTIC = """
import json, socket, struct, time
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
    deadline = time.monotonic() + 3
    endpoint.settimeout(3)
    endpoint.connect('/run/boca-browser-ipc/synthetic.sock')
    pid, uid, gid = struct.unpack('3i', endpoint.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    # Send no frame. EOF makes the worker reject the incomplete request, and
    # draining its bounded reply avoids leaving an active handler behind.
    endpoint.shutdown(socket.SHUT_WR)
    received = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('diagnostic reply deadline')
            endpoint.settimeout(remaining)
            chunk = endpoint.recv(67 - received)
            if not chunk:
                break
            received += len(chunk)
            if received > 66:
                raise RuntimeError('unbounded diagnostic reply')
    except ConnectionResetError:
        pass
print(json.dumps({'pid':pid,'uid':uid,'gid':gid}, sort_keys=True))
"""


FOREIGN_UID_RECEIPT = "BOCA_CI_IPC_FOREIGN_UID state=REJECTED uid=10003 sent_bytes=0"
FOREIGN_UID_PROBE = """
import os, socket, time
assert os.geteuid() == os.getegid() == 10003
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
    deadline = time.monotonic() + 3
    endpoint.settimeout(3)
    endpoint.connect('/run/boca-browser-ipc/synthetic.sock')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('foreign peer deadline')
    endpoint.settimeout(remaining)
    # No frame and no write-half close: only the worker can close this peer.
    try:
        if endpoint.recv(1) != b'':
            raise RuntimeError('foreign peer received a protocol response')
    except ConnectionResetError:
        pass
print('BOCA_CI_IPC_FOREIGN_UID state=REJECTED uid=10003 sent_bytes=0')
"""


def runtime_identity(record: dict) -> tuple:
    state = record["State"]
    return (
        record["Id"],
        record["Image"],
        record["RestartCount"],
        state["StartedAt"],
        state["Running"],
        state.get("Health", {}).get("Status"),
    )


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "seed-sender":
        assert re.fullmatch(r"[0-9a-f]{40}", sys.argv[2])
        seed_sender(sys.argv[2])
        return
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    assert os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
    source, attempt = os.environ["GITHUB_SHA"], os.environ["GITHUB_RUN_ID"]
    assert re.fullmatch(r"[0-9a-f]{40}", source)
    assert re.fullmatch(r"[1-9][0-9]{0,19}", attempt)
    controller_image = os.environ["BOCA_IMAGE"]
    browser_image = os.environ["BOCA_BROWSER_IMAGE"]
    assert controller_image == f"boca-first-install-smoke:{source}"
    assert browser_image == f"boca-browser-lifecycle-smoke:{source}"

    from boca_socios import host_first_deploy as deploy
    from boca_socios import host_rootless_setup as rootless

    images = {}
    for image in (controller_image, browser_image):
        record = json.loads(docker("image", "inspect", "--format", "{{json .}}", image))
        assert record["Config"]["Labels"]["org.opencontainers.image.revision"] == source
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", record["Id"])
        images[image] = record
    virtual = {
        image: "ghcr.io/mbalbo2023/boca-socios-assistant"
        + ("-browser" if image == browser_image else "")
        + "@"
        + record["Id"]
        for image, record in images.items()
    }
    seccomp = Path("docker/seccomp_profile.json").read_bytes()

    def production_run(*args: str, timeout: int = 60) -> str:
        assert args[0] == "docker"
        if args[1:3] == ("image", "inspect"):
            assert args[-1] in images
            record = copy.deepcopy(images[args[-1]])
            record["RepoDigests"] = [args[-1]]  # local build; no registry claim
            return json.dumps(record)
        return docker(*args[1:], timeout=timeout)

    def rootless_read(_home, _binary, _endpoint, *args: str, **_kwargs) -> str:
        if args[:2] == ("image", "inspect"):
            image = next(image for image, record in images.items() if record["Id"] == args[-1])
            record = copy.deepcopy(images[image])
            record["RepoDigests"] = [virtual[image]]  # metadata adapter only
            return json.dumps(record)
        assert args[:2] == ("network", "inspect")
        return docker(*args)

    def root_file(name: str, **_kwargs) -> bytes:
        assert name == "seccomp_profile.json"
        return seccomp

    deploy._run = production_run
    deploy._browser_root_file = root_file
    rootless._command = rootless_read
    home = Path("/home/boca-deploy")
    marker = {
        "source_sha": source,
        "attempt_id": attempt,
        "controller_digest": virtual[controller_image],
        "browser_digest": virtual[browser_image],
    }

    def inspected(container: str) -> dict:
        record = json.loads(docker("inspect", "--format", "{{json .}}", container))
        image = record["Config"]["Image"]
        assert record["Image"] == images[image]["Id"]
        record["Config"]["Image"] = virtual[image]  # only registry-reference adapter
        return record

    if len(sys.argv) == 5 and sys.argv[1] == "pair":
        running = sys.argv[2] == "running"
        assert sys.argv[2] in {"running", "stopped"}
        controller, worker = sys.argv[3:]
        assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (controller, worker))
        if running:
            deploy._browser_wait_healthy(worker)
            deploy._browser_wait_healthy(controller)
        identities = {}
        for container, service in ((worker, "browser-worker"), (controller, "controller")):
            raw_record = json.loads(docker("inspect", "--format", "{{json .}}", container))
            identities[container] = runtime_identity(raw_record)
            print(
                "BOCA_CI_DOCKER_INSPECT "
                + json.dumps(inspection_summary(raw_record, service=service), sort_keys=True),
                flush=True,
            )
        deploy._browser_worker_postflight(
            worker,
            browser_image,
            source,
            attempt,
            hashlib.sha256(seccomp).hexdigest(),
            running=running,
        )
        deploy._browser_controller_postflight(
            controller,
            controller_image,
            source,
            attempt,
            "http://localhost:8443",
            "synthetic-owner",
            running=running,
        )
        for container in (controller, worker):
            assert rootless._verified_browser_ipc_image(
                home, "local-ci", inspected(container), (marker, json.loads(seccomp))
            )
        if running:
            peer = peer_receipt(
                docker(
                    "exec",
                    "--user",
                    "10001:10001",
                    controller,
                    "python",
                    "-c",
                    PEER_DIAGNOSTIC,
                    timeout=8,
                )
            )
            print("BOCA_CI_IPC_PEER " + json.dumps(peer, sort_keys=True), flush=True)
            rejected = docker(
                "exec",
                "--user",
                "10003:10003",
                controller,
                "python",
                "-c",
                FOREIGN_UID_PROBE,
                timeout=8,
            )
            if rejected != FOREIGN_UID_RECEIPT:
                raise RuntimeError("foreign peer rejection receipt unverified")
            for container in (controller, worker):
                after = json.loads(docker("inspect", "--format", "{{json .}}", container))
                if runtime_identity(after) != identities[container]:
                    raise RuntimeError("service changed during foreign peer rejection")
            print(FOREIGN_UID_RECEIPT + " services=unchanged", flush=True)
        print(
            f"BOCA_CI_BROWSER_LIFECYCLE state=PASS services=2 running={str(running).lower()}"
            " inspect=real kernel=real_when_running images=local_unpublished provider=not_contacted"
        )
        return
    assert sys.argv[1:] == ["sender"]
    command = deploy._telegram_worker_container(
        controller_image, source, BOT, CHAT_HMAC, attempt, attempt
    )
    offline = list(command[1:])
    offline[offline.index(deploy.TELEGRAM_NETWORK)] = "none"
    offline[offline.index(deploy.TELEGRAM_WORKER_NAME)] = f"boca-ci-telegram-offline-{attempt}"
    offline_id = docker(*offline)
    assert re.fullmatch(r"[0-9a-f]{64}", offline_id)
    deploy._telegram_worker_ready(offline_id, source)
    assert (
        docker(
            "exec",
            "--user",
            "10001:10001",
            offline_id,
            "python",
            "-c",
            "import os; from boca_socios.telegram_one_shot import require_effective_limits; "
            "assert os.geteuid()==os.getegid()==10001; "
            "assert os.listdir('/sys/class/net')==['lo']; require_effective_limits(); print('PASS')",
        )
        == "PASS"
    )
    docker("stop", "--time", "10", offline_id)
    docker("rm", offline_id)
    # The production network/container are CREATED but NEVER STARTED here.
    docker(
        "network",
        "create",
        "--driver",
        "bridge",
        "--label",
        "com.docker.compose.project=boca-socios",
        "--label",
        "com.docker.compose.network=telegram_egress",
        "--label",
        f"{deploy.BROWSER_ATTEMPT_LABEL}={attempt}",
        "--label",
        f"{deploy.TELEGRAM_ATTEMPT_LABEL}={attempt}",
        deploy.TELEGRAM_NETWORK,
    )
    created = list(command[1:])
    created[0] = "create"
    created.remove("--detach")
    sender = docker(*created)
    sender_record = json.loads(docker("inspect", "--format", "{{json .}}", sender))
    print(
        "BOCA_CI_DOCKER_INSPECT "
        + json.dumps(inspection_summary(sender_record, service="telegram"), sort_keys=True),
        flush=True,
    )
    deploy._telegram_worker_inspect(
        sender,
        controller_image,
        source,
        BOT,
        CHAT_HMAC,
        attempt,
        running=False,
        runtime_attempt=attempt,
    )
    record = inspected(sender)
    assert rootless._verified_telegram_image(home, "local-ci", record, record["Config"])
    print(
        "BOCA_CI_TELEGRAM_LIFECYCLE state=PASS runtime_network=none production_network=never_started"
        " inspect=real kernel=real ledger=synthetic images=local_unpublished provider=not_contacted"
    )


if __name__ == "__main__":
    main()
