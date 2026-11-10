"""Read a single non-TTY Engine attach stream and expose only a finite observation."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from enum import StrEnum
from pathlib import Path
from socket import AF_UNIX, MSG_PEEK, SHUT_RDWR, SOCK_STREAM, socket
from threading import Event, Lock, Thread
from time import monotonic
from typing import TypeGuard

_HANDSHAKE_SECONDS = 3.0
_CAPTURE_SECONDS = 8.0
_HEADER_BYTES = 4096
_WIRE_BYTES = 65_536  # Includes the eight-byte header of every frame.
_FRAME_COUNT = 512
_CHUNK_BYTES = 4096
_JOIN_SECONDS = 0.5
_READ_POLL_SECONDS = 0.2


class CaptureResult(StrEnum):
    EMPTY = "EMPTY"
    STDOUT_ONLY = "STDOUT_ONLY"
    UNCLASSIFIED = "UNCLASSIFIED"
    TRUNCATED = "TRUNCATED"
    LIMIT = "LIMIT"
    TIMEOUT = "TIMEOUT"
    TRANSPORT = "TRANSPORT"
    MODULE_NOT_FOUND_ERROR = "MODULE_NOT_FOUND_ERROR"
    IMPORT_ERROR = "IMPORT_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    FILE_NOT_FOUND_ERROR = "FILE_NOT_FOUND_ERROR"
    OS_ERROR = "OS_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    VALUE_ERROR = "VALUE_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    MEMORY_ERROR = "MEMORY_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    IPC_PATH_UNVERIFIED = "IPC_PATH_UNVERIFIED"
    IPC_DIRECTORY_UNVERIFIED = "IPC_DIRECTORY_UNVERIFIED"
    IPC_SOCKET_UNVERIFIED = "IPC_SOCKET_UNVERIFIED"
    IPC_PEER_UNVERIFIED = "IPC_PEER_UNVERIFIED"
    IPC_FRAME_UNVERIFIED = "IPC_FRAME_UNVERIFIED"
    WORKER_IDENTITY_UNVERIFIED = "WORKER_IDENTITY_UNVERIFIED"
    WORKER_LIMITS_UNVERIFIED = "WORKER_LIMITS_UNVERIFIED"
    MISSING_PLAYWRIGHT = "MISSING_PLAYWRIGHT"
    MISSING_GREENLET = "MISSING_GREENLET"
    MISSING_PYEE = "MISSING_PYEE"
    MISSING_TYPING_EXTENSIONS = "MISSING_TYPING_EXTENSIONS"
    MISSING_BOCA_PACKAGE = "MISSING_BOCA_PACKAGE"
    MISSING_BROWSER_PACKAGE = "MISSING_BROWSER_PACKAGE"
    MISSING_BROWSER_CONTRACTS = "MISSING_BROWSER_CONTRACTS"
    MISSING_IPC_PROTOCOL = "MISSING_IPC_PROTOCOL"
    MISSING_DOMAIN_PACKAGE = "MISSING_DOMAIN_PACKAGE"
    MISSING_DOMAIN_POLICY = "MISSING_DOMAIN_POLICY"
    MISSING_IPC_CLIENT = "MISSING_IPC_CLIENT"
    MISSING_BROWSER_ON_DEMAND = "MISSING_BROWSER_ON_DEMAND"
    MISSING_PLAYWRIGHT_FACTORY = "MISSING_PLAYWRIGHT_FACTORY"
    MISSING_WORKER_HEALTH = "MISSING_WORKER_HEALTH"
    MISSING_BROWSER_SYNTHETIC = "MISSING_BROWSER_SYNTHETIC"
    MISSING_BROWSER_IPC_WORKER = "MISSING_BROWSER_IPC_WORKER"
    MISSING_BARE_CONTRACTS = "MISSING_BARE_CONTRACTS"
    MISSING_BARE_IPC_PROTOCOL = "MISSING_BARE_IPC_PROTOCOL"
    MISSING_BARE_IPC_CLIENT = "MISSING_BARE_IPC_CLIENT"
    MISSING_BARE_ON_DEMAND = "MISSING_BARE_ON_DEMAND"
    MISSING_BARE_PLAYWRIGHT_FACTORY = "MISSING_BARE_PLAYWRIGHT_FACTORY"
    MISSING_BARE_WORKER_HEALTH = "MISSING_BARE_WORKER_HEALTH"
    MISSING_BARE_SYNTHETIC = "MISSING_BARE_SYNTHETIC"
    MISSING_BARE_IPC_WORKER = "MISSING_BARE_IPC_WORKER"
    MISSING_BARE_POLICY = "MISSING_BARE_POLICY"
    MISSING_SCRIPTS_PACKAGE = "MISSING_SCRIPTS_PACKAGE"
    MISSING_SCRIPT_VERIFY_CHROMIUM = "MISSING_SCRIPT_VERIFY_CHROMIUM"
    MISSING_SCRIPT_OBSERVE_HOME = "MISSING_SCRIPT_OBSERVE_HOME"
    MISSING_SCRIPT_BROWSER_BUDGET = "MISSING_SCRIPT_BROWSER_BUDGET"
    MISSING_SCRIPT_TICKET_FLOW = "MISSING_SCRIPT_TICKET_FLOW"
    MISSING_BARE_VERIFY_CHROMIUM = "MISSING_BARE_VERIFY_CHROMIUM"
    MISSING_BARE_OBSERVE_HOME = "MISSING_BARE_OBSERVE_HOME"
    MISSING_BARE_BROWSER_BUDGET = "MISSING_BARE_BROWSER_BUDGET"
    MISSING_BARE_TICKET_FLOW = "MISSING_BARE_TICKET_FLOW"
    MISSING_CONTROLLER_ACCEPTANCE = "MISSING_CONTROLLER_ACCEPTANCE"
    MISSING_CONTROLLER_EVENTS = "MISSING_CONTROLLER_EVENTS"
    MISSING_CONTROLLER_INTEGRATION = "MISSING_CONTROLLER_INTEGRATION"
    MISSING_CONTROLLER_NOTIFY = "MISSING_CONTROLLER_NOTIFY"
    MISSING_CONTROLLER_PANEL = "MISSING_CONTROLLER_PANEL"
    MISSING_CONTROLLER_QUEUE = "MISSING_CONTROLLER_QUEUE"
    MISSING_CONTROLLER_SECURITY = "MISSING_CONTROLLER_SECURITY"
    MISSING_CONTROLLER_STORAGE = "MISSING_CONTROLLER_STORAGE"
    MISSING_CONTROLLER_CONFIG = "MISSING_CONTROLLER_CONFIG"
    MISSING_CONTROLLER_RUNTIME = "MISSING_CONTROLLER_RUNTIME"
    MISSING_PLAYWRIGHT_ASYNC_API = "MISSING_PLAYWRIGHT_ASYNC_API"
    MISSING_CRYPTOGRAPHY = "MISSING_CRYPTOGRAPHY"
    MISSING_CFFI = "MISSING_CFFI"
    MISSING_PYCPARSER = "MISSING_PYCPARSER"
    ENTRY_MODULE_MISSING = "ENTRY_MODULE_MISSING"


_RESULT_VALUES = tuple(item.value for item in CaptureResult)


def is_capture_result(value: object) -> TypeGuard[str]:
    """Validate an external receipt without echoing or interpolating its value."""
    return type(value) in (str, CaptureResult) and value in _RESULT_VALUES


class CaptureFailure(Exception):
    """The start block was never entered. Only the fixed result can cross the boundary."""

    def __init__(self, result: CaptureResult) -> None:
        super().__init__(result.value)
        self.result = result


_EXCEPTIONS = {
    b"ModuleNotFoundError": CaptureResult.MODULE_NOT_FOUND_ERROR,
    b"ImportError": CaptureResult.IMPORT_ERROR,
    b"PermissionError": CaptureResult.PERMISSION_ERROR,
    b"FileNotFoundError": CaptureResult.FILE_NOT_FOUND_ERROR,
    b"OSError": CaptureResult.OS_ERROR,
    b"RuntimeError": CaptureResult.RUNTIME_ERROR,
    b"ValueError": CaptureResult.VALUE_ERROR,
    b"TypeError": CaptureResult.TYPE_ERROR,
    b"MemoryError": CaptureResult.MEMORY_ERROR,
    b"SyntaxError": CaptureResult.SYNTAX_ERROR,
}
_IPC = b"boca_socios.browser.ipc_protocol.SyntheticIPCError: "
_BOUNDARY = b"boca_socios.browser.on_demand.WorkerBoundaryError: "
_HEALTH_BOUNDARY = b"boca_socios.browser.worker_health.WorkerBoundaryError: "
_MISSING = b"ModuleNotFoundError: No module named "
# Dockerfile.browser fixes both the interpreter directory and the -m target.
_PYTHON = b"/app/.venv/bin/python: "
_ENTRY = b"boca_socios.browser.ipc_worker"
_FIND_ENTRY = _PYTHON + b"Error while finding module specification for '" + _ENTRY + b"' ("
_EXACT_LINES = (
    (_IPC + b"ipc_path_unverified", CaptureResult.IPC_PATH_UNVERIFIED),
    (_IPC + b"ipc_directory_unverified", CaptureResult.IPC_DIRECTORY_UNVERIFIED),
    (_IPC + b"ipc_socket_unverified", CaptureResult.IPC_SOCKET_UNVERIFIED),
    (_IPC + b"ipc_peer_unverified", CaptureResult.IPC_PEER_UNVERIFIED),
    (_IPC + b"ipc_frame_unverified", CaptureResult.IPC_FRAME_UNVERIFIED),
    (_BOUNDARY + b"worker_identity_unverified", CaptureResult.WORKER_IDENTITY_UNVERIFIED),
    (_BOUNDARY + b"worker_limits_unverified", CaptureResult.WORKER_LIMITS_UNVERIFIED),
    (_HEALTH_BOUNDARY + b"worker_identity_unverified", CaptureResult.WORKER_IDENTITY_UNVERIFIED),
    (_HEALTH_BOUNDARY + b"worker_limits_unverified", CaptureResult.WORKER_LIMITS_UNVERIFIED),
    (_MISSING + b"'playwright'", CaptureResult.MISSING_PLAYWRIGHT),
    (_MISSING + b"'greenlet'", CaptureResult.MISSING_GREENLET),
    (_MISSING + b"'pyee'", CaptureResult.MISSING_PYEE),
    (_MISSING + b"'typing_extensions'", CaptureResult.MISSING_TYPING_EXTENSIONS),
    (_MISSING + b"'boca_socios'", CaptureResult.MISSING_BOCA_PACKAGE),
    (_MISSING + b"'boca_socios.browser'", CaptureResult.MISSING_BROWSER_PACKAGE),
    (_MISSING + b"'boca_socios.browser.contracts'", CaptureResult.MISSING_BROWSER_CONTRACTS),
    (_MISSING + b"'boca_socios.browser.ipc_protocol'", CaptureResult.MISSING_IPC_PROTOCOL),
    (_MISSING + b"'boca_socios.domain'", CaptureResult.MISSING_DOMAIN_PACKAGE),
    (_MISSING + b"'boca_socios.domain.policy'", CaptureResult.MISSING_DOMAIN_POLICY),
    # Fixed names from the browser COPY paths, public package boundaries and uv.lock.
    # An unqualified sibling has its own receipt, so a packaging fix can distinguish it.
    (_MISSING + b"'boca_socios.browser.ipc_client'", CaptureResult.MISSING_IPC_CLIENT),
    (_MISSING + b"'boca_socios.browser.on_demand'", CaptureResult.MISSING_BROWSER_ON_DEMAND),
    (
        _MISSING + b"'boca_socios.browser.playwright_factory'",
        CaptureResult.MISSING_PLAYWRIGHT_FACTORY,
    ),
    (_MISSING + b"'boca_socios.browser.worker_health'", CaptureResult.MISSING_WORKER_HEALTH),
    (_MISSING + b"'boca_socios.browser.synthetic'", CaptureResult.MISSING_BROWSER_SYNTHETIC),
    (_MISSING + b"'boca_socios.browser.ipc_worker'", CaptureResult.MISSING_BROWSER_IPC_WORKER),
    (_MISSING + b"'contracts'", CaptureResult.MISSING_BARE_CONTRACTS),
    (_MISSING + b"'ipc_protocol'", CaptureResult.MISSING_BARE_IPC_PROTOCOL),
    (_MISSING + b"'ipc_client'", CaptureResult.MISSING_BARE_IPC_CLIENT),
    (_MISSING + b"'on_demand'", CaptureResult.MISSING_BARE_ON_DEMAND),
    (_MISSING + b"'playwright_factory'", CaptureResult.MISSING_BARE_PLAYWRIGHT_FACTORY),
    (_MISSING + b"'worker_health'", CaptureResult.MISSING_BARE_WORKER_HEALTH),
    (_MISSING + b"'synthetic'", CaptureResult.MISSING_BARE_SYNTHETIC),
    (_MISSING + b"'ipc_worker'", CaptureResult.MISSING_BARE_IPC_WORKER),
    (_MISSING + b"'policy'", CaptureResult.MISSING_BARE_POLICY),
    (_MISSING + b"'scripts'", CaptureResult.MISSING_SCRIPTS_PACKAGE),
    (_MISSING + b"'scripts.verify_chromium_worker'", CaptureResult.MISSING_SCRIPT_VERIFY_CHROMIUM),
    (_MISSING + b"'scripts.observe_public_home'", CaptureResult.MISSING_SCRIPT_OBSERVE_HOME),
    (_MISSING + b"'scripts.measure_browser_budget'", CaptureResult.MISSING_SCRIPT_BROWSER_BUDGET),
    (_MISSING + b"'scripts.run_synthetic_ticket_flow'", CaptureResult.MISSING_SCRIPT_TICKET_FLOW),
    (_MISSING + b"'verify_chromium_worker'", CaptureResult.MISSING_BARE_VERIFY_CHROMIUM),
    (_MISSING + b"'observe_public_home'", CaptureResult.MISSING_BARE_OBSERVE_HOME),
    (_MISSING + b"'measure_browser_budget'", CaptureResult.MISSING_BARE_BROWSER_BUDGET),
    (_MISSING + b"'run_synthetic_ticket_flow'", CaptureResult.MISSING_BARE_TICKET_FLOW),
    (_MISSING + b"'boca_socios.acceptance'", CaptureResult.MISSING_CONTROLLER_ACCEPTANCE),
    (_MISSING + b"'boca_socios.events'", CaptureResult.MISSING_CONTROLLER_EVENTS),
    (_MISSING + b"'boca_socios.integration'", CaptureResult.MISSING_CONTROLLER_INTEGRATION),
    (_MISSING + b"'boca_socios.notify'", CaptureResult.MISSING_CONTROLLER_NOTIFY),
    (_MISSING + b"'boca_socios.panel'", CaptureResult.MISSING_CONTROLLER_PANEL),
    (_MISSING + b"'boca_socios.queue'", CaptureResult.MISSING_CONTROLLER_QUEUE),
    (_MISSING + b"'boca_socios.security'", CaptureResult.MISSING_CONTROLLER_SECURITY),
    (_MISSING + b"'boca_socios.storage'", CaptureResult.MISSING_CONTROLLER_STORAGE),
    (_MISSING + b"'boca_socios.config'", CaptureResult.MISSING_CONTROLLER_CONFIG),
    (_MISSING + b"'boca_socios.runtime'", CaptureResult.MISSING_CONTROLLER_RUNTIME),
    (_MISSING + b"'playwright.async_api'", CaptureResult.MISSING_PLAYWRIGHT_ASYNC_API),
    (_MISSING + b"'cryptography'", CaptureResult.MISSING_CRYPTOGRAPHY),
    (_MISSING + b"'cffi'", CaptureResult.MISSING_CFFI),
    (_MISSING + b"'pycparser'", CaptureResult.MISSING_PYCPARSER),
    (_PYTHON + b"No module named " + _ENTRY, CaptureResult.ENTRY_MODULE_MISSING),
    (_FIND_ENTRY + _MISSING + b"'boca_socios')", CaptureResult.MISSING_BOCA_PACKAGE),
    (_FIND_ENTRY + _MISSING + b"'boca_socios.browser')", CaptureResult.MISSING_BROWSER_PACKAGE),
)
# Include a possible CR and a further byte so clipping cannot turn a longer line into a match.
_PREFIX_BYTES = max(len(line) for line, _ in _EXACT_LINES) + 2


def _line_result(prefix: bytes, *, newline: bool = False) -> CaptureResult:
    line = prefix.removesuffix(b"\r") if newline else prefix
    for known_line, result in _EXACT_LINES:
        if line == known_line:
            return result
    name = line.partition(b": ")[0]
    for known_name, result in _EXCEPTIONS.items():
        if name == known_name:
            return result
    return CaptureResult.UNCLASSIFIED


class _StderrTail:
    """Keep only enough of the last physical stderr line to recognize a class prefix."""

    def __init__(self) -> None:
        self.prefix = b""
        self.last_complete: CaptureResult | None = None

    def feed(self, data: bytes) -> None:
        before, newline, tail = data.rpartition(b"\n")
        if newline:
            _, previous_newline, complete = before.rpartition(b"\n")
            prefix = b"" if previous_newline else self.prefix
            self.last_complete = _line_result(
                prefix + complete[: _PREFIX_BYTES - len(prefix)], newline=True
            )
            self.prefix = b""
        self.prefix += tail[: _PREFIX_BYTES - len(self.prefix)]

    def result(self, saw_stdout: bool) -> CaptureResult:
        if self.prefix:
            return _line_result(self.prefix)
        if self.last_complete is not None:
            return self.last_complete
        return CaptureResult.STDOUT_ONLY if saw_stdout else CaptureResult.EMPTY


def _remaining(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _valid_upgrade(header: bytes) -> bool:
    status, *fields = header.split(b"\r\n")
    if not re.fullmatch(rb"HTTP/1[.]1 101(?: [ -~]*)?", status):
        return False
    required = {
        b"connection": b"upgrade",
        b"upgrade": b"tcp",  # Engine's protocol token, including on AF_UNIX.
        b"content-type": b"application/vnd.docker.multiplexed-stream",
    }
    observed = set()
    for field in fields:
        name, sep, value = field.partition(b":")
        name = name.lower()
        if not sep or not re.fullmatch(rb"[!#$%&'*+.^_`|~a-z0-9-]+", name):
            return False
        if not re.fullmatch(rb"[\t\x20-\x7e\x80-\xff]*", value):
            return False
        if name in (b"content-length", b"transfer-encoding"):
            return False
        if name in required:
            if name in observed or value.strip(b" \t").lower() != required[name]:
                return False
            observed.add(name)
    return observed == required.keys()


def _upgrade(peer: socket, path: str, cid: str) -> bytes | CaptureResult:
    deadline = monotonic() + _HANDSHAKE_SECONDS
    peer.settimeout(_remaining(deadline))
    peer.connect(path)
    request = (
        f"POST /v1.48/containers/{cid}/attach?stream=1&stdout=1&stderr=1&stdin=0&logs=0 HTTP/1.1\r\n"
        "Host: localhost\r\nConnection: Upgrade\r\nUpgrade: tcp\r\nContent-Length: 0\r\n\r\n"
    )
    peer.settimeout(_remaining(deadline))
    peer.sendall(request.encode("ascii"))
    buffer = bytearray()
    while len(buffer) < _HEADER_BYTES:
        peer.settimeout(_remaining(deadline))
        chunk = peer.recv(_HEADER_BYTES - len(buffer))
        _remaining(deadline)
        if not chunk:
            return CaptureResult.TRUNCATED
        # A delimiter may straddle reads. Search only the new bytes and that overlap.
        start = max(0, len(buffer) - 3)
        buffer.extend(chunk)
        boundary = buffer.find(b"\r\n\r\n", start)
        if boundary >= 0:
            if not _valid_upgrade(bytes(buffer[:boundary])):
                return CaptureResult.TRANSPORT
            _remaining(deadline)
            return bytes(buffer[boundary + 4 :])
    return CaptureResult.LIMIT


class OutputCapture:
    """The single reader owns the upgraded socket until EOF, quota, deadline or cancellation."""

    def __init__(self, peer: socket, initial: bytes) -> None:
        self._peer = peer
        self._initial = initial
        self._deadline = monotonic() + _CAPTURE_SECONDS
        self._result: CaptureResult | None = None
        self._lock = Lock()
        self._ready = Event()
        self._cancelled = Event()
        self._thread = Thread(target=self._consume, name="boca-start-capture", daemon=True)

    def _arm(self) -> CaptureResult | None:
        # Detect an already disconnected peer after 101; leave any actual data for the reader.
        self._peer.setblocking(False)
        try:
            if not self._peer.recv(1, MSG_PEEK):
                return CaptureResult.TRANSPORT
        except BlockingIOError:
            pass
        self._thread.start()
        if not self._ready.wait(_remaining(self._deadline)):
            return CaptureResult.TIMEOUT
        with self._lock:
            if self._result in (
                CaptureResult.LIMIT,
                CaptureResult.TRUNCATED,
                CaptureResult.TIMEOUT,
            ):
                return self._result
            return None if self._result is None else CaptureResult.TRANSPORT

    def _read(self, count: int) -> bytes:
        while not self._cancelled.is_set():
            remaining = _remaining(self._deadline)
            if self._initial:
                data, self._initial = self._initial[:count], self._initial[count:]
                return data
            # Even if shutdown fails, cancellation wakes within this short poll interval.
            self._peer.settimeout(min(remaining, _READ_POLL_SECONDS))
            try:
                data = self._peer.recv(count)
            except TimeoutError:
                continue
            _remaining(self._deadline)
            return data
        raise ConnectionAbortedError

    def _frames(self) -> CaptureResult:
        budget = _WIRE_BYTES
        stderr = _StderrTail()
        saw_stdout = False
        for _ in range(_FRAME_COUNT):
            header = bytearray()
            while len(header) < min(8, budget):
                fragment = self._read(min(8, budget) - len(header))
                if not fragment:
                    return CaptureResult.TRUNCATED if header else stderr.result(saw_stdout)
                header.extend(fragment)
            if len(header) < 8:
                return CaptureResult.LIMIT
            channel = header[0]
            if channel not in (1, 2) or header[1:4] != b"\0\0\0":
                # Stream 3 carries daemon errors, never process stderr.
                return CaptureResult.TRANSPORT
            size = int.from_bytes(header[4:], "big")
            budget -= 8 + size
            if budget < 0:
                return CaptureResult.LIMIT
            while size:
                data = self._read(min(size, _CHUNK_BYTES))
                if not data:
                    return CaptureResult.TRUNCATED
                if channel == 2:
                    stderr.feed(data)
                else:
                    saw_stdout = True
                size -= len(data)
        return CaptureResult.LIMIT

    def _consume(self) -> None:
        result = CaptureResult.TRANSPORT
        try:
            self._ready.set()
            result = self._frames()
        except TimeoutError:
            result = CaptureResult.TIMEOUT
        except BaseException:
            # No worker exception or its private locals may reach threading.excepthook.
            result = CaptureResult.TRANSPORT
        finally:
            with self._lock:
                self._initial = b""
                try:
                    self._peer.close()
                except Exception:
                    result = CaptureResult.TRANSPORT
                if self._result is None:
                    self._result = result

    def _cancel(self, reason: CaptureResult) -> bool:
        with self._lock:
            active = self._result is None and self._thread.is_alive()
            if self._result is None:
                self._result = reason
                self._cancelled.set()
                # Wake recv/poll on our own socket. No stdin payload or process signal.
                with suppress(Exception):
                    self._peer.shutdown(SHUT_RDWR)
        if self._thread.ident is not None:
            self._thread.join(_JOIN_SECONDS)
        # Also covers a thread that could not start or could not finish its join on time.
        if self._thread.ident is None or self._thread.is_alive():
            with self._lock:
                self._initial = b""
                with suppress(Exception):
                    self._peer.close()
            if self._thread.ident is not None:
                self._thread.join(_JOIN_SECONDS)
        return active and not self._thread.is_alive()

    def finish(self) -> CaptureResult:
        """Wait only for the remainder of this attachment's original observation window."""
        self._thread.join(max(0.0, self._deadline - monotonic()) + _JOIN_SECONDS)
        if self._thread.is_alive():
            self._cancel(CaptureResult.TIMEOUT)
        with self._lock:
            return self._result or CaptureResult.TRANSPORT

    def close(self) -> bool:
        """Detach without signalling the process. True means an active reader was joined."""
        return self._cancel(CaptureResult.TRANSPORT)


