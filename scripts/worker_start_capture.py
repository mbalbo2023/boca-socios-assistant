"""Read a single non-TTY Engine attach stream and expose only a finite observation."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from enum import StrEnum
from pathlib import Path
from socket import AF_UNIX, SOCK_STREAM, socket
from time import monotonic

_HANDSHAKE_SECONDS = 3.0
_CAPTURE_SECONDS = 8.0
_HEADER_BYTES = 4096
_WIRE_BYTES = 65_536  # Includes the eight-byte header of every frame.
_FRAME_COUNT = 512
_CHUNK_BYTES = 4096


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
_PREFIX_BYTES = max(map(len, _EXCEPTIONS)) + len(b": ")


def _line_result(prefix: bytes) -> CaptureResult:
    name = prefix.removesuffix(b"\r").partition(b": ")[0]
    return _EXCEPTIONS.get(name, CaptureResult.UNCLASSIFIED)


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
            self.last_complete = _line_result(prefix + complete[: _PREFIX_BYTES - len(prefix)])
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
    """A confirmed attachment. finish() consumes once and closes the socket."""

    def __init__(self, peer: socket, initial: bytes) -> None:
        self._peer = peer
        self._initial = initial
        self._deadline = monotonic() + _CAPTURE_SECONDS
        self._result: CaptureResult | None = None

    def _read(self, count: int) -> bytes:
        remaining = _remaining(self._deadline)
        if self._initial:
            data, self._initial = self._initial[:count], self._initial[count:]
            return data
        self._peer.settimeout(remaining)
        data = self._peer.recv(count)
        _remaining(self._deadline)
        return data

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

    def finish(self) -> CaptureResult:
        if self._result is None:
            try:
                self._result = self._frames()
            except TimeoutError:
                self._result = CaptureResult.TIMEOUT
            except Exception:
                # The observation boundary must not expose a local exception or its message.
                self._result = CaptureResult.TRANSPORT
            finally:
                self.close()
        return self._result

    def close(self) -> None:
        self._initial = b""
        if self._result is None:
            self._result = CaptureResult.TRANSPORT
        with suppress(OSError):
            self._peer.close()


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
        except TimeoutError:
            initial = CaptureResult.TIMEOUT
        except Exception:
            initial = CaptureResult.TRANSPORT
        if isinstance(initial, CaptureResult):
            raise CaptureFailure(initial)
        capture = OutputCapture(peer, initial)
        del initial
        yield capture
    finally:
        if capture is None:
            with suppress(OSError):
                peer.close()
        else:
            capture.close()
