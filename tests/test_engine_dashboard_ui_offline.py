"""Offline visual evidence must stay tied to fixed fixtures and the candidate SHA."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import zlib
from urllib.parse import urlencode

import pytest

SOURCE_SHA = "a" * 40


def _module():
    from scripts import run_engine_dashboard_ui_offline_chromium

    return run_engine_dashboard_ui_offline_chromium


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\xff\xff" * width) * height))
        + chunk(b"IEND", b"")
    )


def _capture(module, fixture):
    return {
        "schema": 1,
        "mode": "OFFLINE_SYNTHETIC_ENGINE_UI",
        "source_sha": SOURCE_SHA,
        "fixture_sha256": module.fixture_digest(fixture),
        "state": "PASS",
        "network": "none",
        "host_checked": False,
        "physical_device_checked": False,
        "viewports": [
            {
                "width": width,
                "height": height,
                "document_requests": 1,
                "snapshot_requests": 4,
                "native_posts": list(module.POST_ORDER),
                "other_requests": 0,
                "page_errors": 0,
                "checks": dict.fromkeys(module.CHECKS, True),
                "png_base64": base64.b64encode(_png(width, height)).decode("ascii"),
            }
            for width, height, _ in module.VIEWPORTS
        ],
    }


def test_fixed_fixture_uses_actual_renderer_and_ignores_runtime_environment(monkeypatch):
    module = _module()
    from boca_socios.panel import engine_view

    rendered = []
    original = engine_view.page

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        rendered.append(result)
        return result

    monkeypatch.setattr(engine_view, "page", record)
    fixture = module.make_fixture(SOURCE_SHA)
    monkeypatch.setenv("BOCA_DB_PATH", "/must-not-open/runtime.sqlite3")
    monkeypatch.setenv("BOCA_SITE_URL", "https://must-not-contact.invalid/private")
    monkeypatch.setenv("BOCA_OWNER_SUBJECT", "must-not-appear-in-artifact")
    assert module.make_fixture(SOURCE_SHA) == fixture
    assert fixture["html"] == rendered[0].decode("utf-8")
    assert fixture["csp"] == engine_view.csp()
    assert fixture["html_sha256"] == hashlib.sha256(rendered[0]).hexdigest()
    assert "must-not-" not in json.dumps(fixture)
    module.validate_fixture(fixture, SOURCE_SHA)


@pytest.mark.parametrize("change", ["source", "token", "url", "html", "extra"])
def test_fixture_rejects_source_drift_private_metadata_and_unreviewed_inputs(change):
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    if change == "source":
        fixture["source_sha"] = "b" * 40
    elif change == "token":
        fixture["snapshots"][1]["engines"][0]["sessions"][0]["access_token"] = "forbidden"
    elif change == "url":
        fixture["snapshots"][1]["engines"][0]["sessions"][0]["display_url"] += "?pass=forbidden"
    elif change == "html":
        fixture["html"] += "<p>unexpected</p>"
    else:
        fixture["database"] = "/runtime.sqlite3"
    with pytest.raises(ValueError):
        module.validate_fixture(fixture, SOURCE_SHA)


def test_native_post_requires_exact_origin_fields_and_engine_fence():
    module = _module()
    for operation in module.POST_ORDER:
        url = module.post_url(operation)
        fields = module.expected_post_fields(operation)
        assert module.verify_post(url, module.ORIGIN, urlencode(fields)) == operation
        for origin in (None, "null", "https://other.invalid", module.ORIGIN + "/"):
            with pytest.raises(ValueError):
                module.verify_post(url, origin, urlencode(fields))
        with pytest.raises(ValueError):
            module.verify_post(url, module.ORIGIN, urlencode(fields) + "&csrf=duplicate")
        with pytest.raises(ValueError):
            module.verify_post(url + "?unexpected=1", module.ORIGIN, urlencode(fields))

    fields = module.expected_post_fields("queues_tokens:stop")
    other = module.expected_post_fields("browsers_members:stop")
    fields["activation_id"] = other["activation_id"]
    with pytest.raises(ValueError):
        module.verify_post(module.post_url("queues_tokens:stop"), module.ORIGIN, urlencode(fields))
    fields = module.expected_post_fields("browsers_members:start")
    fields.pop("member_id")
    with pytest.raises(ValueError):
        module.verify_post(
            module.post_url("browsers_members:start"), module.ORIGIN, urlencode(fields)
        )


def test_verified_capture_writes_only_bounded_named_pngs_and_public_report(tmp_path):
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    capture = _capture(module, fixture)
    destination = tmp_path / "artifacts"
    report = module.write_artifacts(capture, fixture, SOURCE_SHA, destination)
    assert {path.name for path in destination.iterdir()} == {
        "engines-tablet-800x1280.png",
        "engines-mobile-412x915.png",
        "report.json",
    }
    assert report["source_sha"] == SOURCE_SHA
    assert report["host_checked"] is report["physical_device_checked"] is False
    assert report["html_sha256"] == fixture["html_sha256"]
    assert "png_base64" not in (destination / "report.json").read_text()
    for view in report["viewports"]:
        raw = (destination / view["screenshot"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == view["screenshot_sha256"]
        assert len(raw) == view["screenshot_bytes"]


@pytest.mark.parametrize("change", ["sha", "fixture", "check", "post", "network", "png", "extra"])
def test_capture_rejects_unproven_or_tampered_evidence_before_creating_artifacts(tmp_path, change):
    module = _module()
    fixture = module.make_fixture(SOURCE_SHA)
    capture = _capture(module, fixture)
    if change == "sha":
        capture["source_sha"] = "b" * 40
    elif change == "fixture":
        capture["fixture_sha256"] = "0" * 64
    elif change == "check":
        capture["viewports"][0]["checks"][module.CHECKS[0]] = False
    elif change == "post":
        capture["viewports"][0]["native_posts"].pop()
    elif change == "network":
        capture["viewports"][0]["other_requests"] = 1
    elif change == "png":
        capture["viewports"][0]["png_base64"] = base64.b64encode(_png(1, 1)).decode()
    else:
        capture["viewports"][0]["screenshot"] = "../../escape.png"
    destination = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        module.write_artifacts(capture, fixture, SOURCE_SHA, destination)
    assert not destination.exists()


def test_cli_failure_does_not_print_fixture_contents_or_create_an_output(tmp_path, capsys):
    module = _module()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"unexpected": "private-content-must-not-be-logged"}))
    output = tmp_path / "output"
    assert module.main(["--verify-capture", str(bad), str(bad), SOURCE_SHA, str(output)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-content" not in captured.err
    assert "NO_GO" in captured.err
    assert not output.exists()
