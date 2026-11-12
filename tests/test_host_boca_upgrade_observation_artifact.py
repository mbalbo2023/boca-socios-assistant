"""The existing READ_ONLY selector can publish an exact, non-secret observation.

No extra Action, host mutation, browser, SSH or network is invoked by tests.
"""

from __future__ import annotations

from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def _step(name: str) -> str:
    marker = "      - name: " + name + "\n"
    assert FLOW.count(marker) == 1
    return FLOW.split(marker, 1)[1].split("      - name:", 1)[0]


def test_only_existing_observer_can_publish_exact_verified_receipt() -> None:
    observe = _step("Observe installed Boca controller and worker pair READ_ONLY")
    upload = _step("Upload authenticated candidate for installed pair observation READ_ONLY")
    assert "if: inputs.operation == 'boca-pair-observe'" in observe
    assert "if: inputs.operation == 'boca-pair-observe'" in upload
    assert "boca_socios.host_boca_pair_observe verify" in observe
    assert observe.index("boca_socios.host_boca_pair_observe verify") < observe.index(
        "boca-pair-observation.receipt"
    )
    assert "O_EXCL" in observe
    assert "O_NOFOLLOW" in observe
    assert "os.fsync" in observe
    assert "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9" in upload
    assert "name: boca-installed-pair-observation" in upload
    assert "retention-days: 2" in upload
    assert "if-no-files-found: error" in upload
    assert "${{ runner.temp }}/boca-pair-observation.receipt" in upload
    assert "boca-pair-upgrade-apply" not in upload
    for forbidden in ("docker", "ssh", "sudo", "curl", "gh run download", "GITHUB_TOKEN"):
        assert forbidden not in upload


def test_observer_does_not_include_untrusted_workflow_form_coordinates() -> None:
    observe = _step("Observe installed Boca controller and worker pair READ_ONLY")
    for forbidden in (
        "BOCA_LEGACY_CONTROLLER_ID",
        "BOCA_IMAGE_REF",
        "BOCA_BROWSER_IMAGE_REF",
        "BOCA_RELEASE_RUN_ID",
        "Config.Env",
        "boca_user",
    ):
        assert forbidden not in observe
