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
            "f796581efa29ed3c61390ec64e7534294b602b32ef27077dbb033d91edc4b125",
        ),
        (
            "src/boca_socios/browser/ipc_worker.py",
            "276a23376928d4c1506f96c17be14d49b582b7fb027a8c869cedaba98f9555ae",
        ),
    ],
)
def test_protected_owner_file_exact_bytes(path: str, expected: str) -> None:
    assert sha256((_ROOT / path).read_bytes()).hexdigest() == expected
