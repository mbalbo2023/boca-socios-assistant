"""Prevent pytest from importing externally validated owner browser blackboxes.

The protected files are never imported, opened, introspected or executed by
this guard. Only their public module names are used for a fail-closed fence.
"""

from __future__ import annotations

import importlib.abc
import sys

OWNER_BLACKBOX_MODULES = frozenset(
    {
        "boca_socios.browser.synthetic",
        "boca_socios.browser.ipc_worker",
    }
)


class _OwnerBlackboxImportFence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname in OWNER_BLACKBOX_MODULES:
            raise AssertionError("pytest must not import owner-controlled browser blackboxes")
        return None


assert not OWNER_BLACKBOX_MODULES.intersection(sys.modules)
sys.meta_path.insert(0, _OwnerBlackboxImportFence())
