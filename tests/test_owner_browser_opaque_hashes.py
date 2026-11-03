"""Owner-only files are checked by bytes; the test does not import their code."""

from hashlib import sha256
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "src/boca_socios/browser/synthetic.py",
            "52cd3996548eb318253aecd11d9ffc5bfa04c609be400fdb1ce4863dba4eeeaa",
        ),
        (
            "src/boca_socios/browser/ipc_worker.py",
            "b1286e77b0ff2ee0bc2473b27895bbe1b0f376a4efcf921f5f1c88aabc649ebe",
        ),
    ],
)
def test_protected_owner_file_exact_bytes(path: str, expected: str) -> None:
    assert sha256((_ROOT / path).read_bytes()).hexdigest() == expected
