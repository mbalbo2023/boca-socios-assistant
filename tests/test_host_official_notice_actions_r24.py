"""Synthetic provenance/GO and non-actionable container import contracts.

No GitHub download, Docker, SSH, site request, real /data or token is used.
"""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_official_notice_actions as actions
from boca_socios.events.host_official_notice_import import OfficialImportReceipt


def _coords() -> actions.OfficialImportCoordinates:
    return actions.OfficialImportCoordinates(
        main_sha="a" * 40,
        controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        controller_release_run_id="42031822994",
        controller_id="c" * 64,
        source_run_id="42029320757",
        source_head_sha="d" * 40,
        artifact_id="13414624349",
        artifact_sha256="e" * 64,
        snapshot_sha256="f" * 64,
        source_sha256="1" * 64,
        observed_at_utc="2026-11-05T12:41:50.606388+00:00",
    )


def _source_run() -> dict[str, object]:
    return {
        "id": 42029320757,
        "workflow_id": 407700710,
        "event": "pull_request",
        "conclusion": "success",
        "head_sha": "d" * 40,
        "repository": {"id": 1437453367},
        "head_repository": {"id": 1437453367},
    }


def _artifact() -> dict[str, object]:
    return {
        "id": 13414624349,
        "name": "boca-official-news-receipt-42029320757",
        "expired": False,
        "digest": "sha256:" + "e" * 64,
        "size_in_bytes": 1400,
        "workflow_run": {
            "id": 42029320757,
            "repository_id": 1437453367,
            "head_repository_id": 1437453367,
            "head_sha": "d" * 40,
        },
    }


def _approved(coords: actions.OfficialImportCoordinates) -> str:
    return actions.expected_go_sha256(coords, operation_run_id="500001", actor="mbalbo2023")


def test_go_binding_is_opaque_exact_and_run_specific() -> None:
    coords = _coords()
    approved = _approved(coords)
    assert len(approved) == 64
    assert approved != actions.expected_go_sha256(
        coords, operation_run_id="500002", actor="mbalbo2023"
    )
    assert approved != actions.expected_go_sha256(
        replace(coords, artifact_sha256="9" * 64),
        operation_run_id="500001",
        actor="mbalbo2023",
    )
    with pytest.raises(actions.OfficialImportActionError, match="actor"):
        actions.expected_go_sha256(coords, operation_run_id="500001", actor="outsider")


def test_token_roundtrip_requires_canonical_base64_and_exact_fields() -> None:
    coords = _coords()
    token = actions.encode_coordinates(coords)
    assert actions.decode_coordinates(token) == coords
    for invalid in (token + "=", token + "!", "", "A" * 5000):
        with pytest.raises(actions.OfficialImportActionError):
            actions.decode_coordinates(invalid)
    decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    decoded["unreviewed"] = "other"
    forged = actions.encode_raw(actions._canonical(decoded))
    with pytest.raises(actions.OfficialImportActionError, match="canonical"):
        actions.decode_coordinates(forged)


@pytest.mark.parametrize(
    "field,value",
    (
        ("main_sha", "not-a-sha"),
        ("controller_id", "boca-socios-controller-1"),
        ("controller_image", "busybox:latest"),
        ("source_run_id", "0"),
        ("artifact_id", "../etc/passwd"),
        ("observed_at_utc", "yesterday"),
    ),
)
def test_unreviewed_coordinates_rejected(field: str, value: str) -> None:
    with pytest.raises(actions.OfficialImportActionError):
        actions.OfficialImportCoordinates(
            **{**vars(_coords()), field: value},  # type: ignore[arg-type]
        )


def test_runner_requires_independent_go_before_any_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        pytest.fail("artifact must not be inspected before separate GO")

    monkeypatch.setattr(actions, "_verified_jsonl", forbidden)
    with pytest.raises(actions.OfficialImportActionError, match="independent"):
        actions.verify_artifact_from_github(
            _coords(),
            source_run=_source_run(),
            artifact=_artifact(),
            archive=b"zip",
            independent_go_sha256="",
            operation_run_id="500001",
            actor="mbalbo2023",
        )


