"""The real disposable harness accepts only reviewed exact-SHA image pairs."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
REPOSITORY = "mbalbo2023/boca-socios-assistant"
LEGACY = (f"boca-first-install-smoke:{SHA}", f"boca-browser-lifecycle-smoke:{SHA}")
CI = (f"boca-socios-ci:{SHA}", f"boca-browser-ci:{SHA}")


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "ci_identity_harness", ROOT / "scripts/check_browser_lifecycle_runtime.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "repository": {"full_name": REPOSITORY},
                "pull_request": {"head": {"repo": {"full_name": REPOSITORY}}},
            }
        )
    )
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "mbalbo2023",
        "BOCA_IMAGE": LEGACY[0],
        "BOCA_BROWSER_IMAGE": LEGACY[1],
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(module.sys, "argv", ["probe", "acceptance", "c" * 64])
    return module, event


@pytest.mark.parametrize("pair", [LEGACY, CI])
@pytest.mark.parametrize(
    ("event", "actor"),
    [
        ("pull_request", "mbalbo2023"),
        ("push", "mbalbo2023"),
        ("push", "integration[bot]"),
        ("workflow_dispatch", "mbalbo2023"),
    ],
)
def test_both_exact_image_families_reach_real_inspect_boundary(
    harness, monkeypatch: pytest.MonkeyPatch, pair: tuple[str, str], event: str, actor: str
) -> None:
    module, _ = harness
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_ACTOR", actor)
    monkeypatch.setenv("BOCA_IMAGE", pair[0])
    monkeypatch.setenv("BOCA_BROWSER_IMAGE", pair[1])

    class InspectedExactImage(Exception):
        pass

    def inspect(*args, **kwargs):
        assert args == ("image", "inspect", "--format", "{{json .}}", pair[0])
        assert kwargs == {}
        raise InspectedExactImage

    monkeypatch.setattr(module, "docker", inspect)
    with pytest.raises(InspectedExactImage):
        module.main()


@pytest.mark.parametrize(
    "pair",
    [
        (CI[0], LEGACY[1]),
        (LEGACY[0], CI[1]),
        (CI[1], CI[0]),
        (CI[0] + "-extra", CI[1]),
        (CI[0], CI[1] + "-extra"),
        (CI[0].replace(SHA, "b" * 40), CI[1]),
        (CI[0], CI[1].replace(SHA, "b" * 40)),
        ("boca-socios-ci:latest", CI[1]),
        ("foreign/boca-socios-ci:" + SHA, CI[1]),
        ("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64, CI[1]),
        (CI[0].replace(SHA, SHA.upper()), CI[1]),
    ],
)
def test_wrong_role_mixed_family_or_malformed_tag_never_reaches_docker(
    harness, monkeypatch: pytest.MonkeyPatch, pair: tuple[str, str]
) -> None:
    module, _ = harness
    monkeypatch.setenv("BOCA_IMAGE", pair[0])
    monkeypatch.setenv("BOCA_BROWSER_IMAGE", pair[1])
    monkeypatch.setattr(module, "docker", lambda *a, **kw: pytest.fail("Docker reached"))
    with pytest.raises(AssertionError):
        module.main()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GITHUB_EVENT_NAME", "pull_request_target"),
        ("GITHUB_EVENT_NAME", "schedule"),
        ("RUNNER_ENVIRONMENT", "self-hosted"),
        ("GITHUB_ACTIONS", "false"),
        ("GITHUB_REPOSITORY", "foreign/boca-socios-assistant"),
        ("GITHUB_SHA", "a" * 39),
        ("GITHUB_RUN_ID", "0"),
    ],
)
def test_untrusted_context_never_reaches_docker(
    harness, monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    module, _ = harness
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, "docker", lambda *a, **kw: pytest.fail("Docker reached"))
    with pytest.raises(AssertionError):
        module.main()


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GITHUB_REF", "refs/heads/feature/unreviewed"),
        ("GITHUB_REF", "refs/tags/main"),
    ],
)
def test_non_pr_requires_owned_main_context(
    harness, monkeypatch: pytest.MonkeyPatch, event: str, key: str, value: str
) -> None:
    module, _ = harness
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, "docker", lambda *a, **kw: pytest.fail("Docker reached"))
    with pytest.raises(AssertionError):
        module.main()


def test_manual_dispatch_rejects_non_owner(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = harness
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_ACTOR", "integration[bot]")
    monkeypatch.setattr(module, "docker", lambda *a, **kw: pytest.fail("Docker reached"))
    with pytest.raises(AssertionError):
        module.main()


def test_fork_pr_never_reaches_docker(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    module, event = harness
    event.write_text(
        json.dumps(
            {
                "repository": {"full_name": REPOSITORY},
                "pull_request": {"head": {"repo": {"full_name": "foreign/fork"}}},
            }
        )
    )
    monkeypatch.setattr(module, "docker", lambda *a, **kw: pytest.fail("Docker reached"))
    with pytest.raises(AssertionError):
        module.main()


@pytest.mark.parametrize("pair", [LEGACY, CI])
@pytest.mark.parametrize("fault", [None, "config-tag", "image-id", "revision"])
def test_acceptance_requires_container_config_tag_and_immutable_id_to_match_pair(
    harness, monkeypatch: pytest.MonkeyPatch, pair: tuple[str, str], fault: str | None
) -> None:
    from boca_socios import host_first_deploy as deploy
    from boca_socios import host_rootless_setup as rootless

    module, _ = harness
    monkeypatch.setenv("BOCA_IMAGE", pair[0])
    monkeypatch.setenv("BOCA_BROWSER_IMAGE", pair[1])
    # main installs local adapters; restore the imported production modules
    # even when a negative fixture refuses before acceptance.
    monkeypatch.setattr(deploy, "_run", deploy._run)
    monkeypatch.setattr(deploy, "_browser_root_file", deploy._browser_root_file)
    monkeypatch.setattr(rootless, "_command", rootless._command)
    controller_id = "sha256:" + "b" * 64
    browser_id = "sha256:" + "c" * 64

    def docker(*args, **kwargs):
        assert not kwargs
        if args[:2] == ("image", "inspect"):
            assert args[-1] in pair
            return json.dumps(
                {
                    "Id": controller_id if args[-1] == pair[0] else browser_id,
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": "e" * 40
                            if fault == "revision"
                            else SHA,
                        }
                    },
                }
            )
        assert args == ("inspect", "--format", "{{json .}}", "c" * 64)
        return json.dumps(
            {
                "Id": "c" * 64,
                "Image": browser_id if fault == "image-id" else controller_id,
                "RestartCount": 0,
                "Config": {
                    "Image": pair[1] if fault == "config-tag" else pair[0],
                    "User": "10001:10001",
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.service": "controller",
                    },
                    "Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
                },
                "State": {
                    "Health": {"Status": "healthy"},
                    "Running": True,
                    "StartedAt": "2026-11-12T12:00:00Z",
                },
            }
        )

    class AcceptedExactContainer(Exception):
        pass

    def acceptance(source, controller, identity):
        assert source == SHA and controller == "c" * 64
        assert identity[1] == controller_id
        raise AcceptedExactContainer

    monkeypatch.setattr(module, "docker", docker)
    monkeypatch.setattr(module, "measure_acceptance", acceptance)
    with pytest.raises(AcceptedExactContainer if fault is None else AssertionError):
        module.main()
