"""Offline adversarial gates for opt-in browser-ipc-v2 host helper.

All Docker, rootless, network and filesystem host actions are mocks or
temporary local fixtures. No protected workflow, SSH or droplet is contacted.
The legacy singleton host flow remains covered by test_host_first_deploy.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from boca_socios import host_first_deploy as host
from boca_socios.host_first_deploy import PreflightError
from test_beta_browser_deploy_contract import BROWSER_IMAGE, browser_model
from test_beta_deploy_contract import ORIGIN, OWNER
from test_deploy_contract import IMAGE

SOURCE = "a" * 40
BETA_SHA = "b" * 64
OVERLAY_SHA = "c" * 64
SECCOMP_SHA = "d" * 64
ATTEMPT = "123456"
WORKER_ID = "e" * 64
CONTROLLER_ID = "f" * 64


def coordinates() -> dict[str, str]:
    return {
        "image": IMAGE,
        "source_sha": SOURCE,
        "beta_sha": BETA_SHA,
        "origin": ORIGIN,
        "owner": OWNER,
        "browser_image": BROWSER_IMAGE,
        "overlay_sha": OVERLAY_SHA,
        "seccomp_sha": SECCOMP_SHA,
        "attempt_id": ATTEMPT,
    }


def marker() -> dict[str, object]:
    return {
        "version": "browser-ipc-new-only-v2",
        "attempt_id": ATTEMPT,
        "source_sha": SOURCE,
        "controller_digest": IMAGE,
        "browser_digest": BROWSER_IMAGE,
        "beta_compose_sha": BETA_SHA,
        "overlay_compose_sha": OVERLAY_SHA,
        "seccomp_sha": SECCOMP_SHA,
        "controller_image_absent": True,
        "browser_image_absent": True,
        "bridge_absent": True,
        "ipc_volume_absent": True,
    }


def read_marker(monkeypatch: pytest.MonkeyPatch, value: object) -> dict[str, object]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    monkeypatch.setattr(host, "_browser_root_file", lambda *args, **kwargs: raw)
    return host._browser_read_marker(
        IMAGE, SOURCE, BETA_SHA, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA, ATTEMPT
    )


def test_browser_coordinates_are_fixed_immutable_and_private() -> None:
    host._browser_coordinates(**coordinates())


@pytest.mark.parametrize(
    ("version", "allowed"),
    [
        ("27.5.1", False),
        ("28.0.0-rc.1", False),
        ("28", False),
        ("latest", False),
        ("", False),
        ("28.0.0", True),
        ("28.5.2", True),
        ("29.1.2", True),
    ],
)
def test_docker_engine_below_28_cannot_claim_private_loopback(
    monkeypatch: pytest.MonkeyPatch, version: str, allowed: bool
) -> None:
    monkeypatch.setattr(host, "_run", lambda *args: version)
    if allowed:
        host._browser_engine_version()
    else:
        with pytest.raises(PreflightError, match="Docker Engine >=28"):
            host._browser_engine_version()


@pytest.mark.parametrize("operation", ["browser-preflight", "browser-apply"])
def test_old_engine_blocks_before_staging_pull_or_publish(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: "27.5.1")
    monkeypatch.setattr(
        host, "_browser_preflight_inventory", lambda: pytest.fail("host preflight continued")
    )
    monkeypatch.setattr(host, "_browser_read_marker", lambda *args: pytest.fail("marker read"))
    monkeypatch.setattr(host, "_browser_pull_both", lambda *args: pytest.fail("Docker pull"))
    arguments = (
        operation,
        IMAGE,
        SOURCE,
        BETA_SHA,
        ORIGIN,
        OWNER,
        BROWSER_IMAGE,
        OVERLAY_SHA,
        SECCOMP_SHA,
        ATTEMPT,
    )
    with pytest.raises(PreflightError, match="Docker Engine >=28"):
        host._browser_phase(*arguments)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image", IMAGE.replace("@sha256:", ":latest")),
        ("source_sha", "A" * 40),
        ("beta_sha", "123"),
        ("origin", "https://localhost:8443"),
        ("origin", "http://localhost:8444"),
        ("owner", "owner with spaces"),
        ("browser_image", IMAGE),
        ("browser_image", BROWSER_IMAGE.replace("@sha256:", ":latest")),
        ("overlay_sha", BETA_SHA),
        ("seccomp_sha", "b" * 64),
        ("attempt_id", ""),
        ("attempt_id", "0"),
        ("attempt_id", "001"),
        ("attempt_id", "1;id"),
        ("attempt_id", "9" * 21),
    ],
)
def test_browser_coordinates_fail_before_any_docker_access(field: str, value: str) -> None:
    candidate = coordinates()
    candidate[field] = value
    with pytest.raises(PreflightError):
        host._browser_coordinates(**candidate)


def test_browser_phase_routes_only_through_new_command_and_legacy_rejects_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: None)
    monkeypatch.setattr(host, "_browser_phase", lambda *args: seen.append(args))
    host.phase(
        "browser-preflight",
        IMAGE,
        SOURCE,
        BETA_SHA,
        ORIGIN,
        OWNER,
        browser_image=BROWSER_IMAGE,
        browser_overlay_sha=OVERLAY_SHA,
        browser_seccomp_sha=SECCOMP_SHA,
        browser_attempt_id=ATTEMPT,
    )
    assert seen == [
        (
            "browser-preflight",
            IMAGE,
            SOURCE,
            BETA_SHA,
            ORIGIN,
            OWNER,
            BROWSER_IMAGE,
            OVERLAY_SHA,
            SECCOMP_SHA,
            ATTEMPT,
        )
    ]
    with pytest.raises(PreflightError, match="legacy"):
        host.phase(
            "beta-preflight", IMAGE, SOURCE, BETA_SHA, ORIGIN, OWNER, browser_image=BROWSER_IMAGE
        )
    with pytest.raises(PreflightError, match="unknown browser"):
        host.phase(
            "browser-reset", IMAGE, SOURCE, BETA_SHA, ORIGIN, OWNER, browser_image=BROWSER_IMAGE
        )


def test_cli_accepts_expected_browser_flags_without_touching_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(host, "phase", lambda *args, **kwargs: observed.append((args, kwargs)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "host_first_deploy.py",
            "browser-config",
            IMAGE,
            SOURCE,
            BETA_SHA,
            ORIGIN,
            OWNER,
            "--browser-image",
            BROWSER_IMAGE,
            "--browser-overlay-sha",
            OVERLAY_SHA,
            "--browser-seccomp-sha",
            SECCOMP_SHA,
            "--browser-attempt-id",
            ATTEMPT,
        ],
    )
    assert host.main() == 0
    assert observed[0][0][:6] == (
        "browser-config",
        IMAGE,
        SOURCE,
        BETA_SHA,
        ORIGIN,
        OWNER,
    )
    assert observed[0][1] == {
        "browser_image": BROWSER_IMAGE,
        "browser_overlay_sha": OVERLAY_SHA,
        "browser_seccomp_sha": SECCOMP_SHA,
        "browser_attempt_id": ATTEMPT,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "legacy"),
        ("attempt_id", 123456),
        ("source_sha", "0" * 40),
        ("controller_digest", BROWSER_IMAGE),
        ("browser_digest", IMAGE),
        ("beta_compose_sha", "a" * 64),
        ("overlay_compose_sha", "a" * 64),
        ("seccomp_sha", "a" * 64),
        ("bridge_absent", False),
        ("ipc_volume_absent", False),
        ("controller_image_absent", 1),
        ("browser_image_absent", "true"),
    ],
)
def test_marker_rejects_drift_or_nonboolean_preexistence(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    candidate = marker()
    candidate[field] = value
    with pytest.raises(PreflightError):
        read_marker(monkeypatch, candidate)


def test_marker_rejects_extra_missing_duplicate_and_oversized_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert read_marker(monkeypatch, marker()) == marker()
    extra = marker()
    extra["stolen"] = "no"
    with pytest.raises(PreflightError):
        read_marker(monkeypatch, extra)
    missing = marker()
    del missing["browser_image_absent"]
    with pytest.raises(PreflightError):
        read_marker(monkeypatch, missing)
    raw = json.dumps(marker(), sort_keys=True, separators=(",", ":")).replace(
        '"bridge_absent":true', '"bridge_absent":true,"bridge_absent":true'
    )
    monkeypatch.setattr(host, "_browser_root_file", lambda *args, **kwargs: raw.encode())
    with pytest.raises(PreflightError, match="invalid"):
        host._browser_read_marker(
            IMAGE, SOURCE, BETA_SHA, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA, ATTEMPT
        )


@pytest.mark.parametrize("style", ["pretty", "reordered", "leading-newline"])
def test_marker_noncanonical_bytes_must_fail_before_cleanup(
    monkeypatch: pytest.MonkeyPatch, style: str
) -> None:
    candidate = marker()
    canonical = json.dumps(candidate, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    raw = {
        "pretty": json.dumps(candidate, indent=2),
        "reordered": json.dumps(candidate, separators=(",", ":")),
        "leading-newline": "\n" + canonical,
    }[style]
    assert raw != canonical
    monkeypatch.setattr(host, "_browser_root_file", lambda *args, **kwargs: raw.encode("ascii"))
    with pytest.raises(PreflightError, match="canonical"):
        host._browser_read_marker(
            IMAGE, SOURCE, BETA_SHA, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA, ATTEMPT
        )


def test_marker_creation_is_exclusive_and_canonical_without_other_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "BROWSER_MARKER", root / "browser-ipc-attempt.json")
    monkeypatch.setattr(host, "_browser_root_entries", lambda expected: None)
    native_fstat = os.fstat

    def fake_fstat(fd: int) -> object:
        metadata = native_fstat(fd)
        return SimpleNamespace(
            st_uid=10001,
            st_gid=10001,
            st_dev=metadata.st_dev,
            st_ino=metadata.st_ino,
            st_mode=metadata.st_mode,
            st_nlink=metadata.st_nlink,
            st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns,
            st_ctime_ns=metadata.st_ctime_ns,
        )

    monkeypatch.setattr(host.os, "fstat", fake_fstat)
    host._browser_write_marker(marker())
    file = root / "browser-ipc-attempt.json"
    assert json.loads(file.read_text()) == marker()
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert file.read_text() == json.dumps(marker(), sort_keys=True, separators=(",", ":"))
    with pytest.raises(PreflightError):
        host._browser_write_marker(marker())
    assert sorted(item.name for item in root.iterdir()) == ["browser-ipc-attempt.json"]


def test_preexisting_image_exact_inspect_preserves_prior_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, str]] = []

    def run(*args: object, **kwargs: object) -> object:
        assert args[0] == ("docker", "image", "inspect", "--format", "{{json .}}", IMAGE)
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        seen.append(environment)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "RepoDigests": [IMAGE],
                    "RepoTags": None,
                    "Size": 100_000_000,
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE}},
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("DOCKER_HOST", "ssh://foreign")
    monkeypatch.setenv("DOCKER_CONTEXT", "foreign")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setattr(host.subprocess, "run", run)
    assert host._browser_image_absent(IMAGE, SOURCE) is False
    assert seen[0]["DOCKER_HOST"] == "unix:///run/user/10001/docker.sock"
    assert "DOCKER_CONTEXT" not in seen[0]
    assert "DOCKER_TLS_VERIFY" not in seen[0]


@pytest.mark.parametrize(
    ("code", "stderr", "stdout", "absent"),
    [
        (1, f"Error: No such image: {IMAGE}\n", "", True),
        (1, f"Error response from daemon: No such image: {IMAGE}\n", "", True),
        (1, "Cannot connect to the Docker daemon", "", False),
        (1, f"Error: No such image: {BROWSER_IMAGE}", "", False),
        (2, f"Error: No such image: {IMAGE}", "", False),
        (1, f"Error: No such image: {IMAGE}", "unexpected output", False),
        (0, "warning", "{}", False),
        (0, "", "{}", False),
    ],
)
def test_image_absence_requires_only_literal_exact_docker_error(
    monkeypatch: pytest.MonkeyPatch,
    code: int,
    stderr: str,
    stdout: str,
    absent: bool,
) -> None:
    monkeypatch.setattr(
        host.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=code, stderr=stderr, stdout=stdout),
    )
    if absent:
        assert host._browser_image_absent(IMAGE, SOURCE) is True
    else:
        with pytest.raises(PreflightError):
            host._browser_image_absent(IMAGE, SOURCE)


@pytest.mark.parametrize(
    "deviation",
    [
        lambda m: m.update({"RepoDigests": []}),
        lambda m: m.update({"RepoDigests": [BROWSER_IMAGE]}),
        lambda m: m.update({"RepoDigests": [IMAGE, BROWSER_IMAGE]}),
        lambda m: m.update({"RepoTags": ["latest"]}),
        lambda m: m.update({"Size": True}),
        lambda m: m.update({"Size": "100"}),
        lambda m: m.update({"Size": 0}),
        lambda m: m["Config"]["Labels"].update({"org.opencontainers.image.revision": "f" * 40}),
        lambda m: m.update({"Config": {"Labels": {}}}),
        lambda m: m.update({"RepoDigests": "not-array"}),
    ],
)
def test_preexisting_image_revision_or_digest_mismatch_never_proves_absence(
    monkeypatch: pytest.MonkeyPatch, deviation: Any
) -> None:
    model: dict[str, Any] = {
        "RepoDigests": [IMAGE],
        "RepoTags": None,
        "Size": 100_000_000,
        "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE}},
    }
    deviation(model)
    monkeypatch.setattr(
        host.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(model),
        ),
    )
    with pytest.raises(PreflightError):
        host._browser_image_absent(IMAGE, SOURCE)


def test_staged_files_are_exact_hash_and_seccomp_deny_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = (Path(__file__).resolve().parents[1] / "docker/seccomp_profile.json").read_bytes()
    files = {
        "compose.beta.yaml": b"base synthetic yaml\n",
        "compose.beta.browser.yaml": b"overlay synthetic yaml\n",
        "seccomp_profile.json": profile,
    }
    monkeypatch.setattr(host, "_browser_root_entries", lambda expected: None)
    monkeypatch.setattr(host, "_browser_root_file", lambda name, **kwargs: files[name])
    hashes = [hashlib.sha256(files[name]).hexdigest() for name in files]
    host._browser_verify_staged(*hashes)
    for filename in files:
        candidate = deepcopy(files)
        candidate[filename] += b"tampered"
        monkeypatch.setattr(
            host, "_browser_root_file", lambda name, candidate=candidate, **kwargs: candidate[name]
        )
        with pytest.raises(PreflightError):
            host._browser_verify_staged(*hashes)
    files["seccomp_profile.json"] = (
        b'{"defaultAction":"SCMP_ACT_ALLOW","archMap":[1],"syscalls":[1]}'
    )
    monkeypatch.setattr(host, "_browser_root_file", lambda name, **kwargs: files[name])
    hashes = [hashlib.sha256(files[name]).hexdigest() for name in files]
    with pytest.raises(PreflightError, match="deny-by-default"):
        host._browser_verify_staged(*hashes)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m["services"]["browser-worker"].update({"network_mode": "bridge"}),
        lambda m: m["services"]["browser-worker"].update({"ports": ["8444:8444"]}),
        lambda m: m["services"]["browser-worker"]["environment"].update(
            {"BOCA_RUNTIME_MODE": "live"}
        ),
        lambda m: m["services"]["controller"].update({"restart": "unless-stopped"}),
        lambda m: m["services"]["controller"]["ports"][0].update(
            {"host_ip": "0.0.0.0"}  # noqa: S104 - intentionally forbidden wildcard fixture
        ),
        lambda m: m["services"].update({"foreign": {}}),
        lambda m: m["volumes"]["boca_browser_ipc"].update({"name": "foreign"}),
        lambda m: m["services"]["browser-worker"].update({"cpus": 1.0}),
    ],
)
def test_host_compose_model_rejects_injected_egress_port_or_legacy_restart(
    monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    candidate = browser_model()
    mutation(candidate)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: json.dumps(candidate))
    with pytest.raises(PreflightError):
        host._browser_compose_model(IMAGE, ORIGIN, OWNER, BROWSER_IMAGE, ATTEMPT)


def test_host_compose_model_accepts_only_resolved_versioned_offline_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = browser_model()
    raw = json.dumps(model)
    commands: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs: object) -> str:
        commands.append(args)
        assert kwargs["env"]["BOCA_BROWSER_IMAGE"] == BROWSER_IMAGE  # type: ignore[index]
        assert kwargs["env"]["BOCA_BROWSER_SECCOMP_PATH"] == str(host.BROWSER_SECCOMP)  # type: ignore[index]
        return raw

    monkeypatch.setattr(host, "_run", run)
    assert host._browser_compose_model(IMAGE, ORIGIN, OWNER, BROWSER_IMAGE, ATTEMPT) == raw
    assert commands == [
        (
            "docker",
            "compose",
            "-p",
            "boca-socios",
            "-f",
            str(host.BETA_COMPOSE),
            "-f",
            str(host.BROWSER_COMPOSE),
            "config",
            "--format",
            "json",
        )
    ]


def test_host_compose_model_cutover_uses_verified_stage_paths_without_global_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = host.ROOT / f"cutover-a-{ATTEMPT}"
    base, overlay, seccomp = (
        stage / host.BETA_COMPOSE.name,
        stage / host.BROWSER_COMPOSE.name,
        stage / host.BROWSER_SECCOMP.name,
    )
    model = browser_model()
    model["services"]["browser-worker"]["security_opt"][1] = f"seccomp={seccomp}"
    commands: list[tuple[str, ...]] = []

    def run(*args: str, **kwargs: object) -> str:
        commands.append(args)
        assert kwargs["env"]["BOCA_BROWSER_SECCOMP_PATH"] == str(seccomp)  # type: ignore[index]
        return json.dumps(model)

    monkeypatch.setattr(host, "_run", run)
    assert host._browser_compose_model(
        IMAGE,
        ORIGIN,
        OWNER,
        BROWSER_IMAGE,
        ATTEMPT,
        base_file=base,
        overlay_file=overlay,
        seccomp_file=seccomp,
    ) == json.dumps(model)
    assert commands == [
        (
            "docker",
            "compose",
            "-p",
            "boca-socios",
            "-f",
            str(base),
            "-f",
            str(overlay),
            "config",
            "--format",
            "json",
        )
    ]
    # Invocation cannot silently redirect future legacy Compose reads.
    assert host._browser_compose_args("ps")[:8] == (
        "docker",
        "compose",
        "-p",
        "boca-socios",
        "-f",
        str(host.BETA_COMPOSE),
        "-f",
        str(host.BROWSER_COMPOSE),
    )


@pytest.mark.parametrize("unsafe", ["partial", "outside", "wrong-seccomp"])
def test_host_compose_model_rejects_unauthorized_cutover_stage_paths_before_docker(
    monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    stage = host.ROOT / f"cutover-a-{ATTEMPT}"
    base, overlay, seccomp = (
        stage / host.BETA_COMPOSE.name,
        stage / host.BROWSER_COMPOSE.name,
        stage / host.BROWSER_SECCOMP.name,
    )
    monkeypatch.setattr(
        host,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("Docker must not run for unsafe stage paths"),
    )
    values: dict[str, Path | None] = {
        "base_file": base,
        "overlay_file": overlay,
        "seccomp_file": seccomp,
    }
    if unsafe == "partial":
        values["overlay_file"] = None
    elif unsafe == "outside":
        values["base_file"] = host.BETA_COMPOSE
    else:
        values["seccomp_file"] = stage / "../../../foreign-seccomp.json"
    with pytest.raises(PreflightError, match="exact verified Boca stage"):
        host._browser_compose_model(
            IMAGE,
            ORIGIN,
            OWNER,
            BROWSER_IMAGE,
            ATTEMPT,
            **values,
        )


def test_kernel_effective_seccomp_json_not_path_or_permissive_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = b'{ "defaultAction": "SCMP_ACT_ERRNO", "comment": "keep space in text" }\n'
    monkeypatch.setattr(host, "_browser_root_file", lambda *args, **kwargs: profile)
    reviewed_sha = hashlib.sha256(profile).hexdigest()
    compact = 'seccomp={"defaultAction":"SCMP_ACT_ERRNO","comment":"keep space in text"}'
    host._browser_effective_seccomp_options(["no-new-privileges:true", compact], reviewed_sha)
    for invalid in (
        ["no-new-privileges:true", "seccomp=/srv/boca-socios/seccomp_profile.json"],
        ["no-new-privileges:true", compact.replace("ERRNO", "ALLOW")],
        ["no-new-privileges:true", compact.replace("keep space", "keepspace")],
        ["seccomp=" + compact, "no-new-privileges:true"],
        ["no-new-privileges:true", compact, "apparmor=unconfined"],
        [],
    ):
        with pytest.raises(PreflightError):
            host._browser_effective_seccomp_options(invalid, reviewed_sha)
    duplicate_profile = b'{"defaultAction":"SCMP_ACT_ERRNO","defaultAction":"SCMP_ACT_ALLOW"}'
    monkeypatch.setattr(host, "_browser_root_file", lambda *args, **kwargs: duplicate_profile)
    with pytest.raises(PreflightError, match="invalid"):
        host._browser_effective_seccomp_options(
            ["no-new-privileges:true", compact], hashlib.sha256(duplicate_profile).hexdigest()
        )


def test_effective_seccomp_rechecks_reviewed_sha_after_staged_verify_and_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-place same-length profile swap cannot be blessed by inspect postflight."""
    base = b"reviewed base compose"
    overlay = b"reviewed browser compose"
    seccomp = (
        b'{"defaultAction":"SCMP_ACT_ERRNO","archMap":[{}],'
        b'"syscalls":[{"names":["read"],"action":"SCMP_ACT_ALLOW"}]}'
    )
    altered = seccomp.replace(b"SCMP_ACT_ERRNO", b"SCMP_ACT_ALLOW", 1)
    assert len(altered) == len(seccomp) and altered != seccomp
    reviewed_sha = hashlib.sha256(seccomp).hexdigest()
    files = {
        host.BETA_COMPOSE.name: base,
        host.BROWSER_COMPOSE.name: overlay,
        host.BROWSER_SECCOMP.name: seccomp,
    }
    monkeypatch.setattr(host, "_browser_root_entries", lambda *args: None)
    monkeypatch.setattr(host, "_browser_root_file", lambda name, **kwargs: files[name])
    host._browser_verify_staged(
        hashlib.sha256(base).hexdigest(),
        hashlib.sha256(overlay).hexdigest(),
        reviewed_sha,
    )

    # The staging root retained its path/UID/mode; only the file bytes changed.
    files[host.BROWSER_SECCOMP.name] = altered
    record = worker_record()
    record["HostConfig"]["SecurityOpt"] = [  # type: ignore[index]
        "no-new-privileges:true",
        "seccomp=" + altered.decode("utf-8"),
    ]
    monkeypatch.setattr(host, "_browser_inspect_record", lambda container: record)
    monkeypatch.setattr(host, "_browser_worker_probe", lambda container: None)
    with pytest.raises(
        PreflightError, match="effective seccomp file differs from reviewed SHA-256"
    ):
        host._browser_worker_postflight(WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, reviewed_sha)


