"""TDD contract for a zero-effect, double-read installed Boca service pair."""

from __future__ import annotations

import json
from importlib import import_module

import pytest

from boca_socios import host_boca_census as census

RUN_ID = "43058130210"
SOURCE = "bd6c1212f129454f10e5d4a25585c3f4eeb8edea"
ATTEMPT = "43010000000"
HIST_SOURCE = "03df9a14bdd78cf768386a865876fed9d5656911"
HIST_ATTEMPT = "42806447101"
ROOT = (123, 456)
CONTROLLER_ID = "a" * 64
WORKER_ID = "b" * 64
NETWORK_ID = "c" * 64
WORKER_NETWORK_ID = "8" * 64
CTRL_IMAGE_ID = "sha256:" + "d" * 64
WORKER_IMAGE_ID = "sha256:" + "e" * 64
CTRL_REF = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64
WORKER_REF = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64


def _pair():
    return import_module("boca_socios.host_boca_pair_observe")


def _container(ident, service, running, *, source=SOURCE, attempt=ATTEMPT):
    return census.CensusContainer(
        ident,
        f"/boca-socios-{service}-1",
        running,
        tuple(
            sorted(
                {
                    "com.docker.compose.project": "boca-socios",
                    "com.docker.compose.service": service,
                    "com.docker.compose.config-hash": "f" * 64,
                    "org.opencontainers.image.revision": source,
                    "boca.socios.browser-ipc-attempt": attempt,
                }.items()
            )
        ),
    )


def _snapshot(*, worker_running=False, foreign=False, source=SOURCE, attempt=ATTEMPT):
    return census.CensusSnapshot(
        (
            _container(CONTROLLER_ID, "controller", True, source=source, attempt=attempt),
            _container(WORKER_ID, "browser-worker", worker_running, source=source, attempt=attempt),
        ),
        frozenset((NETWORK_ID, WORKER_NETWORK_ID)),
        frozenset(
            (
                "boca-socios_boca_data",
                "boca-socios_boca_key",
                "boca-socios_boca_owner",
                "boca-socios_boca_browser_ipc",
                "boca-socios_boca_site_config",
            )
        )
        | (frozenset(("foreign_data",)) if foreign else frozenset()),
        ROOT,
    )


def _fields():
    return {
        (CONTROLLER_ID, "Image"): CTRL_IMAGE_ID,
        (WORKER_ID, "Image"): WORKER_IMAGE_ID,
        (CONTROLLER_ID, "Config.Image"): CTRL_REF,
        (WORKER_ID, "Config.Image"): WORKER_REF,
        (CONTROLLER_ID, "State.Health.Status"): "healthy",
        (WORKER_ID, "State.Health.Status"): "unhealthy",
        (CONTROLLER_ID, "State.Status"): "running",
        (WORKER_ID, "State.Status"): "created",
        (CONTROLLER_ID, "State.Pid"): 11111,
        (WORKER_ID, "State.Pid"): 0,
        (CONTROLLER_ID, "State.ExitCode"): 0,
        (WORKER_ID, "State.ExitCode"): 0,
        (CONTROLLER_ID, "HostConfig.PortBindings"): {
            "8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]
        },
        (WORKER_ID, "HostConfig.PortBindings"): None,
        (CONTROLLER_ID, "NetworkSettings.Networks"): {
            "boca-socios_boca_private": {"NetworkID": NETWORK_ID}
        },
        (WORKER_ID, "NetworkSettings.Networks"): {
            "boca-socios_boca_browser_egress": {"NetworkID": WORKER_NETWORK_ID}
        },
        (CONTROLLER_ID, "Mounts"): [
            {"Type": "volume", "Name": "boca-socios_boca_data", "Destination": "/data", "RW": True},
            {
                "Type": "volume",
                "Name": "boca-socios_boca_key",
                "Destination": "/run/secrets",
                "RW": False,
            },
            {
                "Type": "volume",
                "Name": "boca-socios_boca_owner",
                "Destination": "/run/owner",
                "RW": False,
            },
            {
                "Type": "volume",
                "Name": "boca-socios_boca_browser_ipc",
                "Destination": "/run/boca-browser-ipc",
                "RW": False,
            },
            {
                "Type": "volume",
                "Name": "boca-socios_boca_site_config",
                "Destination": "/run/boca-site-config",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/home/boca-deploy/.boca-on-demand/socket",
                "Destination": "/run/boca-bot-control",
                "RW": False,
                "Propagation": "rprivate",
            },
        ],
        (WORKER_ID, "Mounts"): [
            {
                "Type": "volume",
                "Name": "boca-socios_boca_browser_ipc",
                "Destination": "/run/boca-browser-ipc",
                "RW": True,
            },
            {
                "Type": "volume",
                "Name": "boca-socios_boca_site_config",
                "Destination": "/run/boca-site-config",
                "RW": False,
            },
        ],
    }


