"""Fixed storage operation mount contract, shared by image and host."""

MAX_FRAME = 32768
# These mount contracts are shared by the host argv builder and image entrypoint.
MOUNTS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "initialize-volume": (("boca_telegram", "/run/telegram", True),),
    "verify-schema": (("boca_data", "/data", False),),
    "recipient": (("boca_telegram", "/run/telegram", False),),
    "prepare": (("boca_telegram", "/run/telegram", True),),
    "inspect-direct": (("boca_data", "/data", False), ("boca_telegram", "/run/telegram", False)),
    "install-direct": (("boca_data", "/data", False), ("boca_telegram", "/run/telegram", True)),
    "verify-direct": (("boca_data", "/data", False), ("boca_telegram", "/run/telegram", False)),
    "archive-stage": (
        ("boca_data", "/data", True),
        ("boca_owner", "/run/owner", False),
        ("boca_telegram", "/run/telegram", False),
    ),
    "sender-evidence": (
        ("boca_data", "/data", False),
        ("boca_owner", "/run/owner", False),
        ("boca_telegram", "/run/telegram", False),
    ),
    "publish-status": (("boca_data", "/data", True), ("boca_telegram", "/run/telegram", False)),
    "publish-status-absent": (("boca_data", "/data", True),),
    "read-stage": (("boca_data", "/data", False),),
    "verify-owner": (("boca_data", "/data", False), ("boca_owner", "/run/owner", False)),
    "owner-identity": (("boca_owner", "/run/owner", False),),
    "unseal": (("boca_telegram", "/run/telegram", False),),
    "seal": (),
    "consume-nonce": (("boca_data", "/data", True),),
    "install-v2": (("boca_telegram", "/run/telegram", True),),
    "verify-v2": (("boca_telegram", "/run/telegram", False),),
    "publish-recipient": (("boca_data", "/data", True),),
}
