"""R278: the new incident observer has no host mutation or user coordinates."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
SOURCE = ROOT / "src/boca_socios/host_boca_park_incident_readonly.py"


def test_fixed_incident_dispatch_is_owner_only_readonly() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    options = next(
        line
        for line in workflow.splitlines()
        if line.strip().startswith("options: [inspect-prerequisites")
    )
    assert options.count("boca-park-incident-observe") == 1
    script = workflow.split(
        "      - name: Witness the exact failed R277 PARK incident without effects\n", 1
    )[1].split("      - name: Classify missing protected R278 observation before SSH\n", 1)[0]
    assert "if: inputs.operation == 'boca-park-incident-observe'" in script
    assert "check_main_ref.py" in script
    assert "git rev-parse HEAD" in script
    assert '"-I"' in script and '"-B"' in script
    assert "boca-park-incident" in script
    assert "classify" in script
    assert "ssh" in script
    assert "observer_writes=0 restore_authorized=false deploy=NO_GO" in script
    assert "JOURNAL_UNVERIFIED|PARKED_BINDING_UNVERIFIED|PAIR_UNVERIFIED" in script
    assert not any(
        operation in script
        for operation in (
            "docker rm",
            "docker start",
            "docker stop",
            "docker rename",
            "sudo",
            "systemctl",
            "compose up",
        )
    )


def test_fixed_target_and_no_privileged_host_effects_in_observer() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'INCIDENT = "43479367282"' in source
    assert "PREVIOUS_SOURCE_SHA" in source
    assert '"commit_started": False' in source
    assert "O_NOFOLLOW" in source
    assert "restore_authorized" in source
    assert not any(
        bad in source
        for bad in (
            '"rm"',
            '"start"',
            '"stop"',
            '"rename"',
            '"update"',
            "os.unlink(",
            "os.rename(",
            "os.replace(",
            "os.mkdir(",
        )
    )
