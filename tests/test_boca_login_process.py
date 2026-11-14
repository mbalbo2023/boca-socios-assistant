"""Real disposable offline children prove deadline/STOP and bounded pipe semantics."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from boca_socios.browser import boca_login_process as module
from boca_socios.browser.boca_auth_protocol import BocaAuthRequest
from boca_socios.browser.ipc_protocol import SyntheticIPCError
from test_boca_auth_continuation import OPERATION


@pytest.mark.parametrize("mode", ["timeout", "stop", "oversize", "trailing", "success"])
def test_real_offline_child_is_reaped_and_late_output_is_rejected(monkeypatch, mode):
    async def exercise():
        original = asyncio.create_subprocess_exec
        processes = []
        started = asyncio.Event()

        async def fixture(*args, **kwargs):
            assert args == (sys.executable, "-I", "-B", "-c", module._BOOTSTRAP)
            assert kwargs["env"] == {"BOCA_BROWSER_EXECUTOR": "automatic-observation"}
            assert "private-password" not in repr(args) + repr(kwargs)
            suffix = (
                "import time; time.sleep(60)"
                if mode in {"timeout", "stop"}
                else (
                    "sys.stdout.buffer.write((65537).to_bytes(4, 'big')); sys.stdout.buffer.flush()"
                    if mode == "oversize"
                    else "sys.stdout.buffer.write((2).to_bytes(4, 'big') + b'{}'"
                    + (" + b'x'" if mode == "trailing" else "")
                    + "); sys.stdout.buffer.flush()"
                )
            )
            process = await original(
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import sys; sys.stdin.buffer.read(); " + suffix,
                **kwargs,
            )
            processes.append(process)
            started.set()
            return process

        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fixture)
        request = BocaAuthRequest(
            OPERATION, "a" * 64, "fixture@example.invalid", "private-password"
        )
        begin = monotonic()
        running = asyncio.create_task(module.run_login(request, (), deadline=begin + 0.3))
        await asyncio.wait_for(started.wait(), 1)
        if mode == "stop":
            running.cancel()
        if mode == "success":
            assert await running == b"{}"
        else:
            with pytest.raises((SyntheticIPCError, asyncio.CancelledError)):
                await running
        assert monotonic() - begin < 1.5
        assert len(processes) == 1 and processes[0].returncode is not None

    asyncio.run(exercise())


def test_worker_dependency_closure_is_stdlib_only():
    source = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys; sys.path.insert(0, " + repr(str(source)) + "); "
        "import boca_socios.browser.boca_login_process; "
        "import boca_socios.browser.automatic_observer; import boca_socios.browser.ipc_server; "
        "assert not any(m.startswith(('cryptography', 'sqlite3', "
        "'boca_socios.storage', 'boca_socios.security.credential_vault')) for m in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603 - fixed offline import proof
        [sys.executable, "-I", "-S", "-B", "-c", code],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_fixed_child_reuses_transport_and_never_serializes_errors(monkeypatch):
    import io
    import json
    from types import SimpleNamespace

    from boca_socios.browser.ipc_protocol import framed_private_auth

    request = BocaAuthRequest(OPERATION, "a" * 64, "fixture@example.invalid", "private-password")
    body = json.dumps({"request": json.loads(request.to_payload()), "cookies": []}).encode()
    output = io.BytesIO()
    calls = []

    class Transport:
        def __init__(self, *, session):
            assert session.cookies_for_url(module.LOGIN_URL) == ()

        def login(self, **credentials):
            calls.append(credentials)
            return b"received-provider-json"

    monkeypatch.setattr(module, "BocaHttpLoginTransport", Transport)
    monkeypatch.setattr(
        module.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(framed_private_auth(body)))
    )
    monkeypatch.setattr(module.sys, "stdout", SimpleNamespace(buffer=output))
    assert module.child_main() == 0
    assert calls == [{"email": request.email, "password": request.password}]
    assert output.getvalue() == framed_private_auth(b"received-provider-json")


def test_fixed_child_rejects_trailing_input_before_transport(monkeypatch):
    import io
    from types import SimpleNamespace

    from boca_socios.browser.ipc_protocol import framed_private_auth

    output = io.BytesIO()
    monkeypatch.setattr(
        module.sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(framed_private_auth(b"{}") + b"extra")),
    )
    monkeypatch.setattr(module.sys, "stdout", SimpleNamespace(buffer=output))
    monkeypatch.setattr(
        module,
        "BocaHttpLoginTransport",
        lambda **_kw: pytest.fail("invalid payload cannot contact provider"),
    )
    assert module.child_main() == 1
    assert output.getvalue() == b""
