"""R172 code-only guard against duplicating reviewed member/Telegram boundaries.

These static contracts do not inspect the protected browser modules, read
runtime credentials, access an installed database or contact Telegram/Boca.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _method(module: str, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(_read(module))
    owner = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def _called_attribute(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == name
        for item in ast.walk(node)
    )


def test_existing_member_enrollment_keeps_credentials_sealed_only() -> None:
    schema = _read("src/boca_socios/storage/migrations/0001_initial.sql")
    table = re.search(r"(?is)CREATE TABLE IF NOT EXISTS credentials\s*\((.*?)\);", schema)
    assert table is not None
    columns = set(re.findall(r"(?m)^\s{2}([a-z_]+)\s+(?:TEXT|BLOB)\b", table.group(1)))
    assert {"member_id", "key_id", "nonce", "ciphertext", "updated_at"} <= columns
    assert not ({"password", "plaintext", "cleartext", "raw_password"} & columns)

    vault = _method("src/boca_socios/security/credential_vault.py", "CredentialVault", "seal")
    assert _called_attribute(vault, "encrypt")
    assert _called_attribute(vault, "_aad")
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "AESGCM"
        for node in ast.walk(vault)
    )

    enrollment = _method(
        "src/boca_socios/security/enrollment.py", "MemberEnrollmentService", "enroll"
    )
    assert _called_attribute(enrollment, "seal")
    sql_literals = [
        node.value
        for node in ast.walk(enrollment)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert any(
        re.search(
            r"INSERT\s+INTO\s+credentials\s*\(\s*member_id\s*,\s*key_id\s*,\s*nonce\s*,\s*ciphertext\s*\)",
            statement,
            re.IGNORECASE,
        )
        for statement in sql_literals
    )


def test_telegram_staging_and_synthetic_outbox_reuse_existing_wiring() -> None:
    runtime = ast.parse(_read("src/boca_socios/runtime.py"))
    stager = next(
        node
        for node in runtime.body
        if isinstance(node, ast.FunctionDef) and node.name == "_configured_telegram_pairing_stager"
    )
    assert _called_attribute(stager, "validate_beta")
    assert any(
        isinstance(node, ast.Name) and node.id == "stage_private_telegram_pairing"
        for node in ast.walk(stager)
    )
    assert any(
        isinstance(node, ast.Constant) and node.value == "encrypted-only"
        for node in ast.walk(stager)
    )

    # The controller publishes safe synthetic notices to SQLite. Telegram's
    # independent, opt-in sender consumes the same reviewed outbox.
    beta = _read("src/boca_socios/integration/beta.py")
    delivery = _read("src/boca_socios/notify/telegram_delivery.py")
    worker = _read("src/boca_socios/notify/telegram_worker.py")
    assert "StaticOutboxAdapter(self._outbox" in beta
    assert "SqliteNotificationOutbox" in delivery
    assert "SqliteNotificationOutbox(database)" in worker
    assert "BOCA_TELEGRAM_DISPATCH_MODE" in worker
    assert '"explicit"' in worker
    assert "boca_socios.notify.telegram_worker" not in _read("src/boca_socios/runtime.py")


def test_telegram_activation_stays_explicitly_no_go_and_token_requires_rotation() -> None:
    workflow = _read(".github/workflows/boca-first-deploy.yml")
    step = re.search(
        r"(?ms)^      - name: Prove Telegram dual-source release ancestry CODE_ONLY then reject physical activation\n"
        r"(.*?)(?=^      - name:|\Z)",
        workflow,
    )
    assert step is not None
    body = step.group(1)
    assert "if: inputs.operation == 'telegram-activate'" in body
    assert "BOCA_TELEGRAM_POSTCUTOVER state=NO_GO" in body
    assert "host=untouched sender=OFF" in body
    assert re.search(r"(?m)^\s+exit 1\s*$", body)

    # A source gate cannot establish secret rotation. Preserve the documented
    # requirement instead of treating ciphertext staging as sender activation.
    agents = _read("AGENTS.md")
    assert re.search(
        r"Treat the token as\s+compromised and require secret rotation by its owner", agents
    )
    panel = ast.parse(_read("src/boca_socios/panel/private_http.py"))
    binary_fragments = [
        node.value
        for node in ast.walk(panel)
        if isinstance(node, ast.Constant) and isinstance(node.value, bytes)
    ]
    assert any(b'"state":"STAGED_PENDING_PROTECTED_CUTOVER"' in part for part in binary_fragments)
    assert any(
        b'"sender":"OFF","notification_receipt":"UNVERIFIED"' in part for part in binary_fragments
    )
