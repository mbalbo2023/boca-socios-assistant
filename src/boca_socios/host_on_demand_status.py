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
# This program uses only helpers already present in the installed R294 controller.
# It travels with the observer: changing a host reader must not require a new image.
# Keep request, binding and note reads in the same attested, query-only snapshot.
_CURRENT_LEDGER_PROGRAM = """\
import json
import sys
from dataclasses import asdict
from pathlib import Path
try:
    from boca_socios.host_on_demand_lifecycle import (
        _AUDIT, _FINGERPRINT, _NO_DETAIL, _detail, _marker_id, _uuid,
        PanelStatus, validate_panel_status,
    )
    from boca_socios.host_boca_lifecycle import _controller_ledger
    from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
    fingerprint, path = sys.argv[1:]
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError()
    scope, operation = 'NONE', None
    with _controller_ledger(Path(path), readonly=True) as db:
        item = LifecycleIntentStore._current(db)
        if item is not None:
            if item.status in ('REQUESTED', 'CLAIMED', 'UNCERTAIN'):
                raise ValueError()
            if item.on_demand:
                if item.component != 'bot' or not _uuid(item.operation_id):
                    raise ValueError()
                key = _marker_id(item.operation_id, fingerprint, 'binding')
                bound = db.execute(
                    'SELECT action FROM audit_events WHERE audit_id=?', (key,)
                ).fetchone()
                note = db.execute(
                    'SELECT action FROM audit_events WHERE audit_id=?',
                    (_marker_id(item.operation_id, fingerprint, 'note'),),
                ).fetchone()
                if bound is not None and bound != (_AUDIT + 'bound',):
                    raise ValueError()
                if bound is None:
                    if note is not None or (item.target, item.status) != ('stop', 'APPLIED'):
                        raise ValueError()
                    scope = 'NOT_BOUND_TO_CURRENT_INSTALLATION'
                    operation = PanelStatus(item.operation_id, 'stop', 'APPLIED',
                                            'NONE', None, None, None)
                else:
                    scope = 'CURRENT_INSTALLATION'
                    detail = _detail(note[0].removeprefix(_AUDIT + 'note_')
                                     if note else _NO_DETAIL)
                    operation = PanelStatus(item.operation_id, item.target, item.status,
                        detail.cause, detail.exit_code, detail.oom, detail.exit_signature)
                validate_panel_status(operation)
    print(json.dumps({'schema': 1, 'scope': scope,
        'operation': asdict(operation) if operation is not None else None},
        separators=(',', ':'), sort_keys=True))
except Exception:
    raise SystemExit(3)
"""


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
        or document.keys() != {"schema", "workflow_source_sha", "installed", "ledger"}
        or type(document["schema"]) is not int
        or document["schema"] != 3
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
    scope, operation = _ledger_checked(document["ledger"])
    if installed["operation"] != (
        asdict(operation) if operation is not None and scope == "CURRENT_INSTALLATION" else None
    ):
        raise StatusUnavailable
    if scope == "NOT_BOUND_TO_CURRENT_INSTALLATION" and (
        installed["worker_state"] != "created"
        or installed["worker_pid"] != 0
        or installed["worker_healthy"] is not False
        or installed["engine"] != "STOPPED"
    ):
        raise StatusUnavailable
    return CURRENT_PREFIX + json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n"


def _ledger_checked(document: object) -> tuple[str, PanelStatus | None]:
    if (
        type(document) is not dict
        or document.keys() != {"schema", "scope", "operation"}
        or type(document["schema"]) is not int
        or document["schema"] != 1
        or document["scope"]
        not in ("NONE", "CURRENT_INSTALLATION", "NOT_BOUND_TO_CURRENT_INSTALLATION")
    ):
        raise StatusUnavailable
    scope, raw = document["scope"], document["operation"]
    if scope == "NONE":
        if raw is not None:
            raise StatusUnavailable
        return scope, None
    if type(raw) is not dict or raw.keys() != _OP_FIELDS:
        raise StatusUnavailable
    operation = PanelStatus(**raw)
    validate_panel_status(operation)
    if operation.status not in ("APPLIED", "REFUSED", "FAILED") or (
        scope == "NOT_BOUND_TO_CURRENT_INSTALLATION"
        and (operation.target, operation.status) != ("stop", "APPLIED")
    ):
        raise StatusUnavailable
    return scope, operation


def _read_current_ledger(installation: OnDemandInstallation) -> dict[str, object]:
    installation.coordinates(_PROBE_ID)
    raw = cleanup._docker(
        "exec",
        "--user",
        "10001:10001",
        installation.controller_id,
        "/app/.venv/bin/python",
        "-I",
        "-B",
        "-c",
        _CURRENT_LEDGER_PROGRAM,
        installation.fingerprint(),
        str(installation.database_path),
    )
    if type(raw) is not str or len(raw) > 512:
        raise StatusUnavailable
    document = json.loads(raw)
    _ledger_checked(document)
    if raw != json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n":
        raise StatusUnavailable
    return dict(document)


def _observe_current(workflow_sha: str, run: str) -> dict[str, object]:
    if not _matches(workflow_sha, host._SHA) or not _matches(run, host._ATTEMPT):
        raise StatusUnavailable
    with protected_boca_job_lease(run) as lease:
        installed = read_installed_binding(lease)
        pins = _Pins(installed.source_sha, installed.controller_image, installed.worker_image, run)
        pins.validate()
        coordinates = replace(installed.coordinates(_PROBE_ID), attempt_id=run)
        live = _physical(installed, coordinates, lease)
        ledger = _read_current_ledger(installed)
        scope, operation = _ledger_checked(ledger)
        if (
            _physical(installed, coordinates, lease) != live
            or _read_current_ledger(installed) != ledger
            or read_installed_binding(lease) != installed
        ):
            raise StatusUnavailable
        phase, pid, healthy, engine = live
        return {
            "schema": 3,
            "workflow_source_sha": workflow_sha,
            "ledger": ledger,
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
                "operation": (
                    asdict(operation)
                    if operation is not None and scope == "CURRENT_INSTALLATION"
                    else None
                ),
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
