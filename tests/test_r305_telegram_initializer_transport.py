"""R305's exact ZIP, memfd entrypoint and protected shell fail closed offline."""

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

from test_r305_telegram_initializer_recovery import RUN, WORKFLOW, accepted, frame

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
OPERATION = "boca-telegram-initializer-recover"
STEP = "Recover fixed Telegram initializer once"
MODULE = "boca_socios/host_telegram_initializer_recovery.py"
TRANSPORT_NO_GO = (
    b"BOCA_TELEGRAM_INITIALIZER_RECOVERY_V1 state=NO_GO phase=TRANSPORT reason=UNVERIFIED\n"
)
BLANKS = (
    "BOCA_SOURCE_SHA_SUBMITTED",
    "BOCA_PROTECTED_ACTION_CONTEXT",
    "BOCA_IMAGE_REF",
    "BOCA_BROWSER_IMAGE_REF",
    "BOCA_RELEASE_RUN_ID",
    "BOCA_LEGACY_SOURCE_SHA",
    "BOCA_LEGACY_IMAGE_REF",
    "BOCA_LEGACY_RELEASE_RUN_ID",
    "BOCA_LEGACY_CONTROLLER_ID",
    "BOCA_SITE_ENVELOPE",
    "BOCA_TELEGRAM_ENVELOPE",
    "BOCA_OWNER_ENVELOPE",
    "BOCA_OWNER_CAPABILITY_SHA256",
    "BOCA_FAILED_TELEGRAM_RUN_ID",
    "BOCA_OFFICIAL_CONTROLLER_ID",
    "BOCA_OFFICIAL_NEWS_RUN_ID",
    "BOCA_OFFICIAL_NEWS_SOURCE_SHA",
    "BOCA_OFFICIAL_NEWS_ARTIFACT_ID",
    "BOCA_OFFICIAL_NEWS_ZIP_SHA256",
    "BOCA_OFFICIAL_NEWS_JSONL_SHA256",
    "BOCA_OFFICIAL_NEWS_HTML_SHA256",
    "BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC",
)
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_protected_boca_bundle")
bootstrap = importlib.import_module("boca_protected_memfd_bootstrap")


def _step(name):
    source = FLOW.read_text()
    heading = f"      - name: {name}\n"
    assert source.count(heading) == 1, f"missing protected step: {name}"
    return source.split(heading, 1)[1].split("      - name:", 1)[0]


def _shell(name):
    return textwrap.dedent(_step(name).split("        run: |\n", 1)[1])


def _no_go():
    receipt = accepted()
    receipt.update(
        state="NO_GO",
        phase="INPUT",
        initialization="NOT_ATTEMPTED",
        retirement="NOT_ATTEMPTED",
        pair_state="UNVERIFIED",
        sender_state="UNVERIFIED",
        disk_before=None,
        disk_after=None,
    )
    return frame(receipt)


