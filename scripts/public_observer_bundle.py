"""Fixed capture contract and bounded private transfer; no network operations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO

from .observe_public_home import CHALLENGE_MARKERS, HOST

ORIGIN = f"https://{HOST}"
LOGIN_PATH = "/auth/login"
TOTAL_LIMIT = 12 * 1024 * 1024
ENCODED_LIMIT = 17 * 1024 * 1024
PRIVATE_DIR = Path("/tmp/boca-public-capture")  # noqa: S108 - exclusive 0700 in private container tmpfs
BUNDLE_PATH = PRIVATE_DIR / "bundle.json"
ASSETS = (
    "/_next/static/css/110f3266bb0e84b9.css",
    "/_next/static/media/ed68d641ffbc51c9-s.p.ttf",
    "/_next/static/media/c5521e49e0ab5d76-s.p.ttf",
    "/_next/static/media/d5b340b61a9d747a-s.p.ttf",
    "/_next/static/media/542b704cac92f33f-s.p.ttf",
    "/_next/static/media/9079e785e8d9e991-s.p.ttf",
    "/_next/static/media/309b60d940dcc6d8-s.p.ttf",
    "/_next/static/chunks/polyfills-42372ed130431b0a.js",
    "/_next/static/chunks/webpack-ccfdb9bd91362889.js",
    "/_next/static/chunks/framework-d1ea9e652f7756a8.js",
    "/_next/static/chunks/main-2bcb7c5cd03d4c7a.js",
    "/_next/static/chunks/pages/_app-e24083c41ff8470e.js",
    "/_next/static/chunks/9819-2c4a72013c59320c.js",
    "/_next/static/chunks/2739-6943ce35cb75f338.js",
    "/_next/static/chunks/4860-acdc20894c93fa01.js",
    "/_next/static/chunks/83-a1c7ae20bcf7e033.js",
    "/_next/static/chunks/5326-c518c1546ef3384f.js",
    "/_next/static/chunks/3955-5547d64248c3c4c2.js",
    "/_next/static/chunks/7216-4aebbb51b60525b0.js",
    "/_next/static/chunks/7243-ddb1335e09b2ad50.js",
    "/_next/static/chunks/7507-47dcca8ca6668a7a.js",
    "/_next/static/chunks/pages/auth/login-148f8537fd25f3f5.js",
    "/_next/static/ZjtPdUbA-bZTrUy51xKDH/_buildManifest.js",
    "/_next/static/ZjtPdUbA-bZTrUy51xKDH/_ssgManifest.js",
)


def contract(path: str) -> tuple[int, str]:
    if path == LOGIN_PATH:
        return 1024 * 1024, "text/html"
    if path not in ASSETS:
        raise ValueError("unapproved path")
    if path.endswith(".js"):
        return 2 * 1024 * 1024, "text/javascript"
    if path.endswith(".css"):
        return 512 * 1024, "text/css"
    return 1024 * 1024, "font/ttf"


def raw_path(raw: str) -> str:
    """Compare literal URLs, never erase queries/fragments or normalize a new URL."""
    path = raw[len(ORIGIN) :] if raw.startswith(ORIGIN + "/") else raw
    if path not in (*ASSETS, "/", "/favicon.ico"):
        raise ValueError("unapproved reference")
    return path


class Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: set[str] = set()
        self.count = 0
        self.text: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.suppressed += 1
        names = [name for name, _ in attrs]
        if len(names) != len(set(names)):
            raise ValueError("duplicate attributes")
        values = dict(attrs)
        if tag in {"base", "iframe", "frame", "object", "embed"} or (
            tag == "meta" and values.get("http-equiv", "").casefold() == "refresh"
        ):
            raise ValueError("active navigation")
        if any(name in values for name in ("srcset", "imagesrcset", "ping")):
            raise ValueError("alternate resource")
        for name in ("src", "poster", "data"):
            if name in values:
                self.reference(values[name])
        if tag == "link" and "href" in values:
            self.reference(values["href"])

    def reference(self, value: str | None) -> None:
        self.count += 1
        if value is None or self.count > 64:
            raise ValueError("reference limit")
        path = raw_path(value)
        if path in ASSETS:
            self.found.add(path)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.text.append(data)


def inventory(body: bytes) -> tuple[str, ...]:
    if not body or len(body) > contract(LOGIN_PATH)[0]:
        raise ValueError("document size")
    parser = Inventory()
    parser.feed(body.decode("utf-8"))
    parser.close()
    text = " ".join(parser.text).casefold()
    if any(marker in text for marker in CHALLENGE_MARKERS):
        raise ValueError("challenge")
    # Conservative exact publication match; never fetch stale or new references.
    if parser.found != set(ASSETS):
        raise ValueError("publication inventory changed")
    return ASSETS


def entry(path: str, body: bytes) -> dict[str, str]:
    maximum, mime = contract(path)
    if not body or len(body) > maximum:
        raise ValueError("body size")
    return {
        "path": path,
        "mime": mime,
        "sha256": hashlib.sha256(body).hexdigest(),
        "body": base64.b64encode(body).decode("ascii"),
    }


def validate_bundle(value: object, *, fixture: bool) -> dict:
    if not isinstance(value, dict) or set(value) != {"mode", "entries"}:
        raise ValueError("bundle envelope")
    if value["mode"] != ("synthetic_fixture" if fixture else "public_capture"):
        raise ValueError("bundle provenance")
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) != 25:
        raise ValueError("bundle count")
    seen: set[str] = set()
    total = 0
    document = b""
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "mime", "sha256", "body"}:
            raise ValueError("bundle entry")
        if not all(isinstance(field, str) for field in item.values()):
            raise ValueError("bundle types")
        body = base64.b64decode(item["body"], validate=True)
        if item != entry(item["path"], body) or item["path"] in seen:
            raise ValueError("bundle integrity")
        seen.add(item["path"])
        total += len(body)
        if total > TOTAL_LIMIT:
            raise ValueError("bundle total")
        if item["path"] == LOGIN_PATH:
            document = body
    if seen != {LOGIN_PATH, *ASSETS}:
        raise ValueError("bundle paths")
    inventory(document)
    return value


def encode_bundle(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("ascii")


def decode_bundle(stream: BinaryIO, *, fixture: bool) -> dict:
    raw = stream.read(ENCODED_LIMIT + 1)
    if len(raw) > ENCODED_LIMIT:
        raise ValueError("transfer size")
    return validate_bundle(json.loads(raw), fixture=fixture)


def save_bundle(value: dict, *, fixture: bool) -> None:
    validate_bundle(value, fixture=fixture)
    PRIVATE_DIR.mkdir(mode=0o700)
    descriptor = os.open(BUNDLE_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encode_bundle(value))


def open_bundle() -> BinaryIO:
    parent = PRIVATE_DIR.lstat()
    if not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError("private directory")
    descriptor = os.open(BUNDLE_PATH, os.O_RDONLY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size > ENCODED_LIMIT
    ):
        os.close(descriptor)
        raise ValueError("private bundle")
    return os.fdopen(descriptor, "rb")


def remove_bundle() -> None:
    BUNDLE_PATH.unlink(missing_ok=True)
    if PRIVATE_DIR.exists():
        PRIVATE_DIR.rmdir()


def fixture_bundle() -> dict:
    """Fixed synthetic bytes for offline CI; impossible to label as a public capture."""
    refs = "".join(
        f'<script src="{path}"></script>'
        if path.endswith(".js")
        else f'<link href="{path}" rel="stylesheet">'
        if path.endswith(".css")
        else f'<link href="{path}" rel="alternate">'
        for path in ASSETS
    )
    body = (
        "<!doctype html><html><body>" + refs + '<div id="fixture-root"></div></body></html>'
    ).encode()
    entries = [entry(LOGIN_PATH, body)]
    for path in ASSETS:
        data = b"/* offline synthetic fixture */" if path.endswith((".js", ".css")) else b"font"
        if path == ASSETS[7]:
            data = (
                b'document.addEventListener("DOMContentLoaded", () => {'
                b'document.getElementById("fixture-root").innerHTML = '
                b'`<form><input type="email"><input type="password">'
                b'<button type="submit" disabled>Login</button></form>`;});'
            )
        entries.append(entry(path, data))
    return {"mode": "synthetic_fixture", "entries": entries}
