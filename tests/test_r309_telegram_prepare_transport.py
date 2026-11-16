"""R309 installed selector, framed CLI, ZIP and Action boundaries without a host."""

from __future__ import annotations

import hashlib
import importlib
import io
import os
import re
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from boca_socios import host_telegram_backend as backend
from test_r309_telegram_prepare_diagnose import (
    BROWSER,
    IMAGE,
    RUN,
    SOURCE,
    WORKFLOW,
    Runtime,
)

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
OPERATION = "telegram-prepare-diagnose"
STEP = "Execute installed Telegram transaction under one protected lease"
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_protected_telegram_bundle")
memfd = importlib.import_module("boca_protected_memfd_bootstrap")


def _step(name):
    heading = f"      - name: {name}\n"
    source = FLOW.read_text()
    assert source.count(heading) == 1
    return source.split(heading)[1].split("      - name:", 1)[0]


def _shell(name):
    return textwrap.dedent(_step(name).split("        run: |\n", 1)[1])


def _enabled(name, operation):
    condition = _step(name).split("        if: ", 1)[1].splitlines()[0]
    condition = condition.replace("inputs.operation", repr(operation)).replace("always()", "True")
    condition = condition.replace("steps.boca_telegram_attempt.outputs.started", "'true'")
    condition = re.sub(r"startsWith\(([^,]+), ([^)]+)\)", r"\1.startswith(\2)", condition)
    return eval(condition.replace("&&", " and ").replace("||", " or "), {"__builtins__": {}})  # noqa: S307 - repository predicate with finite fixture inputs


def _run(command, directory, *, raw=b"", env=None):
    return subprocess.run(  # noqa: S603 - local Python/Bash only; never Docker or SSH
        command,
        input=raw,
        cwd=directory,
        env=env
        or {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "/untrusted"},
        capture_output=True,
        check=False,
        timeout=20,
    )


def _cli(*args):
    return [
        sys.executable,
        "-I",
        "-B",
        "-c",
        "import sys;sys.path.insert(0,sys.argv.pop(1));from boca_socios.host_telegram_cli import main;raise SystemExit(main())",
        str(ROOT / "src"),
        *args,
    ]


def test_d7_cli_routes_actual_diagnosis_frame_and_preserves_v1(tmp_path, monkeypatch):
    fixture = Runtime(tmp_path, monkeypatch, volume=False)
    _, frame = fixture.diagnose()
    verified = _run(_cli("verify-receipt", OPERATION, SOURCE, WORKFLOW, RUN), tmp_path, raw=frame)
    assert verified.returncode == 0 and verified.stdout == frame and not verified.stderr
    # Real UID/lease validation rejects this local workstation before Docker effects.
    rejected = _run(_cli(OPERATION, SOURCE, WORKFLOW, RUN), tmp_path)
    assert rejected.returncode == 3 and not rejected.stderr
    record = backend.verify_prepare_diagnosis(
        rejected.stdout,
        attempt_id=RUN,
        source_sha=SOURCE,
        workflow_sha=WORKFLOW,
        allow_failure=True,
    )
    assert record["state"] == "INCOMPLETE_NO_GO" and record["phase"] == "LEASE"
    assert record["helper"]["create_attempted"] is False
    for data in (
        frame + b"x",
        frame[:-1],
        b"x" * 4097,
        backend.TelegramBackendReceipt(
            "prepare", RUN, SOURCE, "PREPARED", "NOT_NEEDED"
        ).redacted_json(),
    ):
        result = _run(_cli("verify-receipt", OPERATION, SOURCE, WORKFLOW, RUN), tmp_path, raw=data)
        assert result.returncode == 2 and b"OBSERVED_NO_GO" not in result.stdout
    legacy = backend.TelegramBackendReceipt(
        "observe", RUN, SOURCE, "SCHEMA_READY", "NOT_NEEDED"
    ).redacted_json()
    unchanged = _run(
        _cli("verify-receipt", "telegram-schema-observe", SOURCE, WORKFLOW, RUN),
        tmp_path,
        raw=legacy,
    )
    assert unchanged.returncode == 0 and unchanged.stdout == b"BOCA_TELEGRAM_HOST " + legacy + b"\n"


