"""R178: reuse protected Boca status dispatch; no independent host workflow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_normal_worker_compose_has_dedicated_outbound_bridge_but_offline_smoke_does_not() -> None:
    overlay = (ROOT / "compose.beta.browser.yaml").read_text(encoding="utf-8")
    assert "- boca_browser_egress" in overlay
    assert "name: boca-socios_boca_browser_egress" in overlay
    assert "internal: false" in overlay
    assert "network_mode: none" not in overlay
    assert "ports:" not in overlay
    release = (ROOT / ".github/workflows/release-image.yml").read_text(encoding="utf-8")
    physical = (ROOT / "src/boca_socios/host_worker_physical.py").read_text(encoding="utf-8")
    assert "--network none" in release
    assert '"--network",\n        "none"' in physical


def test_existing_dispatch_reuses_status_bundle_for_opt_in_egress_only() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    bundle = (ROOT / "scripts/build_protected_boca_bundle.py").read_text(encoding="utf-8")
    assert "beta-browser-egress-readonly" in workflow
    assert "on-demand-egress" in bundle
    assert "status(['host-egress', *sys.argv[2:]])" in bundle
    assert "inputs.operation == 'beta-browser-egress-readonly'" in workflow
    assert "Refuse egress without installed on-demand topology" in workflow
    assert "steps.reviewed_browser_model.outputs.mode != 'on-demand'" in workflow
    assert "verify-egress" in workflow
    assert '"$BOCA_OPERATION" = beta-browser-egress-readonly' in workflow
    assert "--network host" not in workflow
    assert "docker system prune" not in workflow


def test_egress_optin_excluded_from_lifecycle_start_and_effectful_cleanup() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    mark = workflow.split("- name: Mark existing browser lifecycle attempt", 1)[1].split(
        "- name:", 1
    )[0]
    operate = workflow.split("- name: Operate only proven existing browser IPC services", 1)[
        1
    ].split("- name:", 1)[0]
    assert "inputs.operation != 'beta-browser-egress-readonly'" in mark
    assert "inputs.operation != 'beta-browser-egress-readonly'" in operate
    assert "if: always() && ((inputs.operation == 'beta-browser-acceptance'" in workflow


def test_diagnostic_does_not_accept_provided_url_or_enable_browser_fixture_by_default() -> None:
    overlay = (ROOT / "compose.beta.browser.yaml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    assert 'BOCA_BROWSER_OBSERVE_MODE: "off"' in overlay
    assert "BOCA_BROWSER_EXECUTOR: automatic-observation" in overlay
    assert "BOCA_BROWSER_OBSERVE_MODE" not in workflow
    assert "worker-egress-readonly" not in overlay