def _run(command, directory, *, raw=b"", env=None):
    return subprocess.run(  # noqa: S603 - reviewed local programs; synthetic I/O, never SSH
        command,
        input=raw,
        cwd=directory,
        env=env
        or {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": "/nonexistent-untrusted-checkout",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        check=False,
        timeout=10,
    )


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    directory = tmp_path_factory.mktemp("r305-transport")
    bundle = directory / "initializer.pyz"
    result = _run(
        [
            sys.executable,
            str(ROOT / "scripts/build_protected_boca_bundle.py"),
            "--telegram-initializer-recover",
            str(ROOT),
            str(bundle),
        ],
        directory,
    )
    assert result.returncode == 0, result.stderr.decode()
    raw = bundle.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert result.stdout == f"BOCA_PROTECTED_BUNDLE sha256={digest}\n".encode()
    return bundle, raw, digest


def test_initializer_mode_has_own_bounds_and_exact_closure():
    assert builder.TELEGRAM_INITIALIZER_MAX_SOURCE_BYTES == 900000
    assert builder.TELEGRAM_INITIALIZER_MAX_ARCHIVE_BYTES == 320000
    assert bootstrap.TELEGRAM_INITIALIZER_MAX_UNCOMPRESSED == 900000
    assert bootstrap.TELEGRAM_INITIALIZER_MAX_ZIP == 320000
    assert bootstrap.TELEGRAM_INITIALIZER_ENTRIES == bootstrap.TELEGRAM_INCIDENT_ENTRIES | {MODULE}
    assert len(bootstrap.TELEGRAM_INITIALIZER_ENTRIES) == 30


@pytest.mark.parametrize("other", ["telegram_incident_observe", "binding_observe", "worker_w1"])
def test_initializer_modes_are_exclusive_before_writes(other, tmp_path):
    with pytest.raises(ValueError, match="exclusive"):
        builder.build(
            ROOT, tmp_path / "invalid.pyz", telegram_initializer_recover=True, **{other: True}
        )
    with pytest.raises(ValueError, match="exclusive"):
        bootstrap.verify(b"", "0" * 64, telegram_initializer_recover=True, **{other: True})
    assert not (tmp_path / "invalid.pyz").exists()


@pytest.mark.parametrize("damage", ["total", "module"])
def test_initializer_source_cap_never_inherits_cutover_compaction(damage, tmp_path):
    for relative in builder.TELEGRAM_INITIALIZER_SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pass\n")
    relative, size, error = (
        ("src/boca_socios/host_boca_cleanup.py", 899999, "total exceeds")
        if damage == "total"
        else ("src/" + MODULE, 24001, "initializer source exceeds")
    )
    (tmp_path / relative).write_bytes(b"#" + b" " * (size - 2) + b"\n")
    with pytest.raises(ValueError, match=error):
        builder.build(tmp_path, tmp_path / "invalid.pyz", telegram_initializer_recover=True)
    assert not (tmp_path / "invalid.pyz").exists()


def test_real_zip_has_exact_reviewed_bytes_and_independent_allowlist(package):
    _, raw, digest = package
    bootstrap.verify(raw, digest, telegram_initializer_recover=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == bootstrap.TELEGRAM_INITIALIZER_ENTRIES
        assert len(archive.infolist()) == 30
        assert archive.read(MODULE) == (ROOT / "src" / MODULE).read_bytes()
        assert len(archive.read(MODULE)) <= 24000
        assert sum(item.file_size for item in archive.infolist()) <= 900000
        assert len(raw) <= 320000
    for other in ("telegram_incident_observe", "binding_observe", "telegram_installed"):
        with pytest.raises(ValueError, match="allowlist"):
            bootstrap.verify(raw, digest, **{other: True})
    with pytest.raises(ValueError, match="SHA/size"):
        bootstrap.verify(raw, "0" * 64, telegram_initializer_recover=True)


@pytest.mark.parametrize("damage", ["missing", "extra", "source_size", "zip_size"])
def test_bootstrap_checks_real_archive_entry_and_byte_bounds(package, damage):
    _, original, _ = package
    target = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(target, "w") as output:
        for item in source.infolist():
            if damage == "missing" and item.filename == MODULE:
                continue
            value = source.read(item.filename)
            if damage == "source_size" and item.filename == MODULE:
                value += b"#" * 100000
            output.writestr(item, value)
        if damage == "extra":
            output.writestr("unexpected.py", b"raise RuntimeError('not reviewed')\n")
    raw = b"x" * 320001 if damage == "zip_size" else target.getvalue()
    error = "SHA/size" if damage == "zip_size" else "allowlist"
    with pytest.raises(ValueError, match=error):
        bootstrap.verify(raw, hashlib.sha256(raw).hexdigest(), telegram_initializer_recover=True)


def test_isolated_zip_verifier_accepts_canonical_zero_and_three(package, tmp_path):
    bundle, _, _ = package
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-c",
        "import sys; sys.path.insert(0,sys.argv.pop(1)); "
        "from boca_socios.host_telegram_initializer_recovery import main; raise SystemExit(main())",
        str(bundle),
        "verify",
        RUN,
        WORKFLOW,
    ]
    for receipt, expected in ((frame(accepted()), 0), (_no_go(), 3)):
        result = _run(command, tmp_path, raw=receipt)
        assert result.returncode == expected and result.stdout == receipt and not result.stderr
    assert not list(tmp_path.iterdir())


def test_real_zip_host_and_memfd_entrypoint_deny_uid_before_effects(package, tmp_path):
    # The executing local/CI user is not Boca's rootless host identity.
    assert (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10001,) * 4
    bundle, raw, digest = package
    for command, stdin in (
        ([sys.executable, "-I", "-S", "-B", str(bundle), OPERATION, RUN, WORKFLOW], b""),
        (
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(ROOT / "scripts/boca_protected_memfd_bootstrap.py"),
                digest,
                OPERATION,
                RUN,
                WORKFLOW,
            ],
            raw,
        ),
    ):
        result = _run(command, tmp_path, raw=stdin)
        assert result.returncode == 3 and result.stdout == _no_go() and not result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("damage", ["digest", "mode", "run", "workflow", "missing", "extra"])