@pytest.mark.parametrize("kind", ["fifo", "symlink", "regular"])
def test_browser_file_open_cannot_follow_symlink_or_block_on_fifo(
    tmp_path: Path, kind: str
) -> None:
    """The real os.open O_NONBLOCK/O_NOFOLLOW must precede type/UID checks.

    A bounded child proves FIFO rejection cannot hang even on hosts where a
    malicious file replaces the marker. The UID substitution ONLY changes
    stat metadata inside the disposable child; no host directory is opened.
    """
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    path = root / "browser-ipc-attempt.json"
    if kind == "fifo":
        os.mkfifo(path, mode=0o600)
    elif kind == "symlink":
        path.symlink_to(tmp_path / "foreign-target")
    else:
        path.write_text('{"synthetic":true}', encoding="ascii")
        path.chmod(0o600)
    script = f"""
import os
from pathlib import Path
from types import SimpleNamespace
from boca_socios import host_first_deploy as host
host.ROOT = Path({str(root)!r})
host.BROWSER_MARKER = host.ROOT / 'browser-ipc-attempt.json'
host._safe_dir = lambda p: True
native_fstat = os.fstat
def proof(fd):
    s = native_fstat(fd)
    return SimpleNamespace(st_mode=s.st_mode, st_uid=10001, st_gid=10001,
        st_nlink=s.st_nlink, st_size=s.st_size, st_dev=s.st_dev, st_ino=s.st_ino,
        st_mtime_ns=s.st_mtime_ns, st_ctime_ns=s.st_ctime_ns)
host.os.fstat = proof
try:
    raw = host._browser_root_file('browser-ipc-attempt.json', max_size=2048)
except host.PreflightError:
    print('NO_GO')
else:
    print('READ:' + raw.decode('ascii'))
"""
    outcome = subprocess.run(  # noqa: S603 - fixed local venv Python, no shell/network
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert outcome.stdout.strip() == ('READ:{"synthetic":true}' if kind == "regular" else "NO_GO")


def test_browser_preflight_stage_writes_marker_after_new_only_capacity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    capacity = SimpleNamespace(stage_free_bytes=8 * 1024**3, docker_free_bytes=8 * 1024**3)

    def inventory() -> tuple[int, float, int, object]:
        events.append("inventory+capacity")
        return 1600000, 2.0, 300, capacity

    monkeypatch.setattr(host, "_browser_preflight_inventory", inventory)
    monkeypatch.setattr(host, "_browser_image_absent", lambda image, sha: image != IMAGE)
    monkeypatch.setattr(
        host,
        "_browser_write_marker",
        lambda value: events.append("marker") or captured.update(value),
    )
    captured: dict[str, object] = {}
    host._browser_stage(IMAGE, SOURCE, BETA_SHA, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA, ATTEMPT)
    assert events == ["inventory+capacity", "marker"]
    assert captured["controller_image_absent"] is False
    assert captured["browser_image_absent"] is True
    assert captured["bridge_absent"] is True and captured["ipc_volume_absent"] is True
    assert "BOCA_BROWSER_STAGE_PASS" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("memory_kib", "cpu", "current", "maximum", "accepted"),
    [
        (1536 * 1024, 1.75, "100", "356", True),
        (1536 * 1024 - 1, 1.75, "100", "356", True),
        (1536 * 1024, 1.74, "100", "356", True),
        (1536 * 1024, 1.75, "100", "355", True),
        (1536 * 1024, 1.75, "100", "max", False),
        (1536 * 1024, 1.75, "100", "1not-number", False),
    ],
)
def test_post_pull_metadata_is_observed_without_unbenchmarked_reserve(
    monkeypatch: pytest.MonkeyPatch,
    memory_kib: int,
    cpu: float,
    current: str,
    maximum: str,
    accepted: bool,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _, **kwargs: None)
    monkeypatch.setattr(
        host,
        "_cpu_structural_capacity",
        lambda: host.CpuCapacity(2, 2, Fraction(str(cpu)), "materialized"),
    )
    monkeypatch.setattr(host.os, "getloadavg", lambda: (64.0, 0.0, 0.0))
    original_read = Path.read_text

    def read(self: Path, *args: object, **kwargs: object) -> str:
        if str(self) == "/proc/meminfo":
            return f"MemAvailable: {memory_kib} kB\n"
        if str(self).endswith("/pids.current"):
            return current
        if str(self).endswith("/pids.max"):
            return maximum
        return original_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", read)
    if accepted:
        assert host._browser_capacity()[:3] == (memory_kib, cpu, int(maximum) - int(current))
    else:
        with pytest.raises(PreflightError):
            host._browser_capacity()