def _run(*, snapshots=None, fields=None, source=SOURCE):
    snapshots = [_snapshot(), _snapshot()] if snapshots is None else snapshots
    fields = _fields() if fields is None else fields
    readings = iter(snapshots)
    return _pair().observe(
        RUN_ID,
        inventory_reader=lambda: next(readings),
        container_field_reader=lambda ident, field: fields[(ident, field)],
        image_label_reader=lambda _ident, field: {
            "org.opencontainers.image.source": "https://github.com/mbalbo2023/boca-socios-assistant",
            "org.opencontainers.image.revision": source,
        }[field],
        effective_uid=10001,
        effective_gid=10001,
    )


def test_pair_receipt_contains_exact_proven_ids_and_no_sensitive_mount_or_env_values():
    raw = _run()
    assert _pair().verify(raw, RUN_ID) == raw
    result = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
    assert result["state"] == "OBSERVED"
    assert result["observation_run_id"] == RUN_ID
    assert result["cutover_authorized"] is False
    assert result["observer_writes"] == 0
    assert result["foreign_resources_touched"] == 0
    assert result["source_sha"] == SOURCE
    assert result["attempt_id"] == ATTEMPT
    assert {service["container_id"] for service in result["services"]} == {
        CONTROLLER_ID,
        WORKER_ID,
    }
    assert result["services"][0]["image_id"] == CTRL_IMAGE_ID
    assert result["services"][1]["image_ref"] == WORKER_REF
    assert result["services"][0]["port_8443"] == "LOOPBACK"
    assert result["services"][1]["port_8443"] == "NONE"
    assert result["services"][1]["running"] is False
    assert result["services"][0]["health"] == "healthy"
    assert result["services"][1]["health"] == "unhealthy"
    assert result["services"][0]["status"] == "running"
    assert result["services"][0]["pid"] == 11111
    assert result["services"][1]["status"] == "created"
    assert result["services"][1]["pid"] == 0
    assert result["services"][1]["exit_code"] == 0
    assert result["ipc_volume"] == "BOTH"
    assert b"/data" not in raw and b"/run/" not in raw
    assert b"Config.Env" not in raw and b"Source" not in raw


def test_created_worker_missing_health_is_a_bounded_none_not_docker_template_error(
    monkeypatch,
):
    from boca_socios import host_boca_cleanup as cleanup

    calls = []

    def docker(*args):
        calls.append(args)
        if "{{if .State.Health}}" not in args[2]:
            raise cleanup.CleanupError("PRIVATE_NIL_HEALTH_FIELD")
        return "null\n"

    monkeypatch.setattr(cleanup, "_docker", docker)
    result = _pair()._fields_from_proven_boca(WORKER_ID, "State.Health.Status")
    assert result is None
    assert calls == [
        (
            "inspect",
            "--format",
            "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}",
            WORKER_ID,
        )
    ]


def test_pair_created_worker_none_health_remains_unstarted_and_unverified():
    fields = _fields()
    fields[(WORKER_ID, "State.Health.Status")] = None
    raw = _run(fields=fields)
    assert _pair().verify(raw, RUN_ID) == raw
    worker = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))["services"][1]
    assert worker["health"] == "none"
    assert worker["status"] == "created"
    assert worker["pid"] == 0
    assert worker["running"] is False


def test_pair_health_probe_malformed_json_does_not_expose_host_bytes(monkeypatch):
    from boca_socios import host_boca_cleanup as cleanup

    monkeypatch.setattr(cleanup, "_docker", lambda *_args: "PRIVATE_HEALTH_VALUE")
    with pytest.raises(_pair().PairNoGo, match="Docker health unverified") as failure:
        _pair()._fields_from_proven_boca(WORKER_ID, "State.Health.Status")
    assert "PRIVATE_HEALTH_VALUE" not in str(failure.value)


