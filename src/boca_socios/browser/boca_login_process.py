"""Supervise one fixed login helper; private pipes, total deadline, exact PID teardown."""

from __future__ import annotations

import asyncio
import json
import math
import sys
from dataclasses import asdict
from time import monotonic, time

from boca_socios.browser.boca_auth_protocol import BocaAuthRequest, decode, encode
from boca_socios.browser.ipc_protocol import (
    SyntheticIPCError,
    framed_private_auth,
    read_private_auth_frame,
)
from boca_socios.security.boca_login_transport import (
    BocaHttpLoginTransport,
    BocaSessionCookie,
    _cookie_header,
)

LOGIN_URL = "https://bocasocios-gw.bocajuniors.com.ar/auth/login/baas"
_CHILD_LIMIT = 65536
_BOOTSTRAP = (
    "import sys; sys.path.insert(0, '/app/src'); "
    "from boca_socios.browser.boca_login_process import child_main; "
    "raise SystemExit(child_main())"
)


class _Snapshot:
    def __init__(self, cookies: tuple[BocaSessionCookie, ...]) -> None:
        self._cookies = cookies

    def cookies_for_url(self, url: str) -> tuple[BocaSessionCookie, ...]:
        if url != LOGIN_URL:
            raise ValueError("login scope unverified")
        return self._cookies


def normalize_cookies(value: object) -> tuple[BocaSessionCookie, ...]:
    """Normalize only metadata returned by this live Chromium context."""
    if type(value) is not list or len(value) > 64:
        raise SyntheticIPCError("boca_session_snapshot_unverified")
    result: list[BocaSessionCookie] = []
    for item in value:
        if type(item) is not dict:
            raise SyntheticIPCError("boca_session_snapshot_unverified")
        expiry = item.get("expires")
        if expiry == -1:
            expiry = None
        try:
            result.append(
                BocaSessionCookie(
                    name=item["name"],
                    value=item["value"],
                    domain=item["domain"],
                    path=item["path"],
                    secure=item["secure"],
                    expires_at=expiry,
                )
            )
        except (KeyError, TypeError):
            raise SyntheticIPCError("boca_session_snapshot_unverified") from None
    cookies = tuple(result)
    try:
        _cookie_header(cookies, now=time())
    except (ValueError, TypeError, OverflowError):
        raise SyntheticIPCError("boca_session_snapshot_unverified") from None
    return cookies


async def _reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except OSError:
            raise SyntheticIPCError("boca_login_teardown_unverified") from None
    task = asyncio.create_task(process.wait())
    done, pending = await asyncio.wait({task}, timeout=1.0)
    if pending:
        task.cancel()
        raise SyntheticIPCError("boca_login_teardown_unverified")
    if not done:
        raise SyntheticIPCError("boca_login_teardown_unverified")
    try:
        task.result()
    except Exception:
        raise SyntheticIPCError("boca_login_teardown_unverified") from None


async def run_login(
    request: BocaAuthRequest,
    cookies: tuple[BocaSessionCookie, ...],
    *,
    deadline: float,
) -> bytes:
    """No threads can outlive STOP; the blocking DNS/TLS transport lives in this child."""
    if not math.isfinite(deadline) or not 0 < deadline - monotonic() <= 15:
        raise SyntheticIPCError("boca_login_deadline_unverified")
    _cookie_header(cookies, now=time())
    payload = encode(
        {
            "request": json.loads(request.to_payload()),
            "cookies": [asdict(cookie) for cookie in cookies],
        },
        _CHILD_LIMIT,
    )
    process: asyncio.subprocess.Process | None = None
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-B",
            "-c",
            _BOOTSTRAP,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={"BOCA_BROWSER_EXECUTOR": "automatic-observation"},
            limit=65540,
        )
    )
    result: bytes | None = None
    try:
        async with asyncio.timeout_at(deadline):
            process = await asyncio.shield(spawn)
            if process.stdin is None or process.stdout is None:
                raise SyntheticIPCError("boca_login_pipe_unverified")
            process.stdin.write(framed_private_auth(payload, maximum=_CHILD_LIMIT))
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            result = await read_private_auth_frame(process.stdout, maximum=65536)
            if await process.stdout.read(1) != b"" or await process.wait() != 0:
                raise SyntheticIPCError("boca_login_result_unverified")
    except asyncio.CancelledError:
        raise
    except Exception:
        raise SyntheticIPCError("boca_login_exchange_unverified") from None
    finally:
        if process is None:
            done, pending = await asyncio.wait({spawn}, timeout=1.0)
            if pending:
                # A late spawn is never left as an unobserved transport.
                def kill_late(task: asyncio.Task[asyncio.subprocess.Process]) -> None:
                    if not task.cancelled() and task.exception() is None:
                        child = task.result()
                        if child.returncode is None:
                            try:
                                child.kill()
                            except OSError:
                                pass  # The caller already poisoned the whole worker.

                spawn.add_done_callback(kill_late)
                raise SyntheticIPCError("boca_login_teardown_unverified")
            if done and not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
        if process is not None:
            await _reap(process)
    task = asyncio.current_task()
    if result is None or task is None or task.cancelling() or monotonic() >= deadline:
        raise SyntheticIPCError("boca_login_expired")
    return result


def child_main() -> int:
    """Fixed child entrypoint. Never prints exceptions or accepts an external endpoint."""
    try:
        header = sys.stdin.buffer.read(4)
        if len(header) != 4:
            return 1
        length = int.from_bytes(header, "big")
        if not 0 < length <= _CHILD_LIMIT:
            return 1
        raw = sys.stdin.buffer.read(length)
        if len(raw) != length or sys.stdin.buffer.read(1) != b"":
            return 1
        payload = decode(raw, {"request", "cookies"}, _CHILD_LIMIT)
        request = BocaAuthRequest.from_payload(encode(payload["request"], 32768))  # type: ignore[arg-type]
        values = payload["cookies"]
        if type(values) is not list or len(values) > 64:
            return 1
        cookies = tuple(BocaSessionCookie(**item) for item in values)
        response = BocaHttpLoginTransport(session=_Snapshot(cookies)).login(
            email=request.email,
            password=request.password,
        )
        sys.stdout.buffer.write(framed_private_auth(response, maximum=65536))
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1