def test_browser_inventory_rejects_foreign_container_volume_and_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "ids": set(),
        "names": set(),
        "labels": set(),
        "volumes": {host.OWNER_VOLUME},
        "networks": {"bridge", "host", "none"},
        "boca_volumes": {host.OWNER_VOLUME},
        "boca_networks": set(),
    }

    def run(*args: str) -> str:
        if args[:4] == ("docker", "ps", "-a", "-q"):
            if "name=^/boca-socios-" in args:
                return "\n".join(state["names"])
            if f"label=com.docker.compose.project={host.PROJECT}" in args:
                return "\n".join(state["labels"])
            return "\n".join(state["ids"])
        if args[:4] == ("docker", "volume", "ls", "-q"):
            return "\n".join(state["volumes"])
        if args[:3] == ("docker", "network", "ls"):
            return "\n".join(state["networks"])
        raise AssertionError(f"unreviewed Docker command: {args}")

    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(
        host,
        "_names",
        lambda kind, label: state["boca_volumes"] if kind == "volume" else state["boca_networks"],
    )
    host._browser_inventory(containers=set(), volumes={host.OWNER_VOLUME}, bridges=set())
    state["ids"] = {"1" * 64}
    with pytest.raises(PreflightError):
        host._browser_inventory(containers=set(), volumes={host.OWNER_VOLUME}, bridges=set())
    state["ids"] = set()
    state["volumes"] = {host.OWNER_VOLUME, "other_app_private"}
    with pytest.raises(PreflightError):
        host._browser_inventory(containers=set(), volumes={host.OWNER_VOLUME}, bridges=set())
    state["volumes"] = {host.OWNER_VOLUME}
    state["networks"].add("other_app_network")
    with pytest.raises(PreflightError):
        host._browser_inventory(containers=set(), volumes={host.OWNER_VOLUME}, bridges=set())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uid", 10001),
        ("gid", 0),
        ("cpu_quota", 50000),
        ("memory_bytes", 268435456),
        ("pids_limit", 256),
        ("seccomp", 0),
        ("filters", 0),
        ("no_new_privs", 0),
        ("interfaces", ["lo", "eth0"]),
    ],
)
def test_worker_kernel_probe_must_prove_effective_isolation(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    receipt: dict[str, object] = {
        "uid": 10002,
        "gid": 10002,
        "cpu_quota": 100000,
        "cpu_period": 100000,
        "memory_bytes": 805306368,
        "pids_limit": 128,
        "seccomp": 2,
        "filters": 1,
        "no_new_privs": 1,
        "interfaces": ["lo"],
    }
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: json.dumps(receipt))
    host._browser_worker_probe(WORKER_ID)
    receipt[field] = value
    with pytest.raises(PreflightError):
        host._browser_worker_probe(WORKER_ID)