def test_d9_workflow_installed_conditions_and_all_five_legacy_exclusions():
    source = FLOW.read_text()
    options = source.split("        options: [", 1)[1].split("]", 1)[0].split(", ")
    assert OPERATION in options
    for name in ("Prove Telegram release ancestry and build installed transaction", STEP):
        assert _enabled(name, OPERATION)
        assert _enabled(name, "telegram-schema-observe")
    legacy = (
        "Recheck current main before Telegram post-install custody",
        "Mark Telegram host attempt before starting existing Boca daemon",
        "Start only stopped existing dedicated Boca daemon",
        "Execute protected Telegram schema, custody or one-shot test",
        "Stop positively identified Boca services after Telegram custody",
    )
    for name in legacy:
        assert not _enabled(name, OPERATION), name
        assert _enabled(name, "telegram-test"), name
    assert OPERATION not in _shell(legacy[3])
    mapping = source.split("      BOCA_SOURCE_SHA: ", 1)[1].splitlines()[0]
    assert OPERATION not in mapping and mapping.endswith("|| inputs.source_sha }}")


@pytest.mark.parametrize(
    "damage", ["", "budget", "source", "incident", "failed-run", "envelope", "attempt"]
)
def test_d9_actual_admission_accepts_r_distinct_w_and_rejects_extra_inputs(tmp_path, damage):
    script = _shell("Require verified protected environment and matching main commit")
    env = {name: "" for name in re.findall(r"\bBOCA_[A-Z0-9_]+\b", script)}
    env.update(
        PATH="/usr/bin:/bin",
        BOCA_OPERATION=OPERATION,
        BOCA_SOURCE_SHA=SOURCE,
        BOCA_SERVICE="controller",
        BOCA_BUDGET="1.5cpu-1024m-192pids",
        GITHUB_SHA=WORKFLOW,
        GITHUB_RUN_ID=RUN,
        GITHUB_RUN_ATTEMPT="1",
        BOCA_IMAGE_REF=IMAGE,
        BOCA_BROWSER_IMAGE_REF=BROWSER,
        BOCA_RELEASE_RUN_ID="43704139794",
        BOCA_BETA_PANEL_ORIGIN="http://localhost:8443",
        BOCA_BETA_OWNER_SUBJECT="synthetic-owner",
    )
    for name in ("DEPLOY", "BETA", "BROWSER", "TELEGRAM"):
        env["BOCA_" + name + "_ENV_READY"] = "ready"
    key, val = {
        "budget": ("BOCA_BUDGET", "1.75cpu-1152m-224pids"),
        "source": ("BOCA_SOURCE_SHA", "bad"),
        "incident": ("BOCA_LEGACY_RELEASE_RUN_ID", "43738415332"),
        "failed-run": ("BOCA_FAILED_TELEGRAM_RUN_ID", "43738415332"),
        "envelope": ("BOCA_TELEGRAM_ENVELOPE", "synthetic"),
        "attempt": ("GITHUB_RUN_ATTEMPT", "2"),
    }.get(damage, ("PATH", "/usr/bin:/bin"))
    env[key] = val
    result = _run(["/bin/bash", "-euo", "pipefail", "-c", script], tmp_path, env=env)
    assert (result.returncode == 0) is (damage == ""), result.stderr.decode()


def test_d9_actual_result_branch_requires_remote_and_verifier_success(tmp_path, monkeypatch):
    fixture = Runtime(tmp_path, monkeypatch)
    observed, frame = fixture.diagnose()
    incomplete = backend._diagnosis_frame(
        {
            **observed,
            "state": "INCOMPLETE_NO_GO",
            "phase": "POSTFLIGHT",
            "reason": "GUARD_UNVERIFIED",
            "recommendation": "PRESERVE_REVIEW",
        }
    )
    script = _shell(STEP)
    tail = script[script.index('if [[ "$verification_rc"') :]
    # Starts at the shared verifier outcome; no network or SSH statements enter this test.
    summary = tmp_path / "summary"
    for remote, verification, data, expected in (
        (0, 0, frame, 0),
        (7, 0, frame, 1),
        (0, 2, frame, 1),
        (0, 0, b"BOCA_TELEGRAM_HOST {}\n", 1),
        (0, 0, incomplete, 1),
    ):
        result = _run(
            ["/bin/bash", "-euo", "pipefail", "-c", tail],
            tmp_path,
            env={
                "PATH": "/usr/bin:/bin",
                "BOCA_OPERATION": OPERATION,
                "remote_rc": str(remote),
                "verification_rc": str(verification),
                "verified": data.decode().rstrip("\n"),
                "GITHUB_STEP_SUMMARY": str(summary),
            },
        )
        assert result.returncode == expected
        text = summary.read_text()
        assert "OWNER_ACCEPTANCE" not in text and "PREPARED" not in text
        if remote:
            lines = text.splitlines()
            assert lines[0].startswith(
                "BOCA_TELEGRAM_PREPARE_DIAGNOSIS state=INCOMPLETE_NO_GO reason=TRANSPORT_UNVERIFIED "
            )
            label = "BOCA_TELEGRAM_BACKEND_EVIDENCE_NON_AUTHORITATIVE transport=UNVERIFIED receipt="
            assert len(lines) == 2 and lines[1].startswith(label)
            original = lines[1].removeprefix(label).encode() + b"\n"
            assert original == frame
            evidence = backend.verify_prepare_diagnosis(
                original,
                attempt_id=RUN,
                source_sha=SOURCE,
                workflow_sha=WORKFLOW,
                allow_failure=True,
            )
            assert evidence == observed
            assert evidence["helper"]["id"] == "d" * 64
            assert evidence["helper"]["retirement"] == "RETIRED"
            assert not any(line.startswith(backend.DIAGNOSIS_PREFIX.decode()) for line in lines)
        elif expected == 0:
            assert frame.decode().rstrip("\n") in text
            assert "state=OBSERVED_NO_GO" in text and "INCOMPLETE_NO_GO" not in text
        elif verification:
            assert "state=INCOMPLETE_NO_GO reason=TRANSPORT_UNVERIFIED" in text
            assert "OBSERVED_NO_GO" not in text and frame.decode().rstrip("\n") not in text
        elif data == incomplete:
            assert incomplete.decode().rstrip("\n") in text and "OBSERVED_NO_GO" not in text
        summary.unlink()


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    target = tmp_path_factory.mktemp("r309-package") / "installed.pyz"
    digest = builder.build(ROOT, target, installed=True)
    return target, target.read_bytes(), digest


