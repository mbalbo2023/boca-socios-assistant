"""Regression: byte-identical legacy/target Compose is a valid Cutover A plan.

The installed original is independently authenticated by immutable source,
OCI image digest, historical release and exact container ID; Compose equality
cannot serve as evidence that two different releases are the same image.
These are pure in-memory checks. No host invocation or file I/O is performed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from boca_socios.host_boca_cutover import CutoverError, CutoverPlan


def _historical_same_compose_plan() -> CutoverPlan:
    return CutoverPlan(
        attempt_id="42084495400",
        legacy_id="2" * 64,
        legacy_sha="a" * 40,
        legacy_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64,
        legacy_compose_sha="1" * 64,
        target_sha="b" * 40,
        target_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
        browser_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64,
        target_compose_sha="1" * 64,
        overlay_sha="3" * 64,
        seccomp_sha="4" * 64,
        owner_subject="boca_owner",
    )


def test_cutover_accepts_same_legacy_target_compose_with_distinct_provenance() -> None:
    plan = _historical_same_compose_plan()
    assert plan.legacy_compose_sha == plan.target_compose_sha
    assert plan.legacy_sha != plan.target_sha
    assert plan.legacy_image != plan.target_image
    plan.validate()


@pytest.mark.parametrize(
    ("changed_field", "value"),
    [
        ("overlay_sha", "1" * 64),
        ("seccomp_sha", "1" * 64),
        ("overlay_sha", "4" * 64),
        ("legacy_compose_sha", "3" * 64),
        ("legacy_compose_sha", "4" * 64),
        ("legacy_compose_sha", "non-digest"),
    ],
)
def test_cutover_still_rejects_compose_overlay_and_seccomp_aliases(
    changed_field: str, value: str
) -> None:
    plan = replace(_historical_same_compose_plan(), **{changed_field: value})
    with pytest.raises(CutoverError, match="coordinates untrusted"):
        plan.validate()


def test_cutover_still_rejects_equal_source_or_oci_image() -> None:
    plan = _historical_same_compose_plan()
    for changed in (
        replace(plan, target_sha=plan.legacy_sha),
        replace(plan, target_image=plan.legacy_image),
    ):
        with pytest.raises(CutoverError, match="coordinates untrusted"):
            changed.validate()