@pytest.mark.parametrize(
    "kind,change",
    (
        ("source", ("workflow_id", 1)),
        ("source", ("head_sha", "0" * 40)),
        ("source", ("event", "workflow_dispatch")),
        ("source", ("repository", "malformed")),
        ("artifact", ("expired", True)),
        ("artifact", ("digest", "sha256:" + "0" * 64)),
        ("artifact", ("id", 7)),
        ("artifact", ("workflow_run", "not-an-object")),
    ),
)
def test_runner_refuses_mismatched_github_identity(
    monkeypatch: pytest.MonkeyPatch, kind: str, change: tuple[str, object]
) -> None:
    monkeypatch.setattr(actions, "_verified_jsonl", lambda *_args: b"synthetic")
    run, artifact = _source_run(), _artifact()
    target = run if kind == "source" else artifact
    target[change[0]] = change[1]
    with pytest.raises(actions.OfficialImportActionError, match="GitHub source"):
        actions.verify_artifact_from_github(
            _coords(),
            source_run=run,
            artifact=artifact,
            archive=b"zip",
            independent_go_sha256=_approved(_coords()),
            operation_run_id="500001",
            actor="mbalbo2023",
        )


def test_runner_accepts_only_reviewed_artifact_bytes_and_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bytes] = []

    def accept(payload: bytes, _pin: object) -> bytes:
        called.append(payload)
        return b"synthetic"

    monkeypatch.setattr(actions, "_verified_jsonl", accept)
    token = actions.verify_artifact_from_github(
        _coords(),
        source_run=_source_run(),
        artifact=_artifact(),
        archive=b"test ZIP bytes, not opened in this unit test",
        independent_go_sha256=_approved(_coords()),
        operation_run_id="500001",
        actor="mbalbo2023",
    )
    assert actions.decode_coordinates(token) == _coords()
    assert called == [b"test ZIP bytes, not opened in this unit test"]


def test_container_import_rejects_non_boca_uid_before_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actions.os, "geteuid", lambda: 1000)
    with pytest.raises(actions.OfficialImportActionError, match="UID"):
        actions.import_from_container_stdin(_coords(), b"fake")


def test_container_import_receipt_preserves_data_and_never_promotes_tickets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actions.os, "geteuid", lambda: 10001)

    def fake(*_args: object, **_kwargs: object) -> OfficialImportReceipt:
        return OfficialImportReceipt(
            outcome="CREATED",
            artifact_sha256="e" * 64,
            snapshot_sha256="f" * 64,
            source_url=actions.OFFICIAL_NEWS_URL,
            source_sha256="1" * 64,
            observed_at_utc=_coords().observed_at_utc,
        )

    monkeypatch.setattr(actions, "import_reviewed_official_artifact", fake)
    receipt = actions.import_from_container_stdin(_coords(), b"synthetic")
    assert receipt.startswith("BOCA_OFFICIAL_IMPORT state=CREATED")
    assert "actionable=false" in receipt
    assert "readback=PASS" in receipt
    assert "data=preserved" in receipt


def _runner_env(monkeypatch: pytest.MonkeyPatch, coords: actions.OfficialImportCoordinates) -> None:
    for name, value in (
        ("BOCA_SOURCE_SHA", coords.main_sha),
        ("BOCA_IMAGE_REF", coords.controller_image),
        ("BOCA_RELEASE_RUN_ID", coords.controller_release_run_id),
        ("BOCA_OFFICIAL_CONTROLLER_ID", coords.controller_id),
        ("BOCA_OFFICIAL_NEWS_RUN_ID", coords.source_run_id),
        ("BOCA_OFFICIAL_NEWS_SOURCE_SHA", coords.source_head_sha),
        ("BOCA_OFFICIAL_NEWS_ARTIFACT_ID", coords.artifact_id),
        ("BOCA_OFFICIAL_NEWS_ZIP_SHA256", coords.artifact_sha256),
        ("BOCA_OFFICIAL_NEWS_JSONL_SHA256", coords.snapshot_sha256),
        ("BOCA_OFFICIAL_NEWS_HTML_SHA256", coords.source_sha256),
        ("BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC", coords.observed_at_utc),
        ("GITHUB_RUN_ID", "500001"),
        ("GITHUB_ACTOR", "mbalbo2023"),
        ("BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256", _approved(coords)),
    ):
        monkeypatch.setenv(name, value)


def test_runner_cli_proves_metadata_and_writes_only_o_excl_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coords = _coords()
    _runner_env(monkeypatch, coords)
    monkeypatch.setattr(actions, "_verified_jsonl", lambda *_args: b"synthetic")
    source = tmp_path / "source.json"
    artifact = tmp_path / "artifact.json"
    archive = tmp_path / "archive.zip"
    token = tmp_path / "token"
    source.write_text(json.dumps(_source_run()), encoding="utf-8")
    artifact.write_text(json.dumps(_artifact()), encoding="utf-8")
    archive.write_bytes(b"synthetic artifact")
    argv = ["program", "runner-preflight", str(source), str(artifact), str(archive), str(token)]
    assert actions._run_cli(argv) == 0
    assert actions.decode_coordinates(token.read_text(encoding="ascii").strip()) == coords
    assert token.stat().st_mode & 0o777 == 0o600
    with pytest.raises(actions.OfficialImportActionError, match="write"):
        actions._run_cli(argv)