def test_memfd_rejects_wrong_hash_mode_and_coordinates(package, tmp_path, damage):
    _, raw, digest = package
    args = [digest, OPERATION, RUN, WORKFLOW]
    if damage == "digest":
        args[0] = "0" * 64
    elif damage == "mode":
        args[1] = "boca-telegram-incident-observe"
    elif damage == "run":
        args[2] = "0"
    elif damage == "workflow":
        args[3] = "PRIVATE_UNTRUSTED"
    elif damage == "missing":
        args.pop()
    else:
        args.append("PRIVATE_UNTRUSTED")
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
    assert not list(tmp_path.iterdir())


def _admit(directory, changes):
    source = FLOW.read_text()
    condition = source.split("  deploy:\n    if: ", 1)[1].split("\n", 1)[0]
    # Execute the existing job's equality/AND predicate with the actual admission shell.
    for name in ("event_name", "ref", "repository", "actor"):
        condition = condition.replace(f"github.{name}", f'"$GITHUB_{name.upper()}"')
    assert "github." not in condition
    script = f"set -euo pipefail\n[[ {condition} ]]\n" + _shell(
        "Require verified protected environment and matching main commit"
    )
    env = {name: "" for name in re.findall(r"\b(?:BOCA|GITHUB)_[A-Z0-9_]+\b", script)}
    env.update(
        PATH="/usr/bin:/bin",
        GITHUB_EVENT_NAME="workflow_dispatch",
        GITHUB_REF="refs/heads/main",
        GITHUB_REPOSITORY="mbalbo2023/boca-socios-assistant",
        GITHUB_ACTOR="mbalbo2023",
        GITHUB_TRIGGERING_ACTOR="mbalbo2023",
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_RUN_ID=RUN,
        GITHUB_SHA=WORKFLOW,
        BOCA_OPERATION=OPERATION,
        BOCA_SOURCE_SHA=WORKFLOW,
        BOCA_SERVICE="controller",
        BOCA_BUDGET="1.5cpu-1024m-192pids",
        BOCA_DEPLOY_ENV_READY="ready",
        BOCA_TELEGRAM_ENV_READY="ready",
        BOCA_HOST_READONLY_ENV_READY="ready",
    )
    env.update(changes)
    return _run(["/bin/bash", "--noprofile", "--norc", "-c", script], directory, env=env)


def test_actual_admission_accepts_only_three_required_markers_and_blank_inputs(tmp_path):
    result = _admit(tmp_path, {})
    assert result.returncode == 0 and not result.stdout and not result.stderr
    assert len(BLANKS) == 22