def test_pair_double_reads_metadata_as_well_as_census():
    fields = _fields()
    calls = []

    def field(ident, name):
        calls.append((ident, name))
        return fields[(ident, name)]

    pair = _pair()
    inventories = iter((_snapshot(), _snapshot()))
    pair.observe(
        RUN_ID,
        inventory_reader=lambda: next(inventories),
        container_field_reader=field,
        image_label_reader=lambda _, name: {
            "org.opencontainers.image.source": "https://github.com/mbalbo2023/boca-socios-assistant",
            "org.opencontainers.image.revision": SOURCE,
        }[name],
        effective_uid=10001,
        effective_gid=10001,
    )
    assert calls.count((WORKER_ID, "Image")) == 2
    assert calls.count((CONTROLLER_ID, "HostConfig.PortBindings")) == 2


def test_pair_rejects_census_or_metadata_drift():
    with pytest.raises(_pair().PairNoGo):
        _run(snapshots=[_snapshot(), _snapshot(worker_running=True)])
    changing = _fields()
    source = changing[(CONTROLLER_ID, "Image")]
    attempts = iter((source, "sha256:" + "9" * 64))

    def drifting(ident, name):
        if (ident, name) == (CONTROLLER_ID, "Image"):
            return next(attempts)
        return changing[(ident, name)]

    with pytest.raises(_pair().PairNoGo):
        _pair().observe(
            RUN_ID,
            inventory_reader=lambda: _snapshot(),
            container_field_reader=drifting,
            image_label_reader=lambda _, name: {
                "org.opencontainers.image.source": "https://github.com/mbalbo2023/boca-socios-assistant",
                "org.opencontainers.image.revision": SOURCE,
            }[name],
            effective_uid=10001,
            effective_gid=10001,
        )


def test_pair_checks_exact_controller_host_bind_without_publishing_its_path():
    fields = _fields()
    raw = _run(fields=fields)
    assert b"/home/boca-deploy" not in raw
    assert _pair().verify(raw, RUN_ID) == raw
    fields[(CONTROLLER_ID, "Mounts")][-1]["Source"] = "/var/lib/foreign-control"
    with pytest.raises(_pair().PairNoGo):
        _run(fields=fields)


def test_pair_requires_separate_controller_and_worker_network_identities():
    fields = _fields()
    fields[(WORKER_ID, "NetworkSettings.Networks")] = {
        "boca-socios_boca_browser_egress": {"NetworkID": NETWORK_ID}
    }
    with pytest.raises(_pair().PairNoGo):
        _run(fields=fields)


def test_pair_full_boca_volume_inventory_stays_bounded_below_4096_bytes():
    # Maximal schema projection, including all six allowlisted Boca volumes,
    # two immutable image digests, both network IDs and two full container IDs.
    volume_names = frozenset(
        {
            "boca-socios_boca_data",
            "boca-socios_boca_key",
            "boca-socios_boca_owner",
            "boca-socios_boca_telegram",
            "boca-socios_boca_browser_ipc",
            "boca-socios_boca_site_config",
        }
    )
    original = _snapshot()
    maximal = census.CensusSnapshot(
        original.containers, original.network_ids, volume_names, original.docker_root_identity
    )
    fields = _fields()
    raw = _run(snapshots=[maximal, maximal], fields=fields)
    assert 1600 < len(raw) <= 4096
    assert _pair().verify(raw, RUN_ID) == raw


