"""Read-only container liveness check. No external site or credential access."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def main() -> int:
    db_path = Path(os.environ.get("BOCA_DB_PATH", "/data/boca.sqlite3"))
    if not db_path.is_file():
        return 1
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0) as conn:
            row = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()
    except sqlite3.Error:
        return 1
    return 0 if row and row[0] >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
