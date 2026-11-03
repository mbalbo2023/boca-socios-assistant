"""Boca-only, read-only host browser inventory (issue #281).

This module never imports, launches, installs or configures a browser. The
protected workflow transfers it only to the existing dedicated UID 10001.
No host path, version string or exception text is printed to Actions.
"""

from __future__ import annotations

import os
import re
import shutil
import sys

_NAMES = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")


def main(source_sha: str) -> int:
    if re.fullmatch(r"[a-f0-9]{40}", source_sha) is None:
        print("BOCA_HOST_CHROME state=NO_GO kind=none uid=unverified")
        return 1
    try:
        if os.getuid() != 10001:
            print("BOCA_HOST_CHROME state=NO_GO kind=none uid=unverified")
            return 1
        for name in _NAMES:
            if shutil.which(name) is not None:
                print(f"BOCA_HOST_CHROME state=PRESENT kind={name} uid=10001")
                return 0
    except (OSError, ValueError):
        print("BOCA_HOST_CHROME state=NO_GO kind=none uid=unverified")
        return 1
    print("BOCA_HOST_CHROME state=ABSENT kind=none uid=10001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) == 2 else ""))