def worker_record() -> dict[str, object]:
    return {
        "Id": WORKER_ID,
        "Name": "/boca-socios-browser-worker-1",
        "RestartCount": 0,
        "State": {"Running": True, "Restarting": False, "Health": {"Status": "healthy"}},
        "Config": {
            "Image": BROWSER_IMAGE,
            "User": "10002:10002",
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": "browser-worker",
                "boca.socios.browser-ipc-attempt": ATTEMPT,
                "org.opencontainers.image.revision": SOURCE,
            },
            "Cmd": ["python", "-m", "boca_socios.browser.ipc_worker"],
            "Entrypoint": None,
            "ExposedPorts": None,
            "Env": [
                "BOCA_ENVIRONMENT=staging",
                "BOCA_RUNTIME_MODE=simulation",
                "BOCA_ENGINE_MODE=off",
                "BOCA_OBSERVER_STOP=1",
                "PATH=/app/.venv/bin",
            ],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PublishAllPorts": False,
            "Init": True,
            "NetworkMode": "none",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "NanoCpus": 1_000_000_000,
            "Memory": 805_306_368,
            "PidsLimit": 128,
            "ShmSize": 67_108_864,
            "CapDrop": ["ALL"],
            "CapAdd": ["SYS_CHROOT"],
            "SecurityOpt": ["no-new-privileges:true", 'seccomp={"reviewed":true}'],
            "PortBindings": {},
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108 - container tmpfs
                "/home/boca-browser": "rw,noexec,nosuid,size=16m",
            },
        },
        "NetworkSettings": {
            "Ports": {},
            "Networks": {"none": {"IPAddress": "", "GlobalIPv6Address": ""}},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Driver": "local",
                "Name": host.BROWSER_IPC_VOLUME,
                "Destination": "/run/boca-browser-ipc",
                "RW": True,
            }
        ],
    }


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("Config", "User", "0:0"),
        ("Config", "Cmd", ["bash"]),
        ("Config", "ExposedPorts", {"80/tcp": {}}),
        ("HostConfig", "NetworkMode", "bridge"),
        ("HostConfig", "IpcMode", "host"),
        ("HostConfig", "CgroupnsMode", "host"),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "NanoCpus", 2_000_000_000),
        ("HostConfig", "Memory", 2_000_000_000),
        ("HostConfig", "PidsLimit", 256),
        ("HostConfig", "PortBindings", {"80/tcp": [{"HostIp": "0.0.0.0"}]}),  # noqa: S104 - forbidden fixture
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "RestartPolicy", {"Name": "always", "MaximumRetryCount": 1}),
        ("NetworkSettings", "Networks", {"boca_private": {}}),
    ],
)
def test_worker_postflight_rejects_privilege_network_or_restart_drift(
    monkeypatch: pytest.MonkeyPatch, section: str, field: str, value: object
) -> None:
    record = worker_record()
    monkeypatch.setattr(host, "_browser_inspect_record", lambda container: record)
    monkeypatch.setattr(host, "_browser_effective_seccomp_options", lambda *args: None)
    monkeypatch.setattr(host, "_browser_worker_probe", lambda _: None)
    host._browser_worker_postflight(WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA)
    record[section][field] = value  # type: ignore[index]
    with pytest.raises(PreflightError):
        host._browser_worker_postflight(WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA)