def test_d9_actual_installed_zip_and_memfd_preserve_47_entry_boundary(
    package, tmp_path, monkeypatch
):
    target, raw, digest = package
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert len(archive.infolist()) == 47
        assert set(archive.namelist()) == memfd.TELEGRAM_INSTALLED_ENTRIES
        assert sum(info.file_size for info in archive.infolist()) <= 512000
    assert len(raw) <= 300000 and hashlib.sha256(raw).hexdigest() == digest
    memfd.verify(raw, digest, telegram_installed=True)
    selftest = _run([sys.executable, "-I", "-S", "-B", str(target), "selftest"], tmp_path)
    assert selftest.returncode == 0 and b"INSTALLED_CLOSURE_READY" in selftest.stdout
    fixture = Runtime(tmp_path, monkeypatch, volume=False)
    _, frame = fixture.diagnose()
    verified = _run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(target),
            "verify-receipt",
            OPERATION,
            SOURCE,
            WORKFLOW,
            RUN,
        ],
        tmp_path,
        raw=frame,
    )
    assert verified.returncode == 0 and verified.stdout == frame and not verified.stderr
    executed = _run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(ROOT / "scripts/boca_protected_memfd_bootstrap.py"),
            digest,
            OPERATION,
            SOURCE,
            WORKFLOW,
            RUN,
        ],
        tmp_path,
        raw=raw,
    )
    assert executed.returncode == 3 and not executed.stderr
    value = backend.verify_prepare_diagnosis(
        executed.stdout,
        attempt_id=RUN,
        source_sha=SOURCE,
        workflow_sha=WORKFLOW,
        allow_failure=True,
    )
    assert value["phase"] == "LEASE" and value["helper"]["create_attempted"] is False


@pytest.mark.parametrize(
    "damage", ["digest", "source", "workflow", "run", "missing", "extra", "foreign-mode"]
)
def test_d9_memfd_rejects_damaged_installed_coordinates(package, tmp_path, damage):
    _, raw, digest = package
    args = [digest, OPERATION, SOURCE, WORKFLOW, RUN]
    if damage in {"digest", "source", "workflow", "run"}:
        args[{"digest": 0, "source": 2, "workflow": 3, "run": 4}[damage]] = "bad"
    elif damage == "missing":
        args.pop()
    elif damage == "extra":
        args.append("untrusted")
    else:
        args[1] = "boca-telegram-incident-observe"
    result = _run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(ROOT / "scripts/boca_protected_memfd_bootstrap.py"),
            *args,
        ],
        tmp_path,
        raw=raw,
    )
    assert result.returncode == 1 and not result.stdout
    assert result.stderr == b"BOCA_BUNDLE state=NO_GO reason=hash_or_host_runtime\n"


def _boundary_zip(total, *, oversized_entry=False):
    names = sorted(memfd.TELEGRAM_INSTALLED_ENTRIES)
    sizes = dict.fromkeys(names, 1)
    sizes[names[0]] = 450001 if oversized_entry else 400000
    sizes[names[1]] += total - sum(sizes.values())
    assert min(sizes.values()) > 0
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, size in sizes.items():
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, b" " * size)
    return output.getvalue()


