"""Exercise the production #916 image planner on the GitHub runner's disposable Docker."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from scripts import host_cutover_904_recovery as recovery

_SOCKET = Path("/var/run/docker.sock")
_REPO = "boca-r916"
_REGISTRY = "application/vnd.docker."
_MANIFEST = _REGISTRY + "distribution.manifest.v2+json"
_CONFIG = _REGISTRY + "container.image.v1+json"
_LAYER = _REGISTRY + "image.rootfs.diff.tar.gzip"


class LabError(ValueError):
    pass


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


@contextmanager
def fixture_registry() -> Iterator[tuple[str, str]]:
    """A read-only Distribution V2 fixture serves only its generated artifact on loopback."""
    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode="w") as archive:
        payload = b"disposable\n"
        entry = tarfile.TarInfo("fixture.txt")
        entry.size = len(payload)
        archive.addfile(entry, io.BytesIO(payload))
    raw = layer.getvalue()
    compressed = gzip.compress(raw, mtime=0)
    config = _json(
        {
            "architecture": "amd64",
            "os": "linux",
            "config": {
                "Cmd": ["/never-start-this-fixture"],
                "Labels": {
                    "org.opencontainers.image.source": recovery.cleanup.BOCA_SOURCE,
                    "org.opencontainers.image.revision": recovery.SOURCE,
                    "io.boca.disposable.fixture": uuid4().hex,
                },
            },
            "rootfs": {"type": "layers", "diff_ids": [_digest(raw)]},
            "history": [{"created_by": "Boca disposable CI fixture"}],
        }
    )

    def descriptor(kind: str, data: bytes) -> dict[str, object]:
        return {"mediaType": kind, "size": len(data), "digest": _digest(data)}

    manifest = _json(
        {
            "schemaVersion": 2,
            "mediaType": _MANIFEST,
            "config": descriptor(_CONFIG, config),
            "layers": [descriptor(_LAYER, compressed)],
        }
    )
    base = f"/v2/{_REPO}"
    resources = {
        "/v2/": ("application/json", b"{}"),
        f"{base}/manifests/{_digest(manifest)}": (_MANIFEST, manifest),
        f"{base}/blobs/{_digest(config)}": ("application/octet-stream", config),
        f"{base}/blobs/{_digest(compressed)}": ("application/octet-stream", compressed),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_HEAD(self) -> None:
            item = resources.get(unquote(urlsplit(self.path).path))
            if item is None:
                self.send_error(404)
                return
            mimetype, data = item
            self.send_response(200)
            self.send_header("Docker-Distribution-Api-Version", "registry/2.0")
            self.send_header("Docker-Content-Digest", _digest(data))
            self.send_header("Content-Type", mimetype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(data)

        do_GET = do_HEAD

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"127.0.0.1:{server.server_port}/{_REPO}@{_digest(manifest)}", _digest(config)
        finally:
            server.shutdown()
            thread.join()


def absence_shape(done: subprocess.CompletedProcess[bytes], ref: str) -> str:
    if not recovery.host._browser_missing_image_result(
        done.returncode, done.stdout, done.stderr, ref
    ):
        raise LabError("ABSENCE")
    return "LF" if done.stdout else "EMPTY"


def remove_fixture_by_id(docker: recovery.Docker916, ref: str, config_id: str, ident: str) -> None:
    permitted = frozenset((config_id, ref.split("@")[1]))
    if ident not in permitted:
        raise LabError("REMOVE_IDENTITY")

    def read() -> dict[str, object]:
        record = recovery.observe_image916(ref, docker=docker, expected_ids=permitted)
        if not isinstance(record, dict):
            raise LabError("REMOVE_PRECONDITION")
        return record

    current = read()
    if current["status"] == "ABSENT":
        # Removing the last tag can also remove its original digest from the store.
        if docker("pull", "--platform", "linux/amd64", ref).returncode:
            raise LabError("RESTORE_FIXTURE")
        current = read()
    if current["status"] != "REMOVABLE" or current["id"] != ident or read() != current:
        raise LabError("REMOVE_PRECONDITION")
    try:
        recovery._success916(
            recovery._call916(docker, "REMOVE", "image", "rm", "--no-prune", ident),
            "REMOVE",
        )
    except recovery._Fault916 as exc:
        raise LabError("REMOVE_ID") from exc
    # The production postcondition checks exact absence by repository and both
    # authored IDs in two complete local image inventories. Only the coordinates
    # of the disposable artifact and CLI transport differ from the real call.
    with (
        patch.dict(recovery._IMAGE_REFS916, {"fixture": ref}),
        patch.dict(recovery._RELEASE_IDS916, {"fixture": permitted}),
        patch.object(recovery, "_image_docker916", docker),
    ):
        observed = recovery._host_image916("fixture", ident)
    if observed["status"] != "ABSENT" or observed["id"] is not None:
        raise LabError("POST_DELETE_ID")


def run_fixture(tmp: str) -> None:
    def docker(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - fixed disposable runner daemon
            ["/usr/bin/docker", "--config", tmp, "--host", f"unix://{_SOCKET}", *args],
            capture_output=True,
            check=False,
            timeout=35,
        )

    def checked(step: str, *args: str) -> bytes:
        p = docker(*args)
        if p.returncode:
            raise LabError(step)
        return p.stdout

    def plan(
        ref: str, expected: str, *, mismatch: str | None = None, **provenance: str
    ) -> str | None:
        record = recovery.observe_image916(ref, docker=docker, **provenance)
        if (
            record["status"] != expected
            or mismatch is not None
            and (record["step"], record["reason"]) != (mismatch, "MISMATCH")
        ):
            raise LabError("PLANNER_" + expected)
        ident = record["id"]
        if ident is not None and not isinstance(ident, str):
            raise LabError("IDENTITY")
        return ident

    shapes = []
    for role in ("target_image_ref", "browser_image_ref"):
        missing = recovery.PINS[role]
        # Inspect only the ID until exact absence is proven. Preserve both channels as bytes.
        shapes.append(
            absence_shape(docker("image", "inspect", "--format", "{{json .Id}}", missing), missing)
        )
        if plan(missing, "ABSENT") is not None:
            raise LabError("ABSENCE")
        with patch.object(recovery.host, "ROOTLESS_SOCKET", _SOCKET):
            if not recovery.host._browser_image_absent(missing, recovery.SOURCE):
                raise LabError("LEGACY_ABSENCE")
    with fixture_registry() as (ref, config_id):
        repo, digest = ref.split("@")
        tag = repo + ":lab-keep"
        name = "boca-r916-" + uuid4().hex
        label = "io.boca.disposable.fixture=" + name
        ident = None
        try:
            checked("PULL", "pull", "--platform", "linux/amd64", ref)
            ident = plan(ref, "REMOVABLE")
            if not isinstance(ident, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", ident):
                raise LabError("IDENTITY")
            digests = json.loads(
                checked("IDENTITY", "image", "inspect", "--format", "{{json .RepoDigests}}", ident)
            )
            if (
                not isinstance(digests, list)
                or ref not in digests
                or set(digests) - {ref, "<none>@<none>"}
            ):
                raise LabError("IDENTITY")
            foreign = repo.rsplit("/", 1)[0] + "/different-repository@" + digest
            plan(foreign, "ABSENT")
            plan(ref, "UNKNOWN", mismatch="REVISION_LABEL", revision="f" * 40)
            plan(
                ref,
                "UNKNOWN",
                mismatch="SOURCE_LABEL",
                source=recovery.cleanup.BOCA_SOURCE + "-fixture",
            )
            cid = (
                checked(
                    "CREATE",
                    "create",
                    "--pull",
                    "never",
                    "--name",
                    name,
                    "--label",
                    label,
                    "--network",
                    "none",
                    ref,
                )
                .strip()
                .decode("ascii")
            )
            if not re.fullmatch(r"[0-9a-f]{64}", cid) or plan(ref, "RETAINED_REFERENCED") != ident:
                raise LabError("REFERENCED")
            if checked("REMOVE_CID", "container", "rm", cid).strip().decode("ascii") != cid:
                raise LabError("REMOVE_CID")
            if checked(
                "REMOVE_CID", "ps", "-a", "-q", "--no-trunc", "--filter", "id=" + cid
            ).strip():
                raise LabError("REMOVE_CID")
            if plan(ref, "REMOVABLE") != ident:
                raise LabError("REFERENCE_REMOVED")
            checked("ALIAS", "image", "tag", ref, tag)
            if plan(ref, "RETAINED_ALIAS") != ident:
                raise LabError("ALIAS")
            checked("REMOVE_ALIAS", "image", "rm", "--no-prune", tag)
            remove_fixture_by_id(docker, ref, config_id, ident)
        finally:
            matches = checked(
                "CLEANUP",
                "ps",
                "-a",
                "-q",
                "--no-trunc",
                "--filter",
                "name=^/" + name + "$",
                "--filter",
                "label=" + label,
            ).splitlines()
            if matches:
                if len(matches) != 1 or not re.fullmatch(rb"[0-9a-f]{64}", matches[0]):
                    raise LabError("CLEANUP")
                checked("CLEANUP", "container", "rm", matches[0].decode("ascii"))
            for item in (tag, ref):
                exists = docker("image", "inspect", "--format", "{{json .Id}}", item)
                if exists.returncode == 0:
                    checked("CLEANUP", "image", "rm", "--no-prune", item)
                absence_shape(docker("image", "inspect", "--format", "{{json .Id}}", item), item)
            if ident in (config_id, digest):
                ids = checked(
                    "CLEANUP", "image", "ls", "--all", "--quiet", "--no-trunc"
                ).splitlines()
                if ident.encode() in ids or ident.removeprefix("sha256:").encode() in ids:
                    for field, sentinel in (
                        ("RepoTags", "<none>:<none>"),
                        ("RepoDigests", "<none>@<none>"),
                    ):
                        names = json.loads(
                            checked(
                                "CLEANUP",
                                "image",
                                "inspect",
                                "--format",
                                "{{json ." + field + "}}",
                                ident,
                            )
                        )
                        if names not in (None, [], [sentinel]):
                            raise LabError("CLEANUP_ALIAS")
                    checked("CLEANUP", "image", "rm", "--no-prune", ident)
    print(
        f"BOCA_916_IMAGE_LAB state=PASS controller_missing={shapes[0]} worker_missing={shapes[1]} "
        "identity=VERIFIED foreign_repository=ABSENT source=CHECKED revision=CHECKED "
        "unreferenced=REMOVABLE alias=RETAINED referenced=RETAINED remove=BY_ID digest=ABSENT id=ABSENT cleanup=VERIFIED"
    )


def main() -> int:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("BOCA_LAB_RUNNER") != "github-hosted"
    ):
        return 3
    try:
        with TemporaryDirectory(prefix="boca-r916-") as tmp:
            run_fixture(tmp)
    except LabError as exc:
        print("BOCA_916_IMAGE_LAB state=FAIL step=" + str(exc), file=sys.stderr)
        return 3
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        recovery.host.PreflightError,
    ):
        print("BOCA_916_IMAGE_LAB state=FAIL step=TRANSPORT", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