def controller_record() -> dict[str, object]:
    return {
        "Id": CONTROLLER_ID,
        "Name": "/boca-socios-controller-1",
        "RestartCount": 0,
        "State": {"Running": True, "Restarting": False, "Health": {"Status": "healthy"}},
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": "controller",
                "boca.socios.browser-ipc-attempt": ATTEMPT,
                "org.opencontainers.image.revision": SOURCE,
            },
            "Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
            "Entrypoint": None,
            "Env": [
                "BOCA_ENVIRONMENT=staging",
                "BOCA_RUNTIME_MODE=simulation",
                "BOCA_ENGINE_MODE=off",
                "BOCA_BROWSER_BACKEND=ipc",
                "BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only",
                f"BOCA_PANEL_ORIGIN={ORIGIN}",
                f"BOCA_OWNER_SUBJECT={OWNER}",
                "BOCA_DB_PATH=/data/boca.sqlite3",
                "BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key",
                "BOCA_PASSKEY_CREDENTIAL_ID_FILE=/run/owner/credential_id",
                "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE=/run/owner/public_key.der",
                "BOCA_BIND_HOST=0.0.0.0",  # noqa: S104 - Boca private bridge only
                "BOCA_BIND_PORT=8443",
                "BOCA_HEALTH_MODE=beta",
            ],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PublishAllPorts": False,
            "Init": True,
            "NetworkMode": host.BROWSER_BRIDGE,
            "NanoCpus": 500_000_000,
            "Memory": 268_435_456,
            "PidsLimit": 64,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges:true"],
            "CgroupnsMode": "private",
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},  # noqa: S108 - container tmpfs
            "PortBindings": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
        },
        "NetworkSettings": {
            "Ports": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            "Networks": {host.BROWSER_BRIDGE: {"NetworkID": "1" * 64}},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Driver": "local",
                "Name": source,
                "Destination": target,
                "RW": writable,
            }
            for source, target, writable in (
                (host.DATA_VOLUME, "/data", True),
                (host.KEY_VOLUME, "/run/secrets", False),
                (host.OWNER_VOLUME, "/run/owner", False),
                (host.BROWSER_IPC_VOLUME, "/run/boca-browser-ipc", False),
            )
        ],
    }


