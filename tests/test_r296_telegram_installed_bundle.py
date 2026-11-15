"""Execute the shipped installed ZIP in isolation; no Docker, host or provider."""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as memfd  # noqa: E402
import build_protected_telegram_bundle as bundle  # noqa: E402


@pytest.fixture(scope="module")
def packed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("r296-telegram") / "installed.pyz"
    bundle.build(ROOT, target, installed=True)
    return target


def run(packed: Path, *args: str, payload: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed isolated archive, synthetic local input
        [sys.executable, "-I", "-S", "-B", str(packed), *args],
        input=payload,
        capture_output=True,
        timeout=15,
        check=False,
    )


def test_installed_transport_has_exact_independent_bounds_and_modes(
    packed: Path, tmp_path: Path
) -> None:
    raw = packed.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    other = tmp_path / "again.pyz"
    assert bundle.build(ROOT, other, installed=True) == digest
    assert other.read_bytes() == raw
    memfd.verify(raw, digest, telegram_installed=True)
    with zipfile.ZipFile(packed) as archive:
        assert set(archive.namelist()) == memfd.TELEGRAM_INSTALLED_ENTRIES
        assert sum(item.file_size for item in archive.infolist()) <= 450_000
        assert len(raw) <= 300_000
        assert "boca_socios/telegram_maintenance.py" not in archive.namelist()
        assert not any(
            "browser/" in name or "cutover_backend" in name for name in archive.namelist()
        )
    with pytest.raises(ValueError):
        memfd.verify(raw, digest)
    with pytest.raises(ValueError):
        memfd.verify(raw, digest, telegram_installed=True, installed_admin=True)
    with pytest.raises(ValueError):
        memfd.verify(raw + b"x", digest, telegram_installed=True)


def test_selected_declarations_preserve_canonical_function_bodies(packed: Path) -> None:
    with zipfile.ZipFile(packed) as archive:
        for name in (
            bundle.CLEANUP_PROJECTION_NAME,
            bundle.NETWORK_PROJECTION_NAME,
            bundle.INSTALLATION_PROJECTION_NAME,
            bundle.OWNER_PROJECTION_NAME,
            bundle.SERVICE_PROJECTION_NAME,
            bundle.STAGE_PROJECTION_NAME,
        ):
            original = ast.parse((ROOT / "src" / name).read_bytes())
            available = {ast.dump(node) for node in original.body}
            selected = ast.parse(archive.read(name))
            assert all(ast.dump(node) in available for node in selected.body)


def test_real_isolated_zip_imports_and_rejects_bad_dispatch_before_host(packed: Path) -> None:
    probe = run(packed, "selftest")
    assert probe.returncode == 0, probe.stderr
    assert b"INSTALLED_CLOSURE_READY host=untouched" in probe.stdout
    assert not probe.stderr
    for args in (
        (),
        ("telegram-activate",),
        ("telegram-activate", "x", "b" * 40, "123"),
        ("arbitrary", "a" * 40, "b" * 40, "123"),
    ):
        result = run(packed, *args)
        assert result.returncode == 2 and result.stdout.startswith(
            b"BOCA_TELEGRAM_HOST state=NO_GO"
        )
        assert not result.stderr


