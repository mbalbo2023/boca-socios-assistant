"""Offline preservation of the owner's new persistent SITE_URL volume."""

from __future__ import annotations

from dataclasses import replace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from test_host_boca_cleanup import (
    ACTIVE_ID,
    ACTIVE_IMAGE,
    ATTEMPT,
    OWNED,
    _physical_observer_fixture,
)

SITE_CONFIG_VOLUME = "boca-socios_boca_site_config"


def test_attempt_labeled_site_config_cannot_be_generic_cleanup_target() -> None:
    snapshot = _physical_observer_fixture()
    snapshot = replace(
        snapshot,
        volumes=(*snapshot.volumes, cleanup.Volume(SITE_CONFIG_VOLUME, OWNED)),
    )
    selected = cleanup.plan(
        snapshot,
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset(),
    )
    assert cleanup.Target("volume", SITE_CONFIG_VOLUME) not in selected.targets
    assert not selected.uncertain


@pytest.mark.parametrize(
    "name",
    [
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_telegram",
        SITE_CONFIG_VOLUME,
    ],
)
def test_direct_cleanup_refuses_protected_volume_even_with_exact_name(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(cleanup, "_docker", lambda *args: pytest.fail("protected volume removed"))
    with pytest.raises(cleanup.CleanupError, match="protected.*volume"):
        cleanup.delete_exact(cleanup.Target("volume", name))