@pytest.mark.parametrize(
    "replacement",
    [
        [],
        ["BOCA_TELEGRAM_PAIRING_STAGE_MODE=off"],
        ["BOCA_TELEGRAM_PAIRING_STAGE_MODE="],
        ["BOCA_TELEGRAM_PAIRING_STAGE_MODE=unexpected"],
        ["BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only "],
        ["BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only"] * 2,
        ["BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only", "BOCA_TELEGRAM_PAIRING_STAGE_MODE=off"],
    ],
)
def test_controller_postflight_requires_encrypted_stage(
    monkeypatch: pytest.MonkeyPatch, replacement: list[str]
) -> None:
    record = controller_record()
    record["State"] = {"Running": False, "Restarting": False}
    networks = record["NetworkSettings"]
    assert isinstance(networks, dict)
    networks["Ports"] = {}
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)

    host._browser_controller_postflight(
        CONTROLLER_ID, IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER, running=False
    )
    config = record["Config"]
    assert isinstance(config, dict)
    env = config["Env"]
    assert isinstance(env, list)
    config["Env"] = [
        item for item in env if not item.startswith("BOCA_TELEGRAM_PAIRING_STAGE_MODE=")
    ] + replacement
    with pytest.raises(PreflightError):
        host._browser_controller_postflight(
            CONTROLLER_ID, IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER, running=False
        )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("Config", "User", "0:0"),
        ("Config", "Cmd", ["sh"]),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "NanoCpus", 1_000_000_000),
        ("HostConfig", "PortBindings", {}),
        ("HostConfig", "RestartPolicy", {"Name": "unless-stopped", "MaximumRetryCount": 0}),
        ("NetworkSettings", "Networks", {"other": {}}),
    ],
)
def test_controller_postflight_rejects_port_mount_or_no_retry_drift(
    monkeypatch: pytest.MonkeyPatch, section: str, field: str, value: object
) -> None:
    record = controller_record()
    monkeypatch.setattr(host, "_browser_inspect_record", lambda container: record)
    monkeypatch.setattr(host, "_validate_boca_network", lambda *args: None)
    monkeypatch.setattr(
        host, "_cgroup_limits", lambda _: host.CgroupLimits(50000, 100000, 268435456, 64)
    )
    host._browser_controller_postflight(CONTROLLER_ID, IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER)
    record[section][field] = value  # type: ignore[index]
    with pytest.raises(PreflightError):
        host._browser_controller_postflight(CONTROLLER_ID, IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER)


@pytest.mark.parametrize(
    ("marker_flip_at", "flipped_flag"),
    [
        (0, ""),
        (2, "controller_image_absent"),
        (2, "browser_image_absent"),
        (3, "controller_image_absent"),
        (4, "browser_image_absent"),
    ],
)
def test_browser_apply_orders_worker_socket_before_keys_and_controller(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    marker_flip_at: int,
    flipped_flag: str,
) -> None:
    events: list[str] = []
    capacity = SimpleNamespace(stage_free_bytes=8 * 1024**3, docker_free_bytes=8 * 1024**3)
    monkeypatch.setattr(host, "_browser_engine_version", lambda: None)
    read_count = 0

    def read_marker(*args: object) -> dict[str, object]:
        nonlocal read_count
        read_count += 1
        events.append("marker")
        result = marker()
        if read_count == marker_flip_at:
            result[flipped_flag] = False
        return result

    monkeypatch.setattr(host, "_browser_read_marker", read_marker)
    monkeypatch.setattr(host, "_browser_verify_staged", lambda *args: events.append("sha"))
    monkeypatch.setattr(
        host, "_browser_staged_inventory", lambda **kwargs: events.append("inventory")
    )
    monkeypatch.setattr(
        host, "_browser_inventory", lambda **kwargs: events.append("final-inventory")
    )
    monkeypatch.setattr(host, "_browser_port_free", lambda: events.append("port"))

    capacity_floors: list[int] = []

    def measured_capacity(
        *, min_free_bytes: int = host.PREFLIGHT_STORAGE_MIN_BYTES
    ) -> tuple[int, float, int, object]:
        events.append("capacity")
        capacity_floors.append(min_free_bytes)
        return 1600000, 2.0, 300, capacity

    monkeypatch.setattr(host, "_browser_capacity", measured_capacity)
    monkeypatch.setattr(host, "_browser_image_absent", lambda image, sha: True)
    monkeypatch.setattr(
        host, "_browser_compose_model", lambda *args: events.append("config") or "{}"
    )
    monkeypatch.setattr(host, "_browser_pull_both", lambda *args: events.append("pull-both"))
    monkeypatch.setattr(
        host, "_browser_create_ipc_volume", lambda *args: events.append("ipc-create")
    )
    monkeypatch.setattr(
        host,
        "_browser_service_id",
        lambda name, *args: WORKER_ID if name == "browser-worker" else CONTROLLER_ID,
    )
    monkeypatch.setattr(host, "_browser_worker_network_inventory", lambda: set())
    monkeypatch.setattr(host, "_browser_validate_ipc_volume", lambda *args: None)
    monkeypatch.setattr(
        host, "_browser_worker_postflight", lambda *args: events.append("worker-proof")
    )
    monkeypatch.setattr(
        host, "_browser_synthetic_socket_smoke", lambda *args: events.append("socket-proof")
    )
    monkeypatch.setattr(
        host,
        "_beta_check_container",
        lambda image, origin, owner, operation: ("docker", "run", operation),
    )
    monkeypatch.setattr(host, "_beta_check_receipt", lambda *args: None)
    monkeypatch.setattr(host, "_browser_create_key", lambda *args: events.append("key-create"))
    monkeypatch.setattr(
        host,
        "_browser_named_probe",
        lambda phase_name, attempt, args: events.append(phase_name) or "",
    )
    monkeypatch.setattr(host, "_validate_key_volume", lambda: None)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_validate_data_volume", lambda: None)
    monkeypatch.setattr(host, "_beta_init_container", lambda image: ("docker", "run", "init-beta"))
    monkeypatch.setattr(
        host, "_browser_controller_postflight", lambda *args: events.append("controller-proof")
    )
    monkeypatch.setattr(host, "_beta_loopback_health", lambda *args: events.append("loopback"))
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda *args, **kwargs: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: capacity)

    def run(*args: str, **kwargs: object) -> str:
        if "up" in args:
            service = args[-1]
            assert service in {"browser-worker", "controller"}
            assert "--no-deps" in args and "--no-build" in args and "--wait" in args
            events.append(f"up-{service}")
            return ""
        if args[:3] == ("docker", "volume", "create"):
            events.append("data-create")
            return host.DATA_VOLUME
        raise AssertionError(f"unreviewed Docker call {args}")

    monkeypatch.setattr(host, "_run", run)
    if marker_flip_at:
        with pytest.raises(PreflightError, match="pre-attempt inventory marker changed"):
            host._browser_apply(
                IMAGE,
                SOURCE,
                BETA_SHA,
                ORIGIN,
                OWNER,
                BROWSER_IMAGE,
                OVERLAY_SHA,
                SECCOMP_SHA,
                ATTEMPT,
            )
        assert read_count == marker_flip_at
        assert "BOCA_BROWSER_IPC_INSTALL_PASS" not in capsys.readouterr().out
        if marker_flip_at == 2:
            assert "pull-both" in events and "ipc-create" not in events
            assert "key-create" not in events and "up-controller" not in events
        elif marker_flip_at == 3:
            assert "data-init" in events and "up-controller" not in events
        else:
            assert "up-controller" in events and "loopback" in events
        return

    host._browser_apply(
        IMAGE, SOURCE, BETA_SHA, ORIGIN, OWNER, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA, ATTEMPT
    )
    assert read_count == 4
    assert events.count("capacity") == 2
    assert capacity_floors == [
        host.PREFLIGHT_STORAGE_MIN_BYTES,
        host.POSTINSTALL_STORAGE_MIN_BYTES,
    ]
    before, after = [index for index, item in enumerate(events) if item == "capacity"]
    assert before < events.index("pull-both") < after < events.index("ipc-create")
    assert events.index("ipc-create") < events.index("up-browser-worker")
    assert events.index("up-browser-worker") < events.index("worker-proof")
    assert events.index("worker-proof") < events.index("socket-proof")
    assert events.index("socket-proof") < events.index("key-create")
    assert events.index("key-create") < events.index("data-create")
    assert events.index("data-create") < events.index("data-init")
    assert events.index("data-init") < events.index("up-controller")
    assert events.index("up-controller") < events.index("controller-proof")
    assert events.index("controller-proof") < events.index("loopback")
    assert "BOCA_BROWSER_IPC_INSTALL_PASS" in capsys.readouterr().out


