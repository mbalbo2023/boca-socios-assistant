"""Synthetic registry artifact, without a registry image or repository filesystem data."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

import pytest
from scripts import lab_image_recovery_916 as lab


def test_ephemeral_registry_only_serves_its_exact_manifest_and_harmless_layer():
    get = build_opener(ProxyHandler({})).open
    with lab.fixture_registry() as (ref, config_id):
        repo, digest = ref.split("@")
        address, name = repo.split("/", 1)
        base = f"http://{address}/v2/{name}"
        with get(f"{base}/manifests/{digest}", timeout=2) as response:
            manifest = response.read()
            assert response.headers["Docker-Content-Digest"] == digest
        assert "sha256:" + hashlib.sha256(manifest).hexdigest() == digest
        parsed = json.loads(manifest)
        config, layer = parsed["config"], parsed["layers"][0]
        assert config["digest"] == config_id
        for desc in (config, layer):
            with get(base + "/blobs/" + desc["digest"], timeout=2) as response:
                data = response.read()
                assert len(data) == desc["size"]
                assert desc["digest"] == "sha256:" + hashlib.sha256(data).hexdigest()
                if desc == config:
                    image_config = json.loads(data)
                else:
                    raw = gzip.decompress(data)
                    with tarfile.open(fileobj=io.BytesIO(raw)) as content:
                        assert content.getnames() == ["fixture.txt"]
                        assert content.extractfile("fixture.txt").read() == b"disposable\n"
        assert (
            image_config["config"]["Labels"]["org.opencontainers.image.source"]
            == lab.recovery.cleanup.BOCA_SOURCE
        )
        assert image_config["rootfs"]["diff_ids"] == ["sha256:" + hashlib.sha256(raw).hexdigest()]
        with pytest.raises(HTTPError) as unavailable:
            get(f"http://{address}/v2/unrelated/manifests/{digest}", timeout=2)
        assert unavailable.value.code == 404


@pytest.mark.parametrize("stdout", [b"", b"\n"])
def test_missing_response_accepts_only_exact_reference_strict_return_code_and_output(stdout):
    import subprocess

    ref = "127.0.0.1:5000/fixture@sha256:" + "a" * 64
    err = f"Error response from daemon: No such image: {ref}\n".encode()
    assert lab.absence_shape(subprocess.CompletedProcess([], 1, stdout, err), ref) in (
        "EMPTY",
        "LF",
    )
    for code, out, stderr in [
        (0, stdout, err),
        (1, b"\n\n", err),
        (1, b"[]\n", err),
        (1, stdout, err + b"private\n"),
        (1, stdout, err.replace(b"/fixture", b"/foreign")),
    ]:
        with pytest.raises(lab.LabError):
            lab.absence_shape(subprocess.CompletedProcess([], code, out, stderr), ref)


@pytest.mark.parametrize(
    ("remained", "by_manifest", "orphan"),
    [
        (True, False, False),
        (False, True, False),
        (True, True, True),
        (False, False, True),
    ],
)
def test_remove_by_full_id_rechecks_the_production_plan_and_both_censuses(
    remained, by_manifest, orphan
):
    from subprocess import CompletedProcess

    config_id = "sha256:" + "a" * 64
    digest = "sha256:" + "b" * 64
    ident = digest if by_manifest else config_id
    ref = "127.0.0.1:5000/boca-r916@" + digest
    repo = ref.split("@")[0]
    present = remained
    calls = []

    def docker(*args):
        nonlocal present
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            key, template = args[-1], args[-2]
            if not present:
                assert key == ref
                return CompletedProcess(
                    args, 1, b"\n", f"Error response from daemon: No such image: {ref}\n".encode()
                )
            assert key in (ref, ident)
            value = {
                "{{json .Id}}": ident,
                "{{json .RepoTags}}": [],
                "{{json .RepoDigests}}": [ref],
                lab.recovery._LABEL_FMT916["source"]: lab.recovery.cleanup.BOCA_SOURCE,
                lab.recovery._LABEL_FMT916["revision"]: lab.recovery.SOURCE,
            }[template]
            return CompletedProcess(args, 0, json.dumps(value).encode() + b"\n", b"")
        if args == (
            "image",
            "ls",
            "--all",
            "--digests",
            "--no-trunc",
            "--format",
            lab.recovery._LIST916,
            repo,
        ):
            assert not present
            return CompletedProcess(args, 0, b"", b"")
        if args == ("image", "ls", "--all", "--quiet", "--no-trunc"):
            assert not present
            return CompletedProcess(args, 0, (ident + "\n").encode() if orphan else b"", b"")
        if args == ("ps", "-a", "-q", "--no-trunc", "--filter", "ancestor=" + ident):
            return CompletedProcess(args, 0, b"", b"")
        if args == ("pull", "--platform", "linux/amd64", ref):
            assert not present
            present = True
        elif args == ("image", "rm", "--no-prune", ident):
            assert present
            present = False
        else:
            pytest.fail("Unexpected Docker command")
        return CompletedProcess(args, 0, b"", b"")

    if orphan:
        with pytest.raises(lab.LabError, match="^POST_DELETE_ID$"):
            lab.remove_fixture_by_id(docker, ref, config_id, ident)
    else:
        lab.remove_fixture_by_id(docker, ref, config_id, ident)
    assert calls.count(("pull", "--platform", "linux/amd64", ref)) == int(not remained)
    assert calls.count(("image", "rm", "--no-prune", ident)) == 1
    assert calls.count(("image", "ls", "--all", "--quiet", "--no-trunc")) == (1 if orphan else 2)