@pytest.mark.parametrize(
    ("target", "replacement"),
    [
        (
            (CONTROLLER_ID, "HostConfig.PortBindings"),
            {"8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]},  # noqa: S104 - negative public fixture
        ),
        (
            (WORKER_ID, "HostConfig.PortBindings"),
            {"8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]},  # noqa: S104 - negative public fixture
        ),
        (
            (WORKER_ID, "Mounts"),
            [{"Type": "volume", "Name": "foreign_data", "Destination": "/run/boca-browser-ipc"}],
        ),
        ((CONTROLLER_ID, "Config.Image"), "ubuntu:latest"),
    ],
)
def test_pair_rejects_public_ports_foreign_mounts_and_unpinned_images(target, replacement):
    fields = _fields()
    fields[target] = replacement
    with pytest.raises(_pair().PairNoGo):
        _run(fields=fields)


def test_pair_never_exposes_raw_exception_or_unverified_attestation(capsys, monkeypatch):
    pair = _pair()
    monkeypatch.setattr(pair, "observe", lambda *_: (_ for _ in ()).throw(ValueError("SECRET")))
    assert pair.main(["host", RUN_ID]) == 3
    out = capsys.readouterr()
    assert out.err == ""
    assert out.out == "BOCA_INSTALLED_PAIR state=NO_GO reason=UNVERIFIED observer_writes=0\n"


def test_pair_rejects_receipt_spoof_and_extra_fields():
    raw = _run()
    with pytest.raises(_pair().PairNoGo):
        _pair().verify(raw.replace(b'"observer_writes":0', b'"observer_writes":1'), RUN_ID)
    with pytest.raises(_pair().PairNoGo):
        _pair().verify(raw.replace(b'"state":"OBSERVED"', b'"state":"GREEN"'), RUN_ID)


def test_pair_observes_exact_historical_v3_none_network_without_site_config():
    """The actual 03df9a Cutover V3 used --network none and IPC-only mounts."""
    historical = _snapshot(source=HIST_SOURCE, attempt=HIST_ATTEMPT)
    volumes = frozenset(
        {
            "boca-socios_boca_data",
            "boca-socios_boca_key",
            "boca-socios_boca_owner",
            "boca-socios_boca_browser_ipc",
        }
    )
    historical = census.CensusSnapshot(
        historical.containers, historical.network_ids, volumes, historical.docker_root_identity
    )
    fields = _fields()
    fields[(WORKER_ID, "NetworkSettings.Networks")] = {
        "none": {"NetworkID": "", "IPAddress": "", "GlobalIPv6Address": ""}
    }
    fields[(CONTROLLER_ID, "Mounts")] = [
        item
        for item in fields[(CONTROLLER_ID, "Mounts")]
        if item.get("Name") != "boca-socios_boca_site_config"
    ]
    fields[(WORKER_ID, "Mounts")] = [
        item
        for item in fields[(WORKER_ID, "Mounts")]
        if item.get("Name") != "boca-socios_boca_site_config"
    ]
    raw = _run(snapshots=[historical, historical], fields=fields, source=HIST_SOURCE)
    receipt = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
    assert receipt["source_sha"] == HIST_SOURCE
    assert receipt["attempt_id"] == HIST_ATTEMPT
    assert receipt["services"][1]["network_name"] == "none"
    assert receipt["services"][1]["network_id"] == "UNATTACHED"
    assert receipt["services"][1]["status"] == "created"


@pytest.mark.parametrize(
    "field,invalid",
    [("Destination", "/tmp/broken"), ("RW", True)],  # noqa: S108 - negative fixture
)
def test_pair_rejects_wrong_controller_ipc_mount_location_or_writability(field, invalid):
    fields = _fields()
    for item in fields[(CONTROLLER_ID, "Mounts")]:
        if item.get("Name") == "boca-socios_boca_browser_ipc":
            item[field] = invalid
    with pytest.raises(_pair().PairNoGo):
        _run(fields=fields)


def test_pair_rejects_missing_controller_control_socket_bind():
    fields = _fields()
    fields[(CONTROLLER_ID, "Mounts")] = [
        item for item in fields[(CONTROLLER_ID, "Mounts")] if item["Type"] != "bind"
    ]
    with pytest.raises(_pair().PairNoGo):
        _run(fields=fields)


def test_pair_reports_exited_worker_with_nonzero_exit_instead_of_created():
    fields = _fields()
    fields[(WORKER_ID, "State.Status")] = "exited"
    fields[(WORKER_ID, "State.ExitCode")] = 1
    raw = _run(fields=fields)
    result = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
    assert result["services"][1]["status"] == "exited"
    assert result["services"][1]["pid"] == 0
    assert result["services"][1]["exit_code"] == 1


def test_pair_runner_rejects_same_network_id_for_different_service_roles():
    raw = _run()
    forged = raw.replace(WORKER_NETWORK_ID.encode("ascii"), NETWORK_ID.encode("ascii"))
    with pytest.raises(_pair().PairNoGo):
        _pair().verify(forged, RUN_ID)