def test_browser_apply_fails_without_retry_before_key_or_controller_after_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(host, "_browser_engine_version", lambda: None)
    monkeypatch.setattr(host, "_browser_read_marker", lambda *args: marker())
    monkeypatch.setattr(host, "_browser_verify_staged", lambda *args: None)
    monkeypatch.setattr(host, "_browser_staged_inventory", lambda **kwargs: None)
    monkeypatch.setattr(host, "_browser_port_free", lambda: None)
    capacity = object()
    monkeypatch.setattr(host, "_browser_capacity", lambda **kwargs: (1600000, 2.0, 300, capacity))
    monkeypatch.setattr(host, "_browser_image_absent", lambda image, sha: True)
    monkeypatch.setattr(host, "_browser_compose_model", lambda *args: "{}")
    monkeypatch.setattr(host, "_browser_pull_both", lambda *args: called.append("pull-both"))
    monkeypatch.setattr(
        host, "_browser_create_ipc_volume", lambda *args: called.append("ipc-create")
    )
    monkeypatch.setattr(host, "_browser_service_id", lambda *args: WORKER_ID)
    monkeypatch.setattr(host, "_browser_worker_network_inventory", lambda: set())
    monkeypatch.setattr(host, "_browser_validate_ipc_volume", lambda *args: None)
    monkeypatch.setattr(
        host,
        "_browser_worker_postflight",
        lambda *args: (_ for _ in ()).throw(PreflightError("worker invalid")),
    )
    monkeypatch.setattr(host, "_storage_snapshot", lambda: capacity)
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        host, "_browser_create_key", lambda *args: pytest.fail("key created after worker failure")
    )

    def run(*args: str, **kwargs: object) -> str:
        if "up" in args:
            assert args[-1] == "browser-worker"
            called.append("up-worker")
            return ""
        raise AssertionError(f"unexpected side effect: {args}")

    monkeypatch.setattr(host, "_run", run)
    with pytest.raises(PreflightError, match="worker invalid"):
        host._browser_apply(
            IMAGE,
            SOURCE,
            BETA_SHA,
            ORIGIN,
            OWNER,
            BROWSER_IMAGE,
            OVERLAY_SHA,
            SECCOMP_SHA,
            ATTEMPT,
        )
    assert called == ["pull-both", "ipc-create", "up-worker"]


def test_postpull_capacity_failure_blocks_ipc_key_data_and_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(host, "_browser_engine_version", lambda: None)
    monkeypatch.setattr(host, "_browser_read_marker", lambda *args: marker())
    monkeypatch.setattr(host, "_browser_verify_staged", lambda *args: None)
    monkeypatch.setattr(host, "_browser_staged_inventory", lambda **kwargs: None)
    monkeypatch.setattr(host, "_browser_port_free", lambda: None)
    monkeypatch.setattr(host, "_browser_image_absent", lambda image, sha: True)
    monkeypatch.setattr(host, "_browser_compose_model", lambda *args: "{}")
    monkeypatch.setattr(host, "_browser_pull_both", lambda *args: events.append("pull-both"))
    monkeypatch.setattr(
        host, "_browser_create_ipc_volume", lambda *args: pytest.fail("IPC volume was created")
    )
    monkeypatch.setattr(host, "_browser_create_key", lambda *args: pytest.fail("key was created"))
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker side effect"))
    probes = 0

    def capacity(**kwargs: int) -> tuple[int, float, int, object]:
        nonlocal probes
        probes += 1
        events.append("capacity")
        if probes == 2:
            raise PreflightError("postpull headroom insufficient")
        return 1600000, 2.0, 300, object()

    monkeypatch.setattr(host, "_browser_capacity", capacity)
    with pytest.raises(PreflightError, match="postpull headroom insufficient"):
        host._browser_apply(
            IMAGE,
            SOURCE,
            BETA_SHA,
            ORIGIN,
            OWNER,
            BROWSER_IMAGE,
            OVERLAY_SHA,
            SECCOMP_SHA,
            ATTEMPT,
        )
    assert events == ["capacity", "pull-both", "capacity"]


@pytest.mark.parametrize(
    "phase_name",
    [
        "ipc-dir-init",
        "synthetic-ipc",
        "key-init",
        "key-verify",
        "owner-check",
        "config-check",
        "data-init",
    ],
)
def test_every_one_shot_has_deterministic_probe_name_labels_and_rm(
    monkeypatch: pytest.MonkeyPatch, phase_name: str
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        host, "_run", lambda *args, **kwargs: calls.append((args, kwargs)) or "ready"
    )
    argv = (
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--user",
        "10001:10001",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "16",
        "--memory",
        "64m",
        "--cpus",
        "0.25",
        IMAGE,
        "python",
        "-c",
        "pass",
    )
    assert host._browser_named_probe(phase_name, ATTEMPT, argv) == "ready"
    command, options = calls[0]
    assert command[:2] == ("docker", "run")
    assert command[2:4] == ("--name", f"boca-socios-browser-ipc-probe-{phase_name}-{ATTEMPT}")
    assert command[4:10] == (
        "--label",
        "com.docker.compose.project=boca-socios",
        "--label",
        f"boca.socios.browser-ipc-attempt={ATTEMPT}",
        "--label",
        f"boca.socios.browser-ipc-phase={phase_name}",
    )
    assert command[10:12] == ("--ipc=private", "--cgroupns=private")
    assert command[12:] == argv[2:]
    assert not any(value == "--pid" or value.startswith("--pid=") for value in command)
    assert "--rm" in command and "--detach" not in command
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--publish" not in command and "-p" not in command
    assert options["timeout"] == (75 if phase_name == "synthetic-ipc" else 120)