@pytest.mark.parametrize("field", BLANKS)
def test_actual_admission_rejects_each_of_22_text_inputs(tmp_path, field):
    result = _admit(tmp_path, {field: "PRIVATE_UNTRUSTED"})
    assert result.returncode != 0 and not result.stdout and not result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GITHUB_EVENT_NAME", "push"),
        ("GITHUB_REF", "refs/heads/other"),
        ("GITHUB_REPOSITORY", "other/repo"),
        ("GITHUB_ACTOR", "other"),
        ("GITHUB_TRIGGERING_ACTOR", "other"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("BOCA_SERVICE", "browser-worker"),
        ("BOCA_SOURCE_SHA", "b" * 40),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids"),
        ("BOCA_DEPLOY_ENV_READY", ""),
        ("BOCA_TELEGRAM_ENV_READY", ""),
        ("BOCA_HOST_READONLY_ENV_READY", ""),
    ],
)
def test_actual_admission_rejects_each_guard_drift(tmp_path, field, value):
    result = _admit(tmp_path, {field: value})
    assert result.returncode != 0 and not result.stdout and not result.stderr


@pytest.mark.parametrize(
    ("kind", "remote_rc", "status", "canonical"),
    [
        ("accepted", 0, 0, True),
        ("no_go", 3, 1, True),
        ("accepted", 255, 1, False),
        ("accepted", 3, 1, False),
        ("no_go", 0, 1, False),
        ("malformed", 0, 1, False),
        ("wrong_w", 0, 1, False),
    ],
)
def test_actual_summary_shell_uses_same_zip_and_strict_rc_pair(
    package, tmp_path, kind, remote_rc, status, canonical
):
    bundle, _, _ = package
    receipt = (
        _no_go()
        if kind == "no_go"
        else b"PRIVATE_UNTRUSTED\n"
        if kind == "malformed"
        else frame(accepted()).replace(WORKFLOW.encode(), b"b" * 40)
        if kind == "wrong_w"
        else frame(accepted())
    )
    (tmp_path / "receipt").write_bytes(receipt)
    shell = "set -euo pipefail\nverification_rc=0" + _shell(STEP).split("verification_rc=0", 1)[1]
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "/nonexistent-untrusted-checkout",
        "bundle": str(bundle),
        "receipt_dir": str(tmp_path),
        "remote_rc": str(remote_rc),
        "GITHUB_RUN_ID": RUN,
        "GITHUB_SHA": WORKFLOW,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    result = _run(["/bin/bash", "-c", shell], tmp_path, env=env)
    assert result.returncode == status and not result.stdout and not result.stderr
    assert (tmp_path / "summary").read_bytes() == (receipt if canonical else TRANSPORT_NO_GO)


def test_workflow_routes_only_new_selector_and_shell_is_valid(tmp_path):
    source = FLOW.read_text()
    options = source.split("options: [", 1)[1].split("]", 1)[0].split(", ")
    assert options.count(OPERATION) == 1
    assert (
        f"inputs.operation == '{OPERATION}'"
        in source.split("BOCA_SOURCE_SHA:", 1)[1].split("BOCA_SOURCE_SHA_SUBMITTED:", 1)[0]
    )
    admission = _step("Require verified protected environment and matching main commit")
    assert admission.count(f"            {OPERATION})\n") == 1
    step = _step(STEP)
    assert f"if: inputs.operation == '{OPERATION}'" in step
    assert "PYTHONPATH: src" in step
    assert step.count(" ssh ") == 1
    assert step.index("check_main_ref.py") < step.index(" ssh ")
    for required in (
        "--telegram-initializer-recover",
        "scripts/boca_protected_memfd_bootstrap.py",
        '"$GITHUB_RUN_ID"',
        '"$GITHUB_SHA"',
        "180s",
        "--kill-after=5s",
        "ulimit -f 8",
        "-I -S -B",
        '"$bundle" verify',
    ):
        assert required in step
    assert not any(command in step for command in ("docker ", "sudo ", "telegram-prepare"))
    for name in (STEP, "Require verified protected environment and matching main commit"):
        result = _run(["/bin/bash", "-n"], tmp_path, raw=_shell(name).encode())
        assert result.returncode == 0 and not result.stderr