def test_d9_adenda_installed_aggregate_and_individual_bounds_are_distinct():
    accepted = _boundary_zip(512000)
    memfd.verify(accepted, hashlib.sha256(accepted).hexdigest(), telegram_installed=True)
    for raw in (_boundary_zip(512001), _boundary_zip(450047, oversized_entry=True)):
        with pytest.raises(ValueError):
            memfd.verify(raw, hashlib.sha256(raw).hexdigest(), telegram_installed=True)
    assert builder.MAX_SOURCE_BYTES == 450000 and builder.MAX_ARCHIVE_BYTES == 300000
    assert builder.MAX_INSTALLED_SOURCE_BYTES == memfd.TELEGRAM_MAX_UNCOMPRESSED == 512000
    assert memfd.TELEGRAM_MAX_ZIP == 300000


def test_d9_builder_adenda_accepts_exact_aggregate_and_rejects_one_more(package, tmp_path):
    _, packed, _ = package
    with zipfile.ZipFile(io.BytesIO(packed)) as archive:
        current = sum(info.file_size for info in archive.infolist())
    repository = tmp_path / "source"
    paths = set(builder.INSTALLED_SOURCES) | {
        "src/" + builder.NETWORK_PROJECTION_NAME,
        "src/" + builder.INSTALLATION_PROJECTION_NAME,
    }
    for relative in paths:
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    destination = repository / "src/boca_socios/host_telegram_cli.py"
    original = destination.read_bytes()
    prefix, suffix = b'\nR309_BOUNDARY_PADDING = "', b'"\n'
    padding = 512000 - current - len(prefix) - len(suffix)
    assert padding > 0
    destination.write_bytes(original + prefix + b"x" * padding + suffix)
    target = tmp_path / "exact.pyz"
    builder.build(repository, target, installed=True)
    with zipfile.ZipFile(target) as archive:
        assert sum(info.file_size for info in archive.infolist()) == 512000
        assert max(info.file_size for info in archive.infolist()) <= 450000
    destination.write_bytes(original + prefix + b"x" * (padding + 1) + suffix)
    with pytest.raises(ValueError, match="source closure exceeds bound"):
        builder.build(repository, tmp_path / "oversize.pyz", installed=True)
    # The individual source boundary still rejects a file even before projection/aggregation.
    destination.write_bytes(b" " * 450001)
    with pytest.raises(ValueError, match="source missing or oversized"):
        builder.build(repository, tmp_path / "individual.pyz", installed=True)


@pytest.mark.parametrize("release_fault", [False, True])
def test_d7_cli_owns_one_real_lease_and_retains_retired_cid_on_release_error(
    tmp_path, monkeypatch, release_fault
):
    import signal
    from types import SimpleNamespace

    from boca_socios import host_telegram_cli as cli
    from boca_socios import host_telegram_installed_context as context_module

    fixture = Runtime(tmp_path, monkeypatch)
    captured = io.BytesIO()
    original_close = os.close

    def close(descriptor):
        original_close(descriptor)
        if (
            release_fault
            and fixture.fs.lease_descriptors
            and descriptor == fixture.fs.lease_descriptors[0][1]
        ):
            raise OSError("synthetic lease close uncertainty")

    with fixture.boundary() as scoped:
        # Substitute only the external Docker I/O protocol; all context, lease,
        # profile, codec and lifecycle validators remain the real implementations.
        scoped.setattr(context_module, "TelegramProductionDockerIO", lambda: fixture.reader)
        scoped.setattr(sys, "stdout", SimpleNamespace(buffer=captured))
        scoped.setattr(signal, "signal", lambda *args: None)
        scoped.setattr(os, "close", close)
        result = cli.main([OPERATION, SOURCE, WORKFLOW, RUN])
    if release_fault:
        original_close(fixture.fs.lease_descriptors[0][0])
    assert len(fixture.fs.lease_descriptors) == 1
    value = backend.verify_prepare_diagnosis(
        captured.getvalue(),
        attempt_id=RUN,
        source_sha=SOURCE,
        workflow_sha=WORKFLOW,
        allow_failure=True,
    )
    assert result == (3 if release_fault else 0)
    assert value["phase"] == ("LEASE" if release_fault else "COMPLETE")
    assert value["state"] == ("INCOMPLETE_NO_GO" if release_fault else "OBSERVED_NO_GO")
    assert value["helper"]["id"] == "d" * 64 and value["helper"]["retirement"] == "RETIRED"
    assert fixture.events == ["PUBLIC_A", "CREATE", "START_HELPER", "REMOVE_HELPER", "PUBLIC_B"]