def test_runner_receipt_assertion_is_exact_and_fails_on_lost_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coords = _coords()
    _runner_env(monkeypatch, coords)
    receipt = tmp_path / "receipt"
    monkeypatch.setenv("BOCA_OFFICIAL_IMPORT_PREFLIGHT", "success")
    monkeypatch.setenv("BOCA_OFFICIAL_IMPORT_HOST_APPLY", "success")
    receipt.write_text(
        "BOCA_OFFICIAL_IMPORT state=CREATED "
        f"main_sha={coords.main_sha} artifact_sha256={coords.artifact_sha256} "
        f"snapshot_sha256={coords.snapshot_sha256} windows=5 actionable=false "
        "data=preserved readback=PASS\n",
        encoding="ascii",
    )
    argv = ["program", "assert-host-receipt", str(receipt)]
    assert actions._run_cli(argv) == 0
    monkeypatch.setenv("BOCA_OFFICIAL_IMPORT_HOST_APPLY", "failure")
    with pytest.raises(actions.OfficialImportActionError, match="outcome"):
        actions._run_cli(argv)
    monkeypatch.setenv("BOCA_OFFICIAL_IMPORT_HOST_APPLY", "success")
    receipt.write_text(receipt.read_text(encoding="ascii").replace("CREATED", "REPLACED"))
    with pytest.raises(actions.OfficialImportActionError, match="identity"):
        actions._run_cli(argv)


def test_official_prepared_context_binds_known_prepare_not_unknown_apply_run() -> None:
    coords = _coords()
    prepared = actions.official_prepared_context_sha256(
        coords, prepare_run_id="50000000001", actor="mbalbo2023"
    )
    assert len(prepared) == 64
    assert prepared != actions.expected_go_sha256(
        coords, operation_run_id="50000000001", actor="mbalbo2023"
    )
    assert (
        actions.official_prepared_context_sha256(
            coords, prepare_run_id="50000000001", actor="mbalbo2023"
        )
        == prepared
    )
    assert (
        actions.official_prepared_context_sha256(
            coords, prepare_run_id="50000000002", actor="mbalbo2023"
        )
        != prepared
    )
    assert (
        actions.official_prepared_context_sha256(
            replace(coords, artifact_sha256="9" * 64),
            prepare_run_id="50000000001",
            actor="mbalbo2023",
        )
        != prepared
    )
    with pytest.raises(actions.OfficialImportActionError):
        actions.official_prepared_context_sha256(coords, prepare_run_id="0", actor="mbalbo2023")
    with pytest.raises(actions.OfficialImportActionError):
        actions.official_prepared_context_sha256(
            coords, prepare_run_id="50000000001", actor="outsider"
        )
    # A PREPARE context is never a legacy single-run GO approval.
    assert prepared != _approved(coords)


def test_prepared_import_go_o_excl_survives_crash_and_refuses_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from boca_socios.events.host_official_notice_import import OfficialImportError

    tmp_path.chmod(0o700)
    monkeypatch.setattr(actions, "_DATA", tmp_path)
    monkeypatch.setattr(actions.os, "geteuid", lambda: 10_001)
    monkeypatch.setattr(actions, "_verified_jsonl", lambda *_args: b"synthetic")
    writes: list[int] = []

    def broken_import(*_args: object, **_kwargs: object) -> object:
        writes.append(1)
        raise OfficialImportError("synthetic crash after prepared marker")

    monkeypatch.setattr(actions, "import_reviewed_official_artifact", broken_import)
    with pytest.raises(actions.OfficialImportActionError):
        actions.import_from_container_stdin(
            _coords(),
            b"fake-reviewed-zip",
            data_dir=tmp_path,
            prepare_run_id="50000000001",
        )
    marker = tmp_path / ".boca-official-import-go-50000000001.json"
    assert marker.is_file()
    assert marker.stat().st_mode & 0o777 == 0o600
    assert writes == [1]
    with pytest.raises(actions.OfficialImportActionError, match="consumed"):
        actions.import_from_container_stdin(
            _coords(),
            b"fake-reviewed-zip",
            data_dir=tmp_path,
            prepare_run_id="50000000001",
        )
    assert writes == [1]



