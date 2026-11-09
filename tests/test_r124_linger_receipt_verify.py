"""R124 runner-side validation of untrusted remote SSH diagnostics."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import verify_boca_linger_receipt as verifier  # noqa: E402

VALID = """BOCA_LINGER_ROOTLESS state=METADATA_CANDIDATE identity=OK linger=YES marker=REGULAR
BOCA_LINGER_DIR home=PRIVATE home_uid=10001 home_gid=10001 home_mode=0700 runtime=PRIVATE runtime_uid=10001 runtime_gid=10001 runtime_mode=0700
BOCA_LINGER_SOCKET manager=OWNED manager_uid=10001 manager_gid=10001 manager_mode=0600 bus=OWNED bus_uid=10001 bus_gid=10001 bus_mode=0600 docker_socket=OWNED docker_uid=10001 docker_gid=166523 docker_mode=0660
BOCA_LINGER_LAYOUT data_root=PRIVATE data_uid=10001 data_gid=10001 data_mode=0700 unit=REGULAR unit_uid=10001 unit_gid=10001 unit_mode=0600 marker=REGULAR marker_uid=0 marker_gid=0 marker_mode=0644
BOCA_LINGER_IDS subuid=VALID subgid=VALID newuidmap=AVAILABLE newgidmap=AVAILABLE userns=AVAILABLE
BOCA_LINGER_SCOPE docker_queries=0 changes=NONE blackbox=UNTOUCHED exitcode1_cause=UNKNOWN deploy=NO_GO
"""


def test_validator_accepts_only_full_coherent_candidate() -> None:
    assert verifier.verify(VALID.encode("ascii"), 0) == "METADATA_CANDIDATE"


def test_validator_accepts_expected_docker_data_root_0710() -> None:
    engine = VALID.replace("data_root=PRIVATE", "data_root=OWNER_0710").replace(
        "data_mode=0700", "data_mode=0710"
    )
    assert verifier.verify(engine.encode("ascii"), 0) == "METADATA_CANDIDATE"


def test_r125_does_not_revalidate_the_incorrect_r124_historical_label() -> None:
    # #890 remains valid evidence under R124 at its original workflow SHA.
    # New receipts must use OWNER_0710 for the same metadata tuple.
    historical = VALID.replace("data_root=PRIVATE", "data_root=UNSAFE").replace(
        "data_mode=0700", "data_mode=0710"
    )
    with pytest.raises(verifier.ReceiptError):
        verifier.verify(historical.encode("ascii"), 0)


@pytest.mark.parametrize(
    "altered",
    [
        VALID.replace("data_root=PRIVATE", "data_root=OWNER_0710"),
        VALID.replace("data_root=PRIVATE", "data_root=OWNER_0710").replace(
            "data_mode=0700", "data_mode=0711"
        ),
        VALID.replace("data_root=PRIVATE", "data_root=OWNER_0710").replace(
            "data_mode=0700", "data_mode=0777"
        ),
        VALID.replace("data_root=PRIVATE", "data_root=OWNER_0710")
        .replace("data_mode=0700", "data_mode=0710")
        .replace("data_gid=10001", "data_gid=166523"),
        VALID.replace("data_root=PRIVATE", "data_root=UNSAFE").replace(
            "data_mode=0700", "data_mode=0710"
        ),
    ],
)
def test_validator_rejects_forged_docker_default_or_insecure_metadata(altered: str) -> None:
    with pytest.raises(verifier.ReceiptError):
        verifier.verify(altered.encode("ascii"), 0)


def test_validator_accepts_systemd_default_socket_mode_inside_private_runtime() -> None:
    systemd = (
        VALID.replace("manager=OWNED", "manager=SYSTEMD_DEFAULT")
        .replace("manager_mode=0600", "manager_mode=0666")
        .replace("bus=OWNED", "bus=SYSTEMD_DEFAULT")
        .replace("bus_mode=0600", "bus_mode=0666")
    )
    assert verifier.verify(systemd.encode("ascii"), 0) == "METADATA_CANDIDATE"


def test_validator_rejects_systemd_default_when_runtime_public_or_docker_open() -> None:
    systemd = VALID.replace("bus=OWNED", "bus=SYSTEMD_DEFAULT").replace(
        "bus_mode=0600", "bus_mode=0666"
    )
    with pytest.raises(verifier.ReceiptError):
        verifier.verify(systemd.replace("runtime_mode=0700", "runtime_mode=0755").encode(), 0)
    with pytest.raises(verifier.ReceiptError):
        verifier.verify(
            systemd.replace("docker_socket=OWNED", "docker_socket=SYSTEMD_DEFAULT")
            .replace("docker_mode=0660", "docker_mode=0666")
            .encode(),
            0,
        )


def test_validator_rejects_absent_with_forged_metadata() -> None:
    forged = VALID.replace("marker=REGULAR", "marker=ABSENT").replace(
        "marker_uid=0", "marker_uid=10001"
    )
    with pytest.raises(verifier.ReceiptError):
        verifier.verify(forged.encode(), 0)


def test_validator_accepts_explicit_unproven_metadata_without_losing_receipt() -> None:
    failed = VALID.replace("METADATA_CANDIDATE", "PREREQUISITES_UNPROVEN").replace(
        "linger=YES", "linger=NO"
    )
    assert verifier.verify(failed.encode("ascii"), 1) == "PREREQUISITES_UNPROVEN"


@pytest.mark.parametrize(
    "altered",
    [
        VALID + "secret-sentinel\n",
        VALID.replace("docker_queries=0", "docker_queries=1"),
        VALID.replace("docker_gid=166523", "docker_gid=166523 secret-sentinel=x"),
        VALID.replace("manager_mode=0600", "manager_mode=7777"),
        VALID.replace("home_uid=10001", "home_uid=4294967296"),
        VALID.replace("linger=YES", "linger=YES\nsecret-sentinel"),
        VALID.replace("marker=REGULAR", "marker=UNVERIFIED", 1),
        VALID.replace("subuid=VALID", "subuid=UNKNOWN"),
        VALID.replace("docker_socket=OWNED", "docker_socket=OPEN_MODE"),
        VALID.removesuffix("\n"),
        "\n".join(VALID.splitlines()[:4]) + "\n",
    ],
)
def test_validator_rejects_malformed_unsafe_truncated_or_inconsistent_receipts(
    altered: str,
) -> None:
    with pytest.raises(verifier.ReceiptError):
        verifier.verify(altered.encode("ascii"), 0)


@pytest.mark.parametrize("code", [1, 2, 124, 255])
def test_validator_rejects_candidate_with_transport_or_remote_failure(code: int) -> None:
    with pytest.raises(verifier.ReceiptError):
        verifier.verify(VALID.encode("ascii"), code)


def test_validator_rejects_non_ascii_or_oversized_report() -> None:
    for blob in (b"secret-sentinel\xff\n", VALID.encode("ascii") * 12):
        with pytest.raises(verifier.ReceiptError):
            verifier.verify(blob, 0)


def test_main_emits_fixed_no_go_not_raw_remote_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "receipt"
    output = tmp_path / "github-output"
    output.touch()
    receipt.write_text(VALID + "\nsecret-sentinel", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["verifier", str(receipt), "0", str(output)])
    assert verifier.main() == 1
    streams = capsys.readouterr()
    assert "secret-sentinel" not in streams.out + streams.err
    assert "NO_GO" in streams.out + streams.err
    assert output.read_text() == ""


def test_main_emits_validated_receipt_and_typed_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "receipt"
    output = tmp_path / "github-output"
    output.touch()
    receipt.write_text(VALID, encoding="ascii")
    monkeypatch.setattr(sys, "argv", ["verifier", str(receipt), "0", str(output)])
    assert verifier.main() == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("BOCA_LINGER_ROOTLESS")
    assert "BOCA_LINGER_SCOPE" in captured.out
    assert output.read_text() == "candidate=true\n"


def test_main_valid_unproven_marks_candidate_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "receipt"
    output = tmp_path / "github-output"
    output.touch()
    receipt.write_text(
        VALID.replace("METADATA_CANDIDATE", "PREREQUISITES_UNPROVEN").replace(
            "linger=YES", "linger=UNKNOWN"
        ),
        encoding="ascii",
    )
    monkeypatch.setattr(sys, "argv", ["verifier", str(receipt), "1", str(output)])
    assert verifier.main() == 0
    assert output.read_text() == "candidate=false\n"
