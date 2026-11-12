"""Combined CODE_ONLY boundaries; no authenticated producer or host activation."""

from __future__ import annotations

import importlib
import importlib.util
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease


def modules() -> tuple[Any, Any, Any, Any]:
    return (
        importlib.import_module("boca_socios.host_boca_pair_upgrade_reusable"),
        importlib.import_module("boca_socios.host_boca_upgrade_adapters"),
        importlib.import_module("test_host_boca_pair_upgrade_reusable"),
        importlib.import_module("test_host_boca_upgrade_adapters"),
    )


def converted_pins(reusable: Any, adapters: Any) -> Any:
    # Explicit test-only conversion. No implicit adoption or production bridge.
    pins = adapters.ResourcePins(
        "42806447101",
        "3" * 64,
        "43217075287",
        "4" * 64,
        "43217075287",
        "5" * 64,
    )
    return reusable.RetainedResourcePins(
        ipc_creator_attempt=pins.ipc_creator_attempt,
        ipc_inode_sha256=pins.ipc_inode_sha256,
        site_creator_attempt=pins.site_creator_attempt,
        site_inode_sha256=pins.site_inode_sha256,
        egress_creator_attempt=pins.egress_creator_attempt,
        egress_id=pins.egress_id,
    )


def test_combined_defaults_still_require_authenticated_release_and_witness() -> None:
    _reusable, adapters, _actor_fixture, evidence_fixture = modules()
    candidate = evidence_fixture.candidate()
    first, paired = evidence_fixture.manifests()
    with pytest.raises(adapters.EvidenceNoGo):
        adapters.verify_release(
            candidate,
            controller_manifest=first,
            paired_manifest=paired,
            current_main_sha=candidate.source_sha,
        )
    with pytest.raises(adapters.EvidenceNoGo):
        adapters.verify_custody_seed(
            evidence_fixture.witness(),
            observation_run_id=evidence_fixture.WITNESS_RUN,
            observer_source_sha=evidence_fixture.OBSERVER_SOURCE,
        )


def test_adapters_pins_cannot_be_implicitly_adopted_by_actor() -> None:
    reusable, adapters, actor_fixture, _evidence_fixture = modules()
    pins = adapters.ResourcePins(
        "42806447101",
        "3" * 64,
        "43217075287",
        "4" * 64,
        "43217075287",
        "5" * 64,
    )
    with pytest.raises(reusable.ReusableUpgradeNoGo):
        reusable.ReusablePairUpgradeBackend(actor_fixture._sources(), pins)


@pytest.mark.parametrize("override_instance", (False, True))
def test_verified_formats_and_image_cleanup_accept_never_grant_pair_go(
    override_instance: bool,
) -> None:
    reusable, adapters, actor_fixture, evidence_fixture = modules()
    plan = actor_fixture._plan()
    candidate = CandidateRelease(
        plan.new_source_sha,
        plan.release_run_id,
        plan.controller_ref,
        plan.worker_ref,
    )
    controller = json.dumps(
        {
            "image_ref": plan.controller_ref,
            "source_sha": plan.new_source_sha,
            "release_run_id": plan.release_run_id,
        }
    ).encode()
    paired = json.dumps(
        {
            "source_sha": plan.new_source_sha,
            "run_id": plan.release_run_id,
            "controller_digest": plan.controller_ref,
            "browser_digest": plan.worker_ref,
        }
    ).encode()
    # This fixture is NOT an installed production authentication provider.
    auth = evidence_fixture.Authenticator(
        evidence_fixture.metadata(
            source=plan.new_source_sha,
            run=plan.release_run_id,
        )
    )
    release = adapters.verify_release(
        candidate,
        controller_manifest=controller,
        paired_manifest=paired,
        current_main_sha=plan.new_source_sha,
        authenticator=auth,
    )
    raw, before, after, removed = evidence_fixture.cleanup_case()
    cleanup = adapters.verify_cleanup(
        raw,
        evidence_fixture.ATTEMPT,
        before=before,
        after=after,
        expected_removed=removed,
    )
    assert release.apply_authorized is False
    assert cleanup.status == "ACCEPT"
    assert cleanup.apply_authorized is False
    assert cleanup.coverage == "IMAGE_RECEIPT_ONLY"
    effects: list[str] = []

    class PlausibleButUnwiredIntegration:
        def verify_release(self, *_args: Any) -> None:
            effects.append("provenance")

        def retained_resources(self, *_args: Any) -> Any:
            effects.append("read_resources")
            return converted_pins(reusable, adapters)

        def final_cleanup(self, *_args: Any) -> str:
            effects.append("cleanup")
            return cleanup.status

    actor = reusable.ReusablePairUpgradeBackend(
        actor_fixture._sources(),
        converted_pins(reusable, adapters),
        PlausibleButUnwiredIntegration(),
    )
    if override_instance:
        actor.requires_persistent_receipt = True
    with pytest.raises(transaction.PairUpgradeError):
        transaction.run_pair_upgrade(
            plan,
            backend=actor,
            terminal_preflight=lambda *_: effects.append("intent"),
            commit_marker=lambda *_: effects.append("commit"),
            terminal_sink=lambda *_: effects.append("terminal"),
        )
    assert effects == []


def test_combined_modules_are_absent_from_effectful_protected_bundle(tmp_path: Path) -> None:
    modules()
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "combined_nogo_bundle_builder", root / "scripts/build_protected_boca_bundle.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    output = tmp_path / "protected-existing-upgrade.pyz"
    builder.build(root, output, pair_upgrade=True)
    with zipfile.ZipFile(output) as archive:
        entries = set(archive.namelist())
    assert "boca_socios/host_boca_pair_upgrade_backend.py" in entries
    assert "boca_socios/host_boca_pair_upgrade_reusable.py" not in entries
    assert "boca_socios/host_boca_upgrade_adapters.py" not in entries