def test_prepared_official_runner_preflight_and_host_command_are_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    from datetime import UTC, datetime, timedelta

    coords = _coords()
    runner = tmp_path / "runner"
    runner.mkdir()
    archive = b"synthetic reviewed ZIP; import never executed"
    zip_path = runner / "boca-official-source.zip"
    zip_path.write_bytes(archive)
    release_path = runner / "boca-release-manifest/boca-release-manifest.json"
    browser_path = runner / "boca-browser-release-manifest/boca-browser-release-manifest.json"
    release_path.parent.mkdir()
    browser_path.parent.mkdir()
    release_path.write_bytes(b"reviewed controller manifest")
    browser_path.write_bytes(b"reviewed browser manifest")
    approved_run = runner / "source-run.json"
    approved_artifact = runner / "source-artifact.json"
    approved_run.write_text(json.dumps(_source_run()), encoding="ascii")
    approved_artifact.write_text(json.dumps(_artifact()), encoding="ascii")
    token_path = runner / "reviewed-import.token"
    monkeypatch.setattr(actions, "_coords_from_env", lambda: coords)
    monkeypatch.setattr(actions, "_verified_jsonl", lambda *_args: b"synthetic")
    prepare_id = "42053482614"
    now = datetime.now(UTC).replace(microsecond=0)
    env = {
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": coords.main_sha,
        "BOCA_SOURCE_SHA": coords.main_sha,
        "GITHUB_RUN_ID": "42055559999",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "BOCA_OPERATION": "official-notice-import",
        "BOCA_BETA_OWNER_SUBJECT": "owner",
        "BOCA_RELEASE_RUN_ID": coords.controller_release_run_id,
        "RUNNER_TEMP": str(runner),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    record = {
        "version": "boca-protected-prepared-go-v1",
        "operation": "official-notice-import",
        "repository": env["GITHUB_REPOSITORY"],
        "actor": env["GITHUB_ACTOR"],
        "ref": env["GITHUB_REF"],
        "source_sha": coords.main_sha,
        "release_run_id": coords.controller_release_run_id,
        "prepare_run_id": prepare_id,
        "prepare_attempt": "1",
        "prepared_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until_utc": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public_context_sha256": actions.official_prepared_context_sha256(
            coords, prepare_run_id=prepare_id, actor="mbalbo2023"
        ),
        "release_manifest_sha256": hashlib.sha256(release_path.read_bytes()).hexdigest(),
        "browser_manifest_sha256": hashlib.sha256(browser_path.read_bytes()).hexdigest(),
        "bundle_sha256": hashlib.sha256(archive).hexdigest(),
        "owner_subject_sha256": hashlib.sha256(b"owner").hexdigest(),
    }
    raw = actions._canonical(record)
    approval = hashlib.sha256(
        b"boca-official-notice-import-prepared-go-v1:\x00" + raw
    ).hexdigest()
    monkeypatch.setenv("BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256", approval)
    for name, value in {
        "boca-protected-legacy-go.approved": (approval + "\n").encode("ascii"),
        "boca-protected-legacy-go.prepare-id": (prepare_id + "\n").encode("ascii"),
        "boca-protected-legacy-go.receipt.json": raw,
    }.items():
        path = runner / name
        path.write_bytes(value)
        path.chmod(0o600)
    assert actions._runner_preflight_prepared(
        ["official", "runner-preflight-prepared", str(approved_run), str(approved_artifact), str(zip_path), str(token_path)]
    ) == 0
    assert actions.decode_coordinates(token_path.read_text(encoding="ascii").strip()) == coords
    assert actions._runner_host_command_prepared(
        ["official", "runner-host-command-prepared", str(token_path), str(zip_path)]
    ) == 0
    assert "container-import-prepared" in capsys.readouterr().out


def test_prepared_official_runner_rejects_missing_go_before_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions, "_coords_from_env", lambda: _coords())
    monkeypatch.setattr(
        actions, "_verified_jsonl", lambda *_args: pytest.fail("source must remain untouched")
    )
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    with pytest.raises(actions.OfficialImportActionError):
        actions._runner_preflight_prepared(
            ["official", "runner-preflight-prepared", "/abs/run.json", "/abs/artifact.json", "/abs/archive.zip", str(tmp_path / "token")]
        )
    assert not (tmp_path / "token").exists()