@contextmanager
def attach_output(socket_path: str | Path, cid: str) -> Iterator[OutputCapture]:
    """Attach before the caller starts its exact CID. Raise CaptureFailure on failed upgrade."""
    if not isinstance(cid, str) or not re.fullmatch(r"[0-9a-f]{64}", cid):
        raise CaptureFailure(CaptureResult.TRANSPORT)
    if not isinstance(socket_path, (str, Path)):
        raise CaptureFailure(CaptureResult.TRANSPORT)
    path = str(socket_path)
    if not path.startswith("/") or "\0" in path:
        raise CaptureFailure(CaptureResult.TRANSPORT)
    try:
        peer = socket(AF_UNIX, SOCK_STREAM)
    except Exception:
        peer = None
    if peer is None:
        raise CaptureFailure(CaptureResult.TRANSPORT)
    capture = None
    try:
        try:
            initial = _upgrade(peer, path, cid)
            if isinstance(initial, CaptureResult):
                failure: CaptureResult | None = initial
            else:
                capture = OutputCapture(peer, initial)
                del initial
                failure = capture._arm()
        except TimeoutError:
            failure = CaptureResult.TIMEOUT
        except Exception:
            failure = CaptureResult.TRANSPORT
        if failure is not None:
            raise CaptureFailure(failure)
        assert capture is not None
        yield capture
    finally:
        if capture is None:
            with suppress(OSError):
                peer.close()
        else:
            capture.close()