@pytest.mark.parametrize("interrupt", [False, True])
def test_isolated_archive_executes_prepare_receipt_and_lazy_binding_closure(
    packed: Path, interrupt: bool
) -> None:
    from boca_socios import host_on_demand_service as service
    from test_on_demand_service import installation

    plan = service._plan(
        Path("/home/boca-deploy"), installation(Path("/home/boca-deploy")), "c" * 64
    )
    program = r"""
import hashlib, json, os, signal, sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from boca_socios import host_on_demand_service as service
from boca_socios import host_first_deploy as deploy
from boca_socios import host_telegram_backend as backend
from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_telegram_cli import main
item, digest = service._decode(Path('/home/boca-deploy'), sys.stdin.buffer.read())
assert not hasattr(service, 'handle_connection')
assert service._decode(Path('/home/boca-deploy'), service._plan(Path('/home/boca-deploy'), item, digest))[0] == item
assert len(item.fingerprint()) == 64
for name in ('_telegram_test_finished', '_telegram_test_environment', '_telegram_sender_hash'):
    assert callable(getattr(deploy, name))
test = deploy._telegram_test_container(item.controller_image, item.source_sha, '', '', v2_attempt='123')
assert test[:2] == ('docker', 'create') and 'test-v2' in test and '123' in test
sender = deploy._telegram_worker_container(item.controller_image, item.source_sha, '', '',
    item.installation_run_id, '123', v2=True)
assert 'serve-v2' in sender
events = []
class Context:
    installation = item
    attempt_id = '123'
    volumes = (('boca-socios_boca_telegram', '/run/telegram'),)
    def healthy(self): events.append('healthy')
    def stop(self): events.append('stop')
    def bind(self, *args): events.append('bind')
    def stopped(self): events.append('stopped')
    def restore(self): events.append('restore')
recipient = bootstrap.RecipientReceipt('PREPARED', bootstrap._b64(b'p' * 32), hashlib.sha256(b'p' * 32).hexdigest())
class Storage:
    def __init__(self, context): pass
    def provision(self): events.append('provision')
    def cleanup_failed_provision(self): events.append('cleanup')
    def call(self, op, data):
        events.append(op)
        if op == 'verify-schema': return {'schema': 7}
        if op == 'owner-identity': return {'owner_digest': 'd' * 64}
        if op == 'prepare':
            if sys.argv[2] == 'interrupt': os.kill(os.getpid(), signal.SIGTERM)
            return asdict(recipient)
        if op == 'publish-recipient': return {'state': 'PUBLISHED'}
        if op == 'publish-status':
            raw = bootstrap._canonical({'version': 1, **data, 'configured': 'ABSENT',
                'paired': 'NOT_PAIRED', 'human_receipt': 'UNVERIFIED'}) + b'\n'
            return {'state': 'STATUS_PUBLISHED', 'sha256': hashlib.sha256(raw).hexdigest(),
                    'configured': 'ABSENT', 'paired': 'NOT_PAIRED'}
        raise AssertionError('unexpected maintenance operation')
backend.resolve_installed_context = lambda *args, **kwargs: Context()
backend.InstalledMaintenance = Storage
@contextmanager
def lease(attempt):
    events.append('lease-enter')
    yield object()
    events.append('lease-exit')
cleanup.protected_boca_job_lease = lease
result = main(['telegram-prepare', item.source_sha, 'b' * 40, '123'])
if sys.argv[2] == 'interrupt':
    assert result == 3
    assert events == ['lease-enter', 'verify-schema', 'owner-identity', 'stop', 'provision', 'prepare', 'cleanup', 'restore'], events
else:
    assert result == 0
    assert events == ['lease-enter', 'verify-schema', 'owner-identity', 'stop', 'provision', 'prepare', 'bind', 'publish-recipient', 'stopped', 'restore', 'healthy', 'publish-status', 'healthy', 'lease-exit'], events
assert 'cryptography' not in sys.modules
"""
    result = subprocess.run(  # noqa: S603 - isolated archive and fake IO, no host/provider
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            program,
            str(packed),
            "interrupt" if interrupt else "normal",
        ],
        input=plan,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (
        b'"state":"FAILED_STATE_PRESERVED"' if interrupt else b'"state":"PREPARED"'
    ) in result.stdout
    assert b'"restoration":"CONTROLLER_HEALTHY_ENGINE_OFF"' in result.stdout
    assert not result.stderr


def test_preflight_denial_cannot_claim_sender_off_without_a_binding_observation(
    packed: Path,
) -> None:
    program = r"""
import sys
from contextlib import contextmanager
sys.path.insert(0, sys.argv[1])
from boca_socios import host_boca_cleanup as cleanup, host_on_demand_service as service
from boca_socios.host_telegram_cli import main
@contextmanager
def denied(attempt):
    raise ValueError('synthetic lease denied')
    yield
def forbidden(*args):
    raise AssertionError('binding must remain unread')
cleanup.protected_boca_job_lease = denied
service.read_installed_binding = forbidden
assert main(['telegram-sender-recover', 'a' * 40, 'b' * 40, '123']) == 3
"""
    result = subprocess.run(  # noqa: S603 - fixed isolated program, denied synthetic lease
        [sys.executable, "-I", "-S", "-B", "-c", program, str(packed)],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert b'"state":"PREFLIGHT_FAILED"' in result.stdout
    assert b'"sender_state":"UNVERIFIED"' in result.stdout
    assert not result.stderr


def test_runner_receipt_verification_is_bounded_correlated_and_has_no_host_effect(
    packed: Path,
) -> None:
    from boca_socios.host_telegram_backend import TelegramBackendReceipt

    raw = TelegramBackendReceipt(
        "prepare", "123", "a" * 40, "PREPARED", "CONTROLLER_HEALTHY_ENGINE_OFF"
    ).redacted_json()
    args = ("verify-receipt", "telegram-prepare", "a" * 40, "b" * 40, "123")
    result = run(packed, *args, payload=raw + b"\n")
    assert result.returncode == 0 and result.stdout == b"BOCA_TELEGRAM_HOST " + raw + b"\n"
    for invalid in (
        raw + b"\n\n",
        b"x" * 1025,
        raw.replace(b'"123"', b'"124"'),
        raw.replace(b'"human_receipt":"UNVERIFIED"', b'"human_receipt":"RECEIVED"'),
    ):
        refused = run(packed, *args, payload=invalid)
        assert refused.returncode == 2 and not refused.stderr
