"""Observe one installed Boca pair and verify its bounded receipt in the Actions runner."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields, replace

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_lifecycle as host
from boca_socios import host_first_deploy as deploy
from boca_socios.host_boca_cleanup import BocaJobLease, protected_boca_job_lease
from boca_socios.host_lifecycle_rootless_adapter import (
    ProductionRootlessDockerIO,
    RootlessLifecycleProbe,
)
from boca_socios.host_on_demand_lifecycle import (
    OnDemandInstallation,
    PanelStatus,
    read_panel_status,
    validate_panel_status,
)
from boca_socios.host_on_demand_service import read_installed_binding

PREFIX = "BOCA_ON_DEMAND_STATUS "
CURRENT_PREFIX = "BOCA_CURRENT_STATUS "
NO_GO = PREFIX + "result=NO_GO"
EGRESS_PREFIX = "BOCA_ON_DEMAND_EGRESS "
_LIMIT = 2048
_WORKER_EGRESS_OK_LINE = "BOCA_WORKER_EGRESS state=PASS dns=PASS https=PASS\n"
_EGRESS_STAGES = frozenset(
    {"worker_stopped", "network_unverified", "dns", "tls", "https", "state_changed"}
)
# The shared attestor requires syntactically complete coordinates. Its fixed read-only
# placeholder is never presented to the ledger, sent on a socket or published as an intent.
_PROBE_ID = "00000000-0000-4000-8000-000000000001"
_FIELDS = frozenset(
    {
        "schema",
        "observation_run_id",
        "source_sha",
        "controller_image",
        "worker_image",
        "installation_run_id",
        "controller_id",
        "worker_id",
        "panel",
        "engine",
        "worker_state",
        "worker_pid",
        "worker_healthy",
        "operation",
    }
)
_OP_FIELDS = frozenset(field.name for field in fields(PanelStatus))


class StatusUnavailable(ValueError):
    """A stable, exact, safe-to-publish observation could not be verified."""


def _matches(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class _Pins:
    source_sha: str
    controller_image: str
    worker_image: str
    observation_run_id: str

    def validate(self) -> None:
        if not (
            _matches(self.source_sha, host._SHA)
            and _matches(self.controller_image, host._CONTROLLER_IMAGE)
            and _matches(self.worker_image, host._WORKER_IMAGE)
            and _matches(self.observation_run_id, host._ATTEMPT)
        ):
            raise StatusUnavailable


def _physical(
    installation: OnDemandInstallation,
    coordinates: host.LifecycleHostCoordinates,
    lease: BocaJobLease,
) -> tuple[str, int, bool, bool]:
    io = ProductionRootlessDockerIO()
    probe = RootlessLifecycleProbe(installation.pair, io, on_demand=True)
    state = probe.observe(coordinates, lease)
    engine = state.require(coordinates)
    phase = io.field("container", installation.worker_id, "State.Status")
    pid = io.field("container", installation.worker_id, "State.Pid")
    if type(phase) is not str or type(pid) is not int or state.worker_running != (pid > 0):
        raise StatusUnavailable
    return phase, pid, state.worker_healthy, engine


def _observe(pins: _Pins) -> dict[str, object]:
    with protected_boca_job_lease(pins.observation_run_id) as lease:
        installed = read_installed_binding(lease)
        if (installed.source_sha, installed.controller_image, installed.worker_image) != (
            pins.source_sha,
            pins.controller_image,
            pins.worker_image,
        ):
            raise StatusUnavailable
        coordinates = replace(installed.coordinates(_PROBE_ID), attempt_id=pins.observation_run_id)
        live = _physical(installed, coordinates, lease)
        operation = read_panel_status(installed)
        # The owner can submit a new request or the worker can exit on its own while
        # this read holds the deployment lease. Publish only a stable pair of samples.
        if (
            _physical(installed, coordinates, lease) != live
            or read_panel_status(installed) != operation
        ):
            raise StatusUnavailable
        phase, pid, healthy, engine = live
        return {
            "schema": 1,
            **asdict(pins),
            "installation_run_id": installed.installation_run_id,
            "controller_id": installed.controller_id,
            "worker_id": installed.worker_id,
            "panel": "HEALTHY",
            "engine": "RUNNING" if engine else "STOPPED",
            "worker_state": phase,
            "worker_pid": pid,
            "worker_healthy": healthy,
            "operation": asdict(operation) if operation is not None else None,
        }


def _checked(document: object, pins: _Pins) -> str:
    if type(document) is not dict or document.keys() != _FIELDS:
        raise StatusUnavailable
    if (
        type(document["schema"]) is not int
        or document["schema"] != 1
        or any(document[key] != value for key, value in asdict(pins).items())
        or not _matches(document["installation_run_id"], host._ATTEMPT)
        or document["installation_run_id"] == pins.observation_run_id
        or not _matches(document["controller_id"], host._ID)
        or not _matches(document["worker_id"], host._ID)
        or document["controller_id"] == document["worker_id"]
        or document["panel"] != "HEALTHY"
        or document["engine"] not in ("STOPPED", "RUNNING")
    ):
        raise StatusUnavailable
    phase, pid, healthy = (
        document["worker_state"],
        document["worker_pid"],
        document["worker_healthy"],
    )
    if (
        phase not in ("created", "running", "exited", "dead", "paused")
        or type(pid) is not int
        or not 0 <= pid <= 2**31 - 1
        or (phase in ("running", "paused")) != (pid > 0)
        or type(healthy) is not bool
        or healthy
        and not pid
    ):
        raise StatusUnavailable
    operation = document["operation"]
    if operation is not None:
        if type(operation) is not dict or operation.keys() != _OP_FIELDS:
            raise StatusUnavailable
        validate_panel_status(PanelStatus(**operation))
    return PREFIX + json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n"


def _current_checked(document: object, workflow_sha: str, run: str) -> str:
    """Runner source authenticates the observer; installed source is its result."""
    if (
        not _matches(workflow_sha, host._SHA)
        or not _matches(run, host._ATTEMPT)
        or type(document) is not dict
        or document.keys() != {"schema", "workflow_source_sha", "installed"}
        or type(document["schema"]) is not int
        or document["schema"] != 2
        or document["workflow_source_sha"] != workflow_sha
        or type(document["installed"]) is not dict
    ):
        raise StatusUnavailable
    installed = document["installed"]
    pins = _Pins(
        installed["source_sha"], installed["controller_image"], installed["worker_image"], run
    )
    pins.validate()
    _checked(installed, pins)
    return CURRENT_PREFIX + json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n"


def _observe_current(workflow_sha: str, run: str) -> dict[str, object]:
    if not _matches(workflow_sha, host._SHA) or not _matches(run, host._ATTEMPT):
        raise StatusUnavailable
    with protected_boca_job_lease(run) as lease:
        installed = read_installed_binding(lease)
        pins = _Pins(installed.source_sha, installed.controller_image, installed.worker_image, run)
        pins.validate()
        coordinates = replace(installed.coordinates(_PROBE_ID), attempt_id=run)
        live = _physical(installed, coordinates, lease)
        operation = read_panel_status(installed)
        if (
            _physical(installed, coordinates, lease) != live
            or read_panel_status(installed) != operation
            or read_installed_binding(lease) != installed
        ):
            raise StatusUnavailable
        phase, pid, healthy, engine = live
        return {
            "schema": 2,
            "workflow_source_sha": workflow_sha,
            "installed": {
                "schema": 1,
                **asdict(pins),
                "installation_run_id": installed.installation_run_id,
                "controller_id": installed.controller_id,
                "worker_id": installed.worker_id,
                "panel": "HEALTHY",
                "engine": "RUNNING" if engine else "STOPPED",
                "worker_state": phase,
                "worker_pid": pid,
                "worker_healthy": healthy,
                "operation": asdict(operation) if operation is not None else None,
            },
        }


def _egress_line(pins: _Pins, stage: str) -> str:
    """One category-only, run-bound attestation; no remote output forwarded."""
    prefix = EGRESS_PREFIX + f"run={pins.observation_run_id} source={pins.source_sha} "
    if stage == "none":
        return prefix + "state=PASS dns=PASS https=PASS\n"
    if stage not in _EGRESS_STAGES:
        raise StatusUnavailable
    return prefix + f"state=NO_GO stage={stage}\n"


def _egress_observe(pins: _Pins) -> str:
    """Use only an already-running, attested Boca worker; do not start Docker."""
    with protected_boca_job_lease(pins.observation_run_id) as lease:
        installed = read_installed_binding(lease)
        if (installed.source_sha, installed.controller_image, installed.worker_image) != (
            pins.source_sha,
            pins.controller_image,
            pins.worker_image,
        ):
            raise StatusUnavailable
        coordinates = replace(installed.coordinates(_PROBE_ID), attempt_id=pins.observation_run_id)
        before = _physical(installed, coordinates, lease)
        if before[0] != "running" or before[1] <= 0 or not before[2]:
            return _egress_line(pins, "worker_stopped")
        io = ProductionRootlessDockerIO()
        network = io.field("container", installed.worker_id, "NetworkSettings.Networks")
        try:
            deploy._browser_worker_egress_network(network)
        except deploy.PreflightError:
            return _egress_line(pins, "network_unverified")
        panel = read_panel_status(installed)
        # cleanup._docker pins /run/user/10001/docker.sock and sanitizes all
        # daemon environment variables.  The attested CID is used directly;
        # never search by name, pull an image, start/stop or mount anything.
        raw = cleanup._docker(
            "exec",
            "--user",
            "10002:10002",
            installed.worker_id,
            "python",
            "-m",
            "boca_socios.browser.egress_probe",
            "--once",
        )
        if raw == _WORKER_EGRESS_OK_LINE:
            stage = "none"
        else:
            matches = [
                candidate
                for candidate in ("dns", "tls", "https")
                if raw == f"BOCA_WORKER_EGRESS state=NO_GO stage={candidate}\n"
            ]
            if len(matches) != 1:
                raise StatusUnavailable
            stage = matches[0]
        if (
            _physical(installed, coordinates, lease) != before
            or io.field("container", installed.worker_id, "NetworkSettings.Networks") != network
            or read_panel_status(installed) != panel
        ):
            return _egress_line(pins, "state_changed")
        return _egress_line(pins, stage)


def _egress_checked(raw: bytes, pins: _Pins) -> str:
    if len(raw) > 256:
        raise StatusUnavailable
    for stage in ("none", *sorted(_EGRESS_STAGES)):
        expected = _egress_line(pins, stage)
        if raw == expected.encode("ascii"):
            return expected
    raise StatusUnavailable


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 3 and args[0] in ("host-current", "verify-current"):
            if args[0] == "host-current":
                line = _current_checked(_observe_current(args[1], args[2]), args[1], args[2])
            else:
                raw = sys.stdin.buffer.read(_LIMIT + 1)
                if len(raw) > _LIMIT or not raw.startswith(CURRENT_PREFIX.encode("ascii")):
                    raise StatusUnavailable
                line = _current_checked(
                    json.loads(raw[len(CURRENT_PREFIX) :].decode("ascii")), args[1], args[2]
                )
                if line.encode("ascii") != raw:
                    raise StatusUnavailable
            sys.stdout.write(line)
            return 0
        if len(args) != 5 or args[0] not in ("host", "verify", "host-egress", "verify-egress"):
            raise StatusUnavailable
        pins = _Pins(*args[1:])
        pins.validate()
        if args[0] == "host-egress":
            line = _egress_observe(pins)
        elif args[0] == "verify-egress":
            line = _egress_checked(sys.stdin.buffer.read(257), pins)
        elif args[0] == "host":
            line = _checked(_observe(pins), pins)
        else:
            raw = sys.stdin.buffer.read(_LIMIT + 1)
            if len(raw) > _LIMIT or not raw.startswith(PREFIX.encode("ascii")):
                raise StatusUnavailable
            line = _checked(json.loads(raw[len(PREFIX) :].decode("ascii")), pins)
            if line.encode("ascii") != raw:
                raise StatusUnavailable
    except Exception:
        # A daemon, SQLite, JSON or IO exception can contain private data. Only the
        # finite failure line is permissible on either side of the SSH boundary.
        print(NO_GO)
        return 3
    sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