@pytest.mark.parametrize(
    ("phase_name", "attempt_id", "command"),
    [
        ("foreign-probe", ATTEMPT, ("docker", "run", "--rm")),
        ("key-init", "001", ("docker", "run", "--rm")),
        ("key-init", ATTEMPT, ("docker", "run", "--name", "foreign")),
        ("key-init", ATTEMPT, ("docker", "run", "--rm", "--label", "foreign")),
        ("key-init", ATTEMPT, ("docker", "run", "--rm", "--detach")),
        ("key-init", ATTEMPT, ("sh", "-c", "docker run")),
    ],
)
def test_one_shot_probe_rejects_unattributable_commands_before_docker(
    monkeypatch: pytest.MonkeyPatch,
    phase_name: str,
    attempt_id: str,
    command: tuple[str, ...],
) -> None:
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker was invoked"))
    with pytest.raises(PreflightError):
        host._browser_named_probe(phase_name, attempt_id, command)


def test_ipc_dir_init_and_fixed_synthetic_probe_keep_no_network_no_owner_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_browser_validate_ipc_volume", lambda _: None)

    def run(*args: str, **kwargs: object) -> str:
        commands.append(args)
        if args[:3] == ("docker", "volume", "create"):
            return host.BROWSER_IPC_VOLUME
        if "ipc-dir-init" in args[3]:
            return "BOCA_BROWSER_IPC_DIR_PASS"
        if "synthetic-ipc" in args[3]:
            return "BOCA_BROWSER_IPC_SYNTHETIC_PASS"
        raise AssertionError(f"unrecognized probe: {args}")

    monkeypatch.setattr(host, "_run", run)
    host._browser_create_ipc_volume(BROWSER_IMAGE, ATTEMPT)
    host._browser_synthetic_socket_smoke(IMAGE, ATTEMPT)
    assert len(commands) == 3
    init, synthetic = commands[1:]
    assert "--user" in init and init[init.index("--user") + 1] == "0:0"
    assert "--cap-add" in init and "CHOWN" in init and "FOWNER" in init
    assert BROWSER_IMAGE in init
    assert (
        "--mount" in init
        and "/run/boca-browser-ipc,volume-nocopy" in init[init.index("--mount") + 1]
    )
    assert "--user" in synthetic and synthetic[synthetic.index("--user") + 1] == "10001:10001"
    assert IMAGE in synthetic and "--cap-add" not in synthetic
    assert "volume-nocopy,readonly" in synthetic[synthetic.index("--mount") + 1]
    for args in (init, synthetic):
        assert "--network" in args and args[args.index("--network") + 1] == "none"
        assert not any(
            host.OWNER_VOLUME in item or host.KEY_VOLUME in item or host.DATA_VOLUME in item
            for item in args
        )
        assert "--publish" not in args and "-p" not in args
    assert "BOCA_SYNTHETIC_V1_RUN" not in synthetic[-1]  # fixed protocol stays inside client
    assert "UnixSyntheticBrowser" in synthetic[-1]


def test_new_only_key_probes_are_named_and_do_not_broaden_legacy_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_validate_key_volume", lambda: None)

    def run(*args: str, **kwargs: object) -> str:
        calls.append(args)
        return host.KEY_VOLUME if args[:3] == ("docker", "volume", "create") else "BOCA_KEY_READY"

    monkeypatch.setattr(host, "_run", run)
    host._browser_create_key(IMAGE, ATTEMPT)
    assert len(calls) == 3
    assert calls[1][3] == f"boca-socios-browser-ipc-probe-key-init-{ATTEMPT}"
    assert calls[2][3] == f"boca-socios-browser-ipc-probe-key-verify-{ATTEMPT}"
    assert "--name" not in host._key_container(IMAGE, "init")  # legacy untouched
    assert "--name" not in host._key_container(IMAGE, "verify")
    assert "--network" in calls[1] and calls[1][calls[1].index("--network") + 1] == "none"
    assert "--network" in calls[2] and calls[2][calls[2].index("--network") + 1] == "none"


@pytest.mark.parametrize(
    ("phase_name", "expected_user", "expected_mounts", "expected_caps", "expected_budget"),
    [
        ("key-init", "0:0", ("boca-socios_boca_key",), ("CHOWN",), ("16", "64m", "0.25")),
        ("key-verify", "10001:10001", ("boca-socios_boca_key",), (), ("16", "64m", "0.25")),
        ("owner-check", "10001:10001", ("boca-socios_boca_owner",), (), ("16", "64m", "0.25")),
        (
            "config-check",
            "10001:10001",
            ("boca-socios_boca_owner", "boca-socios_boca_key"),
            (),
            ("16", "64m", "0.25"),
        ),
        (
            "data-init",
            "10001:10001",
            ("boca-socios_boca_data", "boca-socios_boca_key"),
            (),
            ("64", "256m", "0.50"),
        ),
    ],
)
def test_five_legacy_based_probes_have_exact_cleanup_identity_and_resources(
    monkeypatch: pytest.MonkeyPatch,
    phase_name: str,
    expected_user: str,
    expected_mounts: tuple[str, ...],
    expected_caps: tuple[str, ...],
    expected_budget: tuple[str, str, str],
) -> None:
    """Capture genuine caller argv for C2b spec parity; never run Docker."""
    if phase_name == "key-init":
        inner = host._key_container(IMAGE, "init")
    elif phase_name == "key-verify":
        inner = host._key_container(IMAGE, "verify")
    elif phase_name == "owner-check":
        inner = host._beta_check_container(IMAGE, ORIGIN, OWNER, "check-beta-owner")
    elif phase_name == "config-check":
        inner = host._beta_check_container(IMAGE, ORIGIN, OWNER, "check-beta-config")
    else:
        inner = host._beta_init_container(IMAGE)
    captured: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: captured.append(args) or "")
    host._browser_named_probe(phase_name, ATTEMPT, inner)
    command = captured[0]
    assert command[:10] == (
        "docker",
        "run",
        "--name",
        f"boca-socios-browser-ipc-probe-{phase_name}-{ATTEMPT}",
        "--label",
        "com.docker.compose.project=boca-socios",
        "--label",
        f"boca.socios.browser-ipc-attempt={ATTEMPT}",
        "--label",
        f"boca.socios.browser-ipc-phase={phase_name}",
    )
    assert command[10:12] == ("--ipc=private", "--cgroupns=private")
    assert command[12:] == inner[2:]  # default Docker PID namespace remains private
    assert not any(value == "--pid" or value.startswith("--pid=") for value in command)
    assert "--rm" in command and "--pull" in command and "never" in command
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--user" in command and command[command.index("--user") + 1] == expected_user
    assert "--read-only" in command and "--cap-drop" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert (
        tuple(command[i + 1] for i, value in enumerate(command) if value == "--cap-add")
        == expected_caps
    )
    mounts = tuple(command[i + 1] for i, value in enumerate(command) if value == "--mount")
    actual_sources: list[str] = []
    for mount in mounts:
        matching = [name for name in expected_mounts if f"source={name}," in mount]
        assert len(matching) == 1
        actual_sources.append(matching[0])
    assert tuple(actual_sources) == expected_mounts
    assert command[command.index("--pids-limit") + 1] == expected_budget[0]
    assert command[command.index("--memory") + 1] == expected_budget[1]
    assert command[command.index("--cpus") + 1] == expected_budget[2]
    assert "--publish" not in command and "-p" not in command and "--privileged" not in command
    assert IMAGE in command
    if phase_name == "data-init":
        assert command[-3:] == ("-m", "boca_socios.runtime", "init-beta")
